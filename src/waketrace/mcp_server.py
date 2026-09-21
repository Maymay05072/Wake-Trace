from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from . import __version__
from .config import Settings
from .engine import WakeEngine
from .lifeworld import LifeWorld, SelectedSeed
from .models import WakeDraft, WakeSeed


def build_mcp_server(settings: Settings, engine: WakeEngine) -> FastMCP:
    """Build the stateless Streamable HTTP MCP surface for WakeTrace."""
    allowed_hosts = [item.strip() for item in settings.mcp_allowed_hosts.split(",") if item.strip()]
    server = FastMCP(
        "WakeTrace",
        instructions=(
            "Read WakeTrace continuity through the read tools. Writes are explicit and may be "
            "disabled. For an official-client scheduled wake, call waketrace_prepare_wake once, "
            "then exactly one of waketrace_finish_wake or waketrace_abort_wake."
        ),
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(allowed_hosts=allowed_hosts),
    )
    store = engine.store
    lifeworld = LifeWorld(settings, store)

    @server.tool(name="waketrace_status")
    def status() -> dict[str, Any]:
        """Read runtime status, version, companion name, and next wake time."""
        return {
            "version": __version__,
            "companion_name": settings.companion_name,
            "next_wake_at": store.get_state("next_wake_at", None),
            "last_successful_wake_at": store.get_state("last_successful_wake_at", None),
            "wake_counters": store.get_state("wake_counters", {}),
            "write_enabled": settings.mcp_allow_write,
            "external_wake_enabled": settings.mcp_allow_wake,
        }

    @server.tool(name="waketrace_recent_experiences")
    def recent_experiences(limit: int = 10) -> dict[str, Any]:
        """Read recent autonomous experiences from the WakeTrace timeline."""
        return {"timeline": store.recent_timeline(max(1, min(limit, 30)))}

    @server.tool(name="waketrace_trace_detail")
    def trace_detail(trace_id: int) -> dict[str, Any]:
        """Read one experience with its safe tool evidence summaries."""
        entry = store.timeline_detail(trace_id)
        return {"entry": entry} if entry else {"error": "timeline entry not found"}

    @server.tool(name="waketrace_list_threads")
    def list_threads() -> dict[str, Any]:
        """Read the companion's open life threads."""
        return {"threads": store.list_life_threads()}

    @server.tool(name="waketrace_list_artifacts")
    def list_artifacts(limit: int = 20) -> dict[str, Any]:
        """Read the index of artifacts created during autonomous wakes."""
        return {"artifacts": store.list_life_artifacts(max(1, min(limit, 100)))}

    @server.tool(name="waketrace_submit_event")
    def submit_event(
        summary: str,
        kind: str = "external",
        evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Explicitly hand a real-world event to WakeTrace for a later wake."""
        denied = _require_capability(settings.mcp_allow_write, "MCP write capability is disabled")
        if denied:
            return denied
        event_id = store.enqueue_world_event(kind, summary, evidence=evidence or {})
        return {"ok": True, "event_id": event_id}

    @server.tool(name="waketrace_handoff_chat")
    def handoff_chat(summary: str, source: str = "chat") -> dict[str, Any]:
        """Explicitly pass a short chat summary back into life; never copies a full chat."""
        denied = _require_capability(settings.mcp_allow_write, "MCP write capability is disabled")
        if denied:
            return denied
        event_id = store.enqueue_world_event(
            "chat_handoff",
            summary,
            evidence={"source": source[:80], "explicit_handoff": True},
        )
        return {"ok": True, "event_id": event_id}

    @server.tool(name="waketrace_prepare_wake")
    def prepare_wake() -> dict[str, Any]:
        """Claim one due external wake and return its bounded continuity context."""
        denied = _require_capability(
            settings.mcp_allow_wake,
            "External MCP wake capability is disabled",
        )
        if denied:
            return denied
        now = datetime.now(UTC)
        wake_id = uuid.uuid4().hex
        if not store.acquire_lease(
            "wake_cycle",
            wake_id,
            now=now,
            expires_at=now + timedelta(minutes=15),
        ):
            return {"ok": False, "reason": "busy"}
        next_wake_at = store.get_state("next_wake_at", "")
        if next_wake_at:
            try:
                due_at = datetime.fromisoformat(str(next_wake_at))
                if due_at.tzinfo is None:
                    due_at = due_at.replace(tzinfo=UTC)
            except ValueError:
                due_at = now
            if now < due_at:
                store.release_lease("wake_cycle", wake_id)
                return {
                    "ok": False,
                    "reason": "not_due",
                    "retry_at": due_at.isoformat(),
                }
        gate = engine.policy.allow_wake(now)
        if not gate.allowed:
            retry_at = gate.retry_at or engine.policy.choose_next(now)
            store.set_state("next_wake_at", retry_at.isoformat(), now)
            store.release_lease("wake_cycle", wake_id)
            return {"ok": False, "reason": gate.reason, "retry_at": retry_at.isoformat()}

        selected = lifeworld.select_seed(now)
        cycle_id = store.start_cycle(selected.seed.kind, selected.seed.summary, now)
        store.set_state(
            _pending_key(wake_id),
            {
                "cycle_id": cycle_id,
                "created_at": now.isoformat(),
                "seed": {
                    "kind": selected.seed.kind,
                    "summary": selected.seed.summary,
                    "occurred_at": selected.seed.occurred_at.isoformat(),
                    "evidence": selected.seed.evidence,
                },
                "event_id": selected.event_id,
                "claim_token": selected.claim_token,
            },
            now,
        )
        return {
            "ok": True,
            "wake_id": wake_id,
            "cycle_id": cycle_id,
            "seed": {
                "kind": selected.seed.kind,
                "summary": selected.seed.summary,
                "evidence": selected.seed.evidence,
            },
            "recent_facts": store.recent_facts(settings.recent_fact_limit),
            "residue": store.fresh_residue(settings.residue_ttl_hours, now),
            "instruction": (
                "Treat this as private autonomous time. Finish with waketrace_finish_wake; "
                "use waketrace_abort_wake if you cannot complete it. A wake need not send a message."
            ),
        }

    @server.tool(name="waketrace_finish_wake")
    def finish_wake(
        wake_id: str,
        outcome: str,
        fact: str = "",
        content: str = "",
        share: str = "",
        residue: str = "",
        next_min_minutes: int | None = None,
        next_max_minutes: int | None = None,
    ) -> dict[str, Any]:
        """Finish a prepared external wake and commit its fact/content split."""
        denied = _require_capability(
            settings.mcp_allow_wake,
            "External MCP wake capability is disabled",
        )
        if denied:
            return denied
        pending = store.get_state(_pending_key(wake_id), None)
        if not isinstance(pending, dict):
            return {"ok": False, "reason": "unknown_or_expired_wake"}
        if outcome not in {"silent", "trace", "message"}:
            return {"ok": False, "reason": "invalid_outcome"}
        if outcome == "message" and not share.strip():
            return {"ok": False, "reason": "message_without_share"}
        if outcome == "silent" and share.strip():
            return {"ok": False, "reason": "silent_with_share"}

        selected = _selected_seed(pending)
        cycle_id = int(pending["cycle_id"])
        try:
            result = engine.commit_external(
                cycle_id,
                WakeDraft(
                    outcome=outcome,
                    fact=fact[:1200],
                    content=content[:4000],
                    share=share[:1000],
                    residue=residue[:200],
                    next_min_minutes=next_min_minutes,
                    next_max_minutes=next_max_minutes,
                ),
            )
            lifeworld.settle_seed(selected, result)
            return {
                "ok": True,
                "cycle_id": result.cycle_id,
                "outcome": result.outcome,
                "notified": result.notified,
                "next_wake_at": result.next_wake_at.isoformat(),
            }
        except Exception as exc:  # noqa: BLE001 - keep the external wake lease recoverable
            lifeworld.release_seed(selected)
            store.finish_cycle(cycle_id, status="failed", error_code=type(exc).__name__)
            return {"ok": False, "reason": "commit_failed"}
        finally:
            store.delete_state(_pending_key(wake_id))
            store.release_lease("wake_cycle", wake_id)

    @server.tool(name="waketrace_abort_wake")
    def abort_wake(wake_id: str, reason: str = "client_aborted") -> dict[str, Any]:
        """Abort a prepared external wake without consuming its claimed event."""
        denied = _require_capability(
            settings.mcp_allow_wake,
            "External MCP wake capability is disabled",
        )
        if denied:
            return denied
        pending = store.get_state(_pending_key(wake_id), None)
        if not isinstance(pending, dict):
            return {"ok": False, "reason": "unknown_or_expired_wake"}
        lifeworld.release_seed(_selected_seed(pending))
        store.finish_cycle(
            int(pending["cycle_id"]),
            status="failed",
            error_code=f"external_abort:{reason}"[:160],
        )
        store.delete_state(_pending_key(wake_id))
        store.release_lease("wake_cycle", wake_id)
        return {"ok": True}

    return server


def _require_capability(enabled: bool, reason: str) -> dict[str, Any] | None:
    return None if enabled else {"ok": False, "reason": reason}


def _pending_key(wake_id: str) -> str:
    return f"mcp_pending_wake:{wake_id[:64]}"


def _selected_seed(pending: dict[str, Any]) -> SelectedSeed:
    raw = pending.get("seed") or {}
    occurred_at = datetime.fromisoformat(str(raw.get("occurred_at")))
    return SelectedSeed(
        WakeSeed(
            str(raw.get("kind") or "external"),
            str(raw.get("summary") or ""),
            occurred_at,
            raw.get("evidence") if isinstance(raw.get("evidence"), dict) else {},
        ),
        event_id=pending.get("event_id"),
        claim_token=str(pending.get("claim_token") or ""),
    )
