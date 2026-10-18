import sqlite3
from concurrent.futures import ThreadPoolExecutor

from waketrace.storage import SCHEMA, SQLiteStore


def test_old_database_migrates_without_inventing_notification_reasons(tmp_path):
    path = tmp_path / "old.db"
    legacy_schema = SCHEMA.replace("    requested_outcome TEXT,\n", "").replace(
        "    notification_reason TEXT,\n", ""
    )
    with sqlite3.connect(path) as conn:
        conn.executescript(legacy_schema)
        conn.execute(
            "INSERT INTO wake_cycles(id, trigger_kind, seed_summary, status, outcome, started_at) "
            "VALUES(1,'test','original seed','completed','trace','2026-10-18T00:00:00+00:00')"
        )
        conn.execute(
            "INSERT INTO traces(cycle_id,outcome,content,share,notified,created_at) "
            "VALUES(1,'trace','original content','unsent message',0,'2026-10-18T00:00:00+00:00')"
        )
    # Independent startup paths must be able to repeat the additive migration.
    with ThreadPoolExecutor(max_workers=2) as pool:
        stores = list(pool.map(lambda _: SQLiteStore(path), range(2)))
    entry = stores[0].timeline_detail(1)
    assert entry["content"] == "original content"
    assert entry["share"] == "unsent message"
    assert entry["seed_summary"] == "original seed"
    assert entry["notification_reason"] is None
    assert entry["requested_outcome"] is None
