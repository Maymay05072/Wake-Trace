#!/usr/bin/env python3
"""醒来收件箱：把 Wake-Trace 里"有话要对小楠说、但还没送到她"的醒来读出来。

判定条件不看 outcome，而看 traces.share 是否非空且 notified=0：
Wake-Trace 在安静时段（QUIET_HOURS）或推送渠道不可用时会保留 share、
把 outcome 记成 trace，这条话就等于没说出口。收件箱负责把它捡起来。

安静时段内收件箱直接回 NONE，绝不越过 23:00-07:00 这条线。

  --peek   只读。没有待送达的话时输出 NONE，有则输出正文（每条一行）。
  --ack    把当前待送达的醒来标记为已送达。

用法：
  python tools/wake_inbox.py --peek
  python tools/wake_inbox.py --ack
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "waketrace.db"
ENV = ROOT / ".env"
EMPTY = "NONE"


def env_value(key: str, default: str) -> str:
    if not ENV.exists():
        return default
    for line in ENV.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if stripped.startswith(f"{key}="):
            return stripped.split("=", 1)[1].strip()
    return default


def env_int(key: str, default: int) -> int:
    try:
        return int(env_value(key, str(default)))
    except ValueError:
        return default


def local_hour() -> int:
    zone_name = env_value("WAKETRACE_TIMEZONE", "UTC")
    try:
        zone = ZoneInfo(zone_name)
    except Exception:  # noqa: BLE001 - 时区名字不可用时退回 UTC
        zone = ZoneInfo("UTC")
    return datetime.now(zone).hour


def in_quiet_hours(hour: int) -> bool:
    start = env_int("WAKETRACE_QUIET_HOURS_START", 23)
    end = env_int("WAKETRACE_QUIET_HOURS_END", 7)
    if start == end:
        return False
    if start > end:
        return hour >= start or hour < end
    return start <= hour < end


def pending_lines(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """
        SELECT COALESCE(NULLIF(TRIM(share), ''), '')
        FROM traces
        WHERE notified = 0 AND TRIM(share) <> ''
        ORDER BY id
        """
    ).fetchall()
    return [str(row[0]).strip() for row in rows if str(row[0]).strip()]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Wake-Trace 醒来收件箱")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--peek", action="store_true", help="打印待送达的醒来消息")
    group.add_argument("--ack", action="store_true", help="把待送达的醒来标记为已送达")
    args = parser.parse_args(argv)

    if not DB.exists():
        print(f"数据库不存在：{DB}", file=sys.stderr)
        return 2

    if args.ack:
        conn = sqlite3.connect(DB)
        with conn:
            cursor = conn.execute(
                "UPDATE traces SET notified = 1 WHERE notified = 0 AND TRIM(share) <> ''"
            )
        conn.close()
        print(f"acked {cursor.rowcount}")
        return 0

    if in_quiet_hours(local_hour()):
        print(EMPTY)
        return 0

    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    lines = pending_lines(conn)
    conn.close()

    if not lines:
        print(EMPTY)
        return 0
    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))