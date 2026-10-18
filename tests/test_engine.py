import json
import logging
from datetime import UTC, datetime

import pytest

from waketrace.config import Settings
from waketrace.engine import WakeEngine
from waketrace.models import ProviderTurn, ToolCall, WakeSeed
from waketrace.storage import SQLiteStore
from waketrace.tools import RegisteredTool, ToolRegistry


class SequenceProvider:
    def __init__(self, turns):
        self.turns = iter(turns)

    def complete(self, messages, tools):
        return next(self.turns)


class RecordingNotifier:
    def __init__(self):
        self.messages = []

    def send(self, title, body, *, message_id):
        self.messages.append((title, body, message_id))
        return True


def settings(tmp_path):
    return Settings(
        db_path=tmp_path / "wake.db",
        admin_token="test-token-long-enough",
        min_interval_minutes=30,
        max_interval_minutes=60,
        quiet_hours_start=0,
        quiet_hours_end=0,
    )


def final(outcome="trace", **changes):
    payload = {
        "outcome": outcome,
        "fact": "The wake followed one seed.",
        "content": "A private trace.",
        "share": "hello" if outcome == "message" else "",
        "residue": "one loose thread",
        "next_wake": {"min_minutes": 30, "max_minutes": 60},
    }
    payload.update(changes)
    return ProviderTurn(json.dumps(payload), (), "stop")


def test_successful_tool_result_becomes_evidence(tmp_path):
    registry = ToolRegistry()
    registry.register(
        RegisteredTool(
            "look",
            "Look at a trusted test value.",
            {"type": "object", "properties": {}},
            lambda _: {"summary": "The lamp is on."},
        )
    )
    provider = SequenceProvider(
        [
            ProviderTurn("", (ToolCall("call-1", "look", {}),), "tool_calls"),
            final(),
        ]
    )
    store = SQLiteStore(tmp_path / "wake.db")
    engine = WakeEngine(settings(tmp_path), store, provider, registry, RecordingNotifier())
    result = engine.run(WakeSeed("test", "A test seed."), force=True)
    assert result.outcome == "trace"
    assert "Tool look: The lamp is on." in result.fact
    assert result.evidence[0].ok is True


def test_provider_failure_is_not_silence(tmp_path, caplog):
    class BrokenProvider:
        def complete(self, messages, tools):
            from waketrace.providers import ProviderError

            raise ProviderError("missing final response")

    store = SQLiteStore(tmp_path / "wake.db")
    engine = WakeEngine(
        settings(tmp_path), store, BrokenProvider(), ToolRegistry(), RecordingNotifier()
    )
    result = engine.run(WakeSeed("test", "A test seed."), force=True)
    assert result.outcome == "error"
    assert store.recent_facts() == []
    assert "wake failed" in caplog.text
    assert "missing final response" in caplog.text


def test_duplicate_message_is_kept_as_trace_not_sent_twice(tmp_path):
    store = SQLiteStore(tmp_path / "wake.db")
    notifier = RecordingNotifier()
    cfg = settings(tmp_path)
    first = WakeEngine(cfg, store, SequenceProvider([final("message")]), ToolRegistry(), notifier)
    second = WakeEngine(cfg, store, SequenceProvider([final("message")]), ToolRegistry(), notifier)
    now = datetime.now(UTC)
    assert first.run(WakeSeed("test", "first"), now=now, force=True).outcome == "message"
    assert second.run(WakeSeed("test", "second"), now=now, force=True).outcome == "trace"
    assert len(notifier.messages) == 1


@pytest.mark.parametrize(
    "scenario, expected_outcome, expected_reason",
    [
        ("sent", "message", "sent"),
        ("duplicate", "trace", "duplicate"),
        ("quiet_hours", "trace", "quiet_hours"),
        ("delivery_failed", "trace", "delivery_failed"),
        ("silent", "silent", "not_requested"),
    ],
)
def test_wake_diagnostics_explain_decision_without_private_text(
    tmp_path, caplog, scenario, expected_outcome, expected_reason
):
    cfg = settings(tmp_path)
    cfg.timezone = "UTC"
    now = datetime(2026, 1, 2, 12, tzinfo=UTC)
    store = SQLiteStore(tmp_path / "wake.db")
    notifier = RecordingNotifier()
    if scenario == "quiet_hours":
        cfg.quiet_hours_start = 11
        cfg.quiet_hours_end = 13
    if scenario == "duplicate":
        store.set_state("last_share", "PRIVATE_SHARE", now)
    if scenario == "delivery_failed":
        notifier.send = lambda *args, **kwargs: False
    requested = "silent" if scenario == "silent" else "message"
    provider = SequenceProvider([
        final(
            requested, fact="PRIVATE_FACT", content="PRIVATE_CONTENT",
            share="" if requested == "silent" else "PRIVATE_SHARE",
            residue="PRIVATE_RESIDUE",
        )
    ])
    engine = WakeEngine(cfg, store, provider, ToolRegistry(), notifier)
    with caplog.at_level(logging.INFO, logger="waketrace.engine"):
        result = engine.run(WakeSeed("test", "PRIVATE_SEED"), now=now, force=True)
    assert result.outcome == expected_outcome
    assert "wake started" in caplog.text
    assert "wake completed" in caplog.text
    assert f"requested_outcome={requested}" in caplog.text
    assert f"outcome={expected_outcome}" in caplog.text
    assert f"notification_reason={expected_reason}" in caplog.text
    assert "PRIVATE_" not in caplog.text
    entry = store.timeline_detail(store.recent_timeline(1)[0]["id"])
    assert entry["requested_outcome"] == requested
    assert entry["notification_reason"] == expected_reason


