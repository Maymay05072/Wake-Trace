from datetime import UTC, datetime, timedelta

from waketrace.storage import SQLiteStore


def test_content_is_not_replayed_as_fact(tmp_path):
    store = SQLiteStore(tmp_path / "wake.db")
    now = datetime.now(UTC)
    cycle = store.start_cycle("test", "seed", now)
    store.add_trace(
        cycle,
        outcome="trace",
        fact="A factual line.",
        content="A long emotional paragraph that must not return.",
        share="",
        notified=False,
        fact_source="self_report",
        evidence=[],
        now=now,
    )
    assert store.recent_facts() == ["A factual line."]


def test_residue_expires_and_is_replaced(tmp_path):
    store = SQLiteStore(tmp_path / "wake.db")
    now = datetime.now(UTC)
    store.replace_residue("first", now - timedelta(hours=25))
    assert store.fresh_residue(24, now) == ""
    store.replace_residue("second", now)
    assert store.fresh_residue(24, now) == "second"


def test_runtime_lease_blocks_a_second_owner(tmp_path):
    store = SQLiteStore(tmp_path / "wake.db")
    now = datetime.now(UTC)
    assert store.acquire_lease(
        "wake", "one", now=now, expires_at=now + timedelta(minutes=5)
    )
    assert not store.acquire_lease(
        "wake", "two", now=now, expires_at=now + timedelta(minutes=5)
    )
    store.release_lease("wake", "one")
    assert store.acquire_lease(
        "wake", "two", now=now, expires_at=now + timedelta(minutes=5)
    )
