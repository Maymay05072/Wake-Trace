from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS wake_cycles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trigger_kind TEXT NOT NULL,
    seed_summary TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    outcome TEXT,
    error_code TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS traces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id INTEGER NOT NULL,
    outcome TEXT NOT NULL,
    fact TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT '',
    share TEXT NOT NULL DEFAULT '',
    notified INTEGER NOT NULL DEFAULT 0,
    fact_source TEXT NOT NULL DEFAULT 'self_report',
    evidence_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    FOREIGN KEY (cycle_id) REFERENCES wake_cycles(id)
);

CREATE TABLE IF NOT EXISTS tool_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id INTEGER NOT NULL,
    call_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    ok INTEGER NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY (cycle_id) REFERENCES wake_cycles(id),
    UNIQUE(cycle_id, call_id)
);

CREATE TABLE IF NOT EXISTS runtime_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runtime_leases (
    key TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS push_subscriptions (
    endpoint TEXT PRIMARY KEY,
    subscription_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS world_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    summary TEXT NOT NULL,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    available_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    claim_token TEXT,
    claim_expires_at TEXT,
    consumed_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS life_threads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    origin TEXT NOT NULL,
    latest_note TEXT NOT NULL DEFAULT '',
    next_pull TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    closed_at TEXT
);

CREATE TABLE IF NOT EXISTS life_thread_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    note TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (thread_id) REFERENCES life_threads(id)
);

