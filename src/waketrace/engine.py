from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any

from .config import Settings
from .models import ProviderTurn, ToolEvidence, WakeDraft, WakeResult, WakeSeed
from .notifiers import Notifier
from .policy import WakePolicy
from .prompt import build_system_prompt, build_wake_input
from .providers import LanguageProvider, ProviderError
from .storage import SQLiteStore
from .tools import ToolRegistry


class WakeProtocolError(ValueError):
    pass


class WakeEngine:
    def __init__(
        self,
        settings: Settings,
        store: SQLiteStore,
        provider: LanguageProvider,
        tools: ToolRegistry,
        notifier: Notifier,
    ):
        self.settings = settings
        self.store = store
        self.provider = provider
        self.tools = tools
        self.notifier = notifier
        self.policy = WakePolicy(settings, store)

    def run(self, seed: WakeSeed, *, now: datetime | None = None, force: bool = False) -> WakeResult:
        now = (now or datetime.now(UTC)).astimezone(UTC)
        lease_owner = uuid.uuid4().hex
        if not self.store.acquire_lease(
            "wake_cycle",
            lease_owner,
            now=now,
            expires_at=now + timedelta(minutes=15),
        ):
            next_at = now + timedelta(minutes=1)
            return WakeResult(0, "skipped:busy", False, next_at)

        gate = self.policy.allow_wake(now)
        if not gate.allowed and not force:
            next_at = gate.retry_at or self.policy.choose_next(now)
            self.store.set_state("next_wake_at", next_at.isoformat(), now)
            self.store.release_lease("wake_cycle", lease_owner)
            return WakeResult(0, f"skipped:{gate.reason}", False, next_at)

        cycle_id = self.store.start_cycle(seed.kind, seed.summary, now)
        evidence: list[ToolEvidence] = []
        try:
            draft = self._conversation(seed, cycle_id, evidence, now)
            result = self._commit(cycle_id, draft, evidence, now)
            self.store.finish_cycle(cycle_id, status="completed", outcome=result.outcome, now=now)
            self.policy.mark_wake(now)
            return result
        except (ProviderError, WakeProtocolError) as exc:
            code = str(exc)[:160] or type(exc).__name__
            self.store.finish_cycle(cycle_id, status="failed", error_code=code, now=now)
            retry_at = self.policy.choose_next(now)
            return WakeResult(cycle_id, "error", False, retry_at)
        finally:
            self.store.release_lease("wake_cycle", lease_owner)

    def _conversation(
        self,
        seed: WakeSeed,
        cycle_id: int,
        evidence: list[ToolEvidence],
        now: datetime,
    ) -> WakeDraft:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": build_system_prompt(self.settings)},
            {
                "role": "user",
                "content": build_wake_input(
                    seed,
                    self.store.recent_facts(self.settings.recent_fact_limit),
                    self.store.fresh_residue(self.settings.residue_ttl_hours, now),
                ),
            },
        ]
        specs = self.tools.specifications()

        for round_index in range(self.settings.max_tool_rounds + 1):
            turn = self.provider.complete(messages, specs if round_index < self.settings.max_tool_rounds else [])
            if not turn.tool_calls:
                return parse_final_draft(turn.content)
            if round_index >= self.settings.max_tool_rounds:
                raise WakeProtocolError("tool_round_limit")

            messages.append(_assistant_tool_message(turn))
            for call in turn.tool_calls:
                ok, result, summary = self.tools.execute(call.name, call.arguments)
                item = ToolEvidence(call.id, call.name, ok, summary)
                evidence.append(item)
                self.store.record_tool_event(
                    cycle_id,
                    call.id,
                    call.name,
                    ok,
                    summary,
                    result,
                    now,
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps(result, ensure_ascii=False, default=str)[:4000],
                    }
                )
        raise WakeProtocolError("missing_final_response")

    def _commit(
        self,
        cycle_id: int,
        draft: WakeDraft,
        evidence: list[ToolEvidence],
        now: datetime,
    ) -> WakeResult:
        verified = [item.summary for item in evidence if item.ok and item.summary]
        self_reported = draft.fact.strip()
        fact_parts = [self_reported] if self_reported else []
        fact_parts.extend(f"Tool {item.tool_name}: {item.summary}" for item in evidence if item.ok)
        fact = " | ".join(dict.fromkeys(fact_parts))[:1200]
        if verified and self_reported:
            fact_source = "mixed"
        elif verified:
            fact_source = "tool_evidence"
        else:
            fact_source = "self_report"

        proposed_share = draft.share.strip()
        share = proposed_share
        notified = False
        outcome = draft.outcome
        if outcome == "message":
            if self.policy.is_duplicate(share):
                share = ""
                outcome = "trace"
            elif not self.policy.can_notify(now):
                outcome = "trace"
            else:
                message_id = uuid.uuid4().hex
                notified = self.notifier.send(
                    self.settings.companion_name,
                    share,
                    message_id=message_id,
                )
                if notified:
                    self.store.set_state("last_share", share, now)
                    self.policy.mark_push(now)
                else:
                    outcome = "trace"

        self.store.replace_residue(draft.residue.strip(), now)
        self.store.add_trace(
            cycle_id,
            outcome=outcome,
            fact=fact,
            content=draft.content.strip(),
            share=proposed_share,
            notified=notified,
            fact_source=fact_source,
            evidence=[asdict(item) for item in evidence],
            now=now,
        )
        next_at = self.policy.choose_next(
            now,
            draft.next_min_minutes,
            draft.next_max_minutes,
        )
        return WakeResult(
            cycle_id,
            outcome,
            notified,
            next_at,
            fact,
            draft.content.strip(),
            proposed_share,
            tuple(evidence),
        )


def parse_final_draft(content: str) -> WakeDraft:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise WakeProtocolError("final_response_is_not_json") from exc
    if not isinstance(payload, dict):
        raise WakeProtocolError("final_response_is_not_object")
    outcome = payload.get("outcome")
    if outcome not in {"silent", "trace", "message"}:
        raise WakeProtocolError("invalid_outcome")
    share = str(payload.get("share") or "").strip()
    if outcome == "message" and not share:
        raise WakeProtocolError("message_without_share")
    if outcome == "silent" and share:
        raise WakeProtocolError("silent_with_share")
    next_wake = payload.get("next_wake") or {}
    if not isinstance(next_wake, dict):
        raise WakeProtocolError("invalid_next_wake")

    def optional_int(name: str) -> int | None:
        value = next_wake.get(name)
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise WakeProtocolError(f"invalid_{name}") from exc

    return WakeDraft(
        outcome=outcome,
        fact=str(payload.get("fact") or "")[:1200],
        content=str(payload.get("content") or "")[:4000],
        share=share[:1000],
        residue=str(payload.get("residue") or "")[:200],
        next_min_minutes=optional_int("min_minutes"),
        next_max_minutes=optional_int("max_minutes"),
        next_reason=str(next_wake.get("reason") or "")[:160],
    )


def _assistant_tool_message(turn: ProviderTurn) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": turn.content or None,
        "tool_calls": [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.arguments, ensure_ascii=False),
                },
            }
            for call in turn.tool_calls
        ],
    }