CREATE TABLE IF NOT EXISTS life_artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    media_type TEXT NOT NULL DEFAULT 'text/markdown',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_traces_created_at ON traces(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_cycles_started_at ON wake_cycles(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_world_events_ready
    ON world_events(status, available_at, id);
CREATE INDEX IF NOT EXISTS idx_life_threads_status
    ON life_threads(status, updated_at DESC);
"""


def _iso(value: datetime | None = None) -> str:
    return (value or datetime.now(UTC)).astimezone(UTC).isoformat()


class SQLiteStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    def start_cycle(self, trigger_kind: str, seed_summary: str, now: datetime) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO wake_cycles(trigger_kind, seed_summary, started_at) VALUES(?,?,?)",
                (trigger_kind[:64], seed_summary[:1000], _iso(now)),
            )
            return int(cur.lastrowid)

    def finish_cycle(
        self,
        cycle_id: int,
        *,
        status: str,
        outcome: str | None = None,
        error_code: str | None = None,
        now: datetime | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE wake_cycles SET status=?, outcome=?, error_code=?, finished_at=? WHERE id=?",
                (status, outcome, error_code, _iso(now), cycle_id),
            )

    def add_trace(
        self,
        cycle_id: int,
        *,
        outcome: str,
        fact: str,
        content: str,
        share: str,
        notified: bool,
        fact_source: str,
        evidence: list[dict[str, Any]],
        now: datetime,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO traces
                   (cycle_id, outcome, fact, content, share, notified,
                    fact_source, evidence_json, created_at)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    cycle_id,
                    outcome,
                    fact[:1200],
                    content[:4000],
                    share[:1000],
                    int(notified),
                    fact_source,
                    json.dumps(evidence, ensure_ascii=False),
                    _iso(now),
                ),
            )

    def acquire_lease(
        self,
        key: str,
        owner: str,
        *,
        now: datetime,
        expires_at: datetime,
    ) -> bool:
        """取得跨进程租约；若已有尚未过期的持有者则拒绝。"""
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT owner, expires_at FROM runtime_leases WHERE key=?", (key,)
            ).fetchone()
            if row:
                try:
                    expiry = datetime.fromisoformat(row["expires_at"])
                except ValueError:
                    expiry = now
                if expiry > now and row["owner"] != owner:
                    return False
            conn.execute(
                """INSERT INTO runtime_leases(key, owner, expires_at) VALUES(?,?,?)
                   ON CONFLICT(key) DO UPDATE SET
                   owner=excluded.owner, expires_at=excluded.expires_at""",
                (key, owner, _iso(expires_at)),
            )
            return True

    def release_lease(self, key: str, owner: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM runtime_leases WHERE key=? AND owner=?", (key, owner))

    def recent_facts(self, limit: int = 8) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT fact FROM traces
                   WHERE trim(fact) != ''
                   ORDER BY id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [str(row["fact"]) for row in reversed(rows)]

    def record_tool_event(
        self,
        cycle_id: int,
        call_id: str,
        tool_name: str,
        ok: bool,
        summary: str,
        result: Any,
        now: datetime,
    ) -> None:
        try:
            result_json = json.dumps(result, ensure_ascii=False, default=str)[:8000]
        except (TypeError, ValueError, RecursionError):
            result_json = json.dumps({"unserializable": True})
        with self.connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO tool_events
                   (cycle_id, call_id, tool_name, ok, summary, result_json, created_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (cycle_id, call_id, tool_name, int(ok), summary[:500], result_json, _iso(now)),
            )

    def get_state(self, key: str, default: Any = None) -> Any:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM runtime_state WHERE key=?", (key,)).fetchone()
        if not row:
            return default
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            return default

    def set_state(self, key: str, value: Any, now: datetime | None = None) -> None:
        raw = json.dumps(value, ensure_ascii=False, default=str)
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO runtime_state(key, value, updated_at) VALUES(?,?,?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
                (key, raw, _iso(now)),
            )

    def fresh_residue(self, ttl_hours: int, now: datetime) -> str:
        value = self.get_state("residue", {})
        if not isinstance(value, dict) or not str(value.get("text", "")).strip():
            return ""
        try:
            saved_at = datetime.fromisoformat(value["saved_at"])
            if saved_at.tzinfo is None:
                saved_at = saved_at.replace(tzinfo=UTC)
        except (KeyError, TypeError, ValueError):
            return ""
        if now.astimezone(UTC) - saved_at.astimezone(UTC) > timedelta(hours=ttl_hours):
            self.set_state("residue", {}, now)
            return ""
        return str(value["text"])[:200]

    def replace_residue(self, text: str, now: datetime) -> None:
        payload = {"text": text[:200], "saved_at": _iso(now)} if text.strip() else {}
        self.set_state("residue", payload, now)

    def add_subscription(self, subscription: dict[str, Any], now: datetime | None = None) -> None:
        endpoint = str(subscription.get("endpoint", "")).strip()
        if not endpoint:
            raise ValueError("subscription endpoint is required")
        raw = json.dumps(subscription, ensure_ascii=False)
        timestamp = _iso(now)
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO push_subscriptions(endpoint, subscription_json, created_at, updated_at)
                   VALUES(?,?,?,?) ON CONFLICT(endpoint) DO UPDATE SET
                   subscription_json=excluded.subscription_json, updated_at=excluded.updated_at""",
                (endpoint, raw, timestamp, timestamp),
            )

    def subscriptions(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT subscription_json FROM push_subscriptions").fetchall()
        return [json.loads(row["subscription_json"]) for row in rows]

    def remove_subscription(self, endpoint: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM push_subscriptions WHERE endpoint=?", (endpoint,))

    def enqueue_world_event(
        self,
        kind: str,
        summary: str,
        *,
        evidence: dict[str, Any] | None = None,
        available_at: datetime | None = None,
        now: datetime | None = None,
    ) -> int:
        timestamp = now or datetime.now(UTC)
        ready_at = available_at or timestamp
        clean_summary = summary.strip()
        if not clean_summary:
            raise ValueError("world event summary is required")
        with self.connect() as conn:
            cur = conn.execute(
                """INSERT INTO world_events
                   (kind, summary, evidence_json, available_at, created_at)
                   VALUES(?,?,?,?,?)""",
                (
                    kind.strip()[:64] or "event",
                    clean_summary[:1000],
                    json.dumps(evidence or {}, ensure_ascii=False, default=str)[:8000],
                    _iso(ready_at),
                    _iso(timestamp),
                ),
            )
            return int(cur.lastrowid)

    def claim_world_event(
        self,
        *,
        now: datetime,
        claim_token: str,
        lease_minutes: int = 15,
    ) -> dict[str, Any] | None:
        """领取一个已到时间的生活事件；过期领取会自动回到等待状态。"""
        expires_at = now + timedelta(minutes=lease_minutes)
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """UPDATE world_events SET status='pending', claim_token=NULL,
                   claim_expires_at=NULL
                   WHERE status='claimed' AND claim_expires_at <= ?""",
                (_iso(now),),
            )
            rows = conn.execute(
                """SELECT id, kind, summary, evidence_json, available_at
                   FROM world_events
                   WHERE status='pending' AND available_at <= ?
                   ORDER BY available_at ASC, id ASC""",
                (_iso(now),),
            ).fetchall()
            for row in rows:
                try:
                    evidence = json.loads(row["evidence_json"])
                except json.JSONDecodeError:
                    evidence = {}
                if row["kind"] == "thread_due" and self._thread_is_closed(conn, evidence):
                    conn.execute(
                        "UPDATE world_events SET status='consumed', consumed_at=? WHERE id=?",
                        (_iso(now), row["id"]),
                    )
                    continue
                conn.execute(
                    """UPDATE world_events SET status='claimed', claim_token=?, claim_expires_at=?
                       WHERE id=?""",
                    (claim_token, _iso(expires_at), row["id"]),
                )
                return {
                    "id": int(row["id"]),
                    "kind": str(row["kind"]),
                    "summary": str(row["summary"]),
                    "evidence": evidence if isinstance(evidence, dict) else {},
                    "available_at": str(row["available_at"]),
                }
        return None

    def settle_world_event(self, event_id: int, claim_token: str, *, consumed: bool) -> bool:
        status = "consumed" if consumed else "pending"
        consumed_at = _iso() if consumed else None
        with self.connect() as conn:
            cur = conn.execute(
                """UPDATE world_events SET status=?, claim_token=NULL, claim_expires_at=NULL,
                   consumed_at=? WHERE id=? AND status='claimed' AND claim_token=?""",
                (status, consumed_at, event_id, claim_token),
            )
            return cur.rowcount == 1

    @staticmethod
    def _thread_is_closed(conn: sqlite3.Connection, evidence: dict[str, Any]) -> bool:
        try:
            thread_id = int(evidence.get("thread_id"))
        except (AttributeError, TypeError, ValueError):
            return False
        row = conn.execute("SELECT status FROM life_threads WHERE id=?", (thread_id,)).fetchone()
        return row is None or row["status"] == "closed"

    def create_life_thread(
        self,
        title: str,
        origin: str,
        *,
        next_pull: str = "",
        revisit_after_minutes: int | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        timestamp = now or datetime.now(UTC)
        clean_title = title.strip()
        clean_origin = origin.strip()
        if not clean_title or not clean_origin:
            return {"error": "线头标题和来处都不能为空"}
        with self.connect() as conn:
            active = conn.execute(
                "SELECT COUNT(*) AS count FROM life_threads WHERE status != 'closed'"
            ).fetchone()["count"]
            if int(active) >= 5:
                return {"error": "最多保留五根仍在生长的线头"}
            duplicate = conn.execute(
                """SELECT id FROM life_threads
                   WHERE status != 'closed' AND lower(title)=lower(?) LIMIT 1""",
                (clean_title,),
            ).fetchone()
            if duplicate:
                return {"error": "已经存在同名线头", "thread_id": int(duplicate["id"])}
            cur = conn.execute(
                """INSERT INTO life_threads
                   (title, origin, latest_note, next_pull, created_at, updated_at)
                   VALUES(?,?,?,?,?,?)""",
                (
                    clean_title[:100],
                    clean_origin[:1000],
                    clean_origin[:1000],
                    next_pull.strip()[:300],
                    _iso(timestamp),
                    _iso(timestamp),
                ),
            )
            thread_id = int(cur.lastrowid)
            conn.execute(
                """INSERT INTO life_thread_entries(thread_id, kind, note, created_at)
                   VALUES(?,?,?,?)""",
                (thread_id, "origin", clean_origin[:2000], _iso(timestamp)),
            )
        if revisit_after_minutes is not None:
            self.schedule_thread_revisit(thread_id, revisit_after_minutes, timestamp)
        return {"ok": True, "thread_id": thread_id, "title": clean_title[:100]}

    def list_life_threads(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT id, title, origin, latest_note, next_pull, status,
                   created_at, updated_at, closed_at FROM life_threads
                   WHERE status != 'closed' ORDER BY updated_at DESC, id DESC LIMIT 5"""
            ).fetchall()
        return [dict(row) for row in rows]

    def continue_life_thread(
        self,
        thread_id: int,
        note: str,
        *,
        next_pull: str = "",
        revisit_after_minutes: int | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        timestamp = now or datetime.now(UTC)
        clean_note = note.strip()
        if not clean_note:
            return {"error": "线头进展不能为空"}
        with self.connect() as conn:
            row = conn.execute(
                "SELECT title, status FROM life_threads WHERE id=?", (thread_id,)
            ).fetchone()
            if not row or row["status"] == "closed":
                return {"error": "线头不存在或已经结束"}
            conn.execute(
                """UPDATE life_threads SET latest_note=?, next_pull=?, updated_at=?
                   WHERE id=?""",
                (clean_note[:1000], next_pull.strip()[:300], _iso(timestamp), thread_id),
            )
            conn.execute(
                """INSERT INTO life_thread_entries(thread_id, kind, note, created_at)
                   VALUES(?,?,?,?)""",
                (thread_id, "progress", clean_note[:2000], _iso(timestamp)),
            )
        if revisit_after_minutes is not None:
            self.schedule_thread_revisit(thread_id, revisit_after_minutes, timestamp)
        return {"ok": True, "thread_id": thread_id, "title": str(row["title"])}

    def close_life_thread(
        self, thread_id: int, reason: str = "", *, now: datetime | None = None
    ) -> dict[str, Any]:
        timestamp = now or datetime.now(UTC)
        with self.connect() as conn:
            row = conn.execute(
                "SELECT title, status FROM life_threads WHERE id=?", (thread_id,)
            ).fetchone()
            if not row or row["status"] == "closed":
                return {"error": "线头不存在或已经结束"}
            conn.execute(
                """UPDATE life_threads SET status='closed', closed_at=?, updated_at=?,
                   latest_note=CASE WHEN ? != '' THEN ? ELSE latest_note END WHERE id=?""",
                (_iso(timestamp), _iso(timestamp), reason.strip(), reason.strip()[:1000], thread_id),
            )
            if reason.strip():
                conn.execute(
                    """INSERT INTO life_thread_entries(thread_id, kind, note, created_at)
                       VALUES(?,?,?,?)""",
                    (thread_id, "close", reason.strip()[:2000], _iso(timestamp)),
                )
        return {"ok": True, "thread_id": thread_id, "title": str(row["title"])}

    def schedule_thread_revisit(
        self, thread_id: int, after_minutes: int, now: datetime | None = None
    ) -> int:
        timestamp = now or datetime.now(UTC)
        minutes = max(30, min(int(after_minutes), 7 * 24 * 60))
        with self.connect() as conn:
            row = conn.execute(
                "SELECT title, next_pull, status FROM life_threads WHERE id=?", (thread_id,)
            ).fetchone()
        if not row or row["status"] == "closed":
            raise ValueError("cannot schedule a closed or missing thread")
        summary = f"线头《{row['title']}》到了可以重新看一眼的时候。"
        if row["next_pull"]:
            summary += f" 上次留下的方向：{row['next_pull']}"
        return self.enqueue_world_event(
            "thread_due",
            summary,
            evidence={"thread_id": thread_id},
            available_at=timestamp + timedelta(minutes=minutes),
            now=timestamp,
        )

    def create_life_artifact(
        self,
        title: str,
        content: str,
        *,
        media_type: str = "text/markdown",
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if media_type not in {"text/plain", "text/markdown"}:
            return {"error": "当前只允许 text/plain 或 text/markdown"}
        clean_title = title.strip()
        if not clean_title or not content.strip():
            return {"error": "作品标题和内容都不能为空"}
        timestamp = now or datetime.now(UTC)
        with self.connect() as conn:
            cur = conn.execute(
                """INSERT INTO life_artifacts(title, content, media_type, created_at)
                   VALUES(?,?,?,?)""",
                (clean_title[:120], content[:12000], media_type, _iso(timestamp)),
            )
            artifact_id = int(cur.lastrowid)
        return {
            "ok": True,
            "artifact_id": artifact_id,
            "title": clean_title[:120],
            "media_type": media_type,
        }

    def list_life_artifacts(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT id, title, media_type, created_at FROM life_artifacts
                   ORDER BY id DESC LIMIT ?""",
                (max(1, min(limit, 100)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def recent_timeline(self, limit: int = 30) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT t.id, t.cycle_id, t.outcome, t.fact, t.content, t.share,
                   t.notified, t.fact_source, t.created_at, c.trigger_kind
                   FROM traces t JOIN wake_cycles c ON c.id=t.cycle_id
                   ORDER BY t.id DESC LIMIT ?""",
                (max(1, min(limit, 100)),),
            ).fetchall()
        return [dict(row) for row in rows]
