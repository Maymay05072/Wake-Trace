from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from typing import Any

import uvicorn

from .api import create_app
from .config import Settings
from .engine import WakeEngine
from .lifeworld import build_lifeworld_tools
from .models import WakeSeed
from .notifiers import ConsoleNotifier, WebPushNotifier
from .providers import OpenAICompatibleProvider
from .scheduler import WakeScheduler
from .storage import SQLiteStore


def build_engine(settings: Settings, *, console: bool = False) -> WakeEngine:
    settings.ensure_runtime_dirs()
    store = SQLiteStore(settings.db_path)
    notifier = ConsoleNotifier() if console else WebPushNotifier(settings, store)
    return WakeEngine(
        settings,
        store,
        OpenAICompatibleProvider(settings),
        build_lifeworld_tools(store),
        notifier,
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="waketrace")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db", help="initialize the SQLite database")
    serve = sub.add_parser("serve", help="serve the authenticated HTTP API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    run = sub.add_parser("run", help="run the autonomous scheduler")
    run.add_argument("--poll-seconds", type=float, default=5.0)
    run.add_argument(
        "--console",
        action="store_true",
        help="print companion messages to stdout instead of using Web Push",
    )
    wake = sub.add_parser("wake", help="run one manual wake")
    wake.add_argument("summary")
    wake.add_argument("--kind", default="manual")
    wake.add_argument("--force", action="store_true")
    wake.add_argument("--console", action="store_true")
    timeline = sub.add_parser("timeline", help="show recent wake traces without a frontend")
    timeline.add_argument("--limit", type=int, default=10)
    timeline.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    settings = Settings()
    if args.command == "init-db":
        settings.ensure_runtime_dirs()
        SQLiteStore(settings.db_path)
        print(f"initialized {settings.db_path}")
    elif args.command == "serve":
        uvicorn.run(create_app(settings), host=args.host, port=args.port)
    elif args.command == "run":
        WakeScheduler(
            build_engine(settings, console=args.console),
            args.poll_seconds,
        ).run_forever()
    elif args.command == "wake":
        engine = build_engine(settings, console=args.console)
        result = engine.run(
            WakeSeed(args.kind, args.summary, datetime.now(UTC)),
            force=args.force,
        )
        print(f"outcome={result.outcome} next={result.next_wake_at.isoformat()}")
    elif args.command == "timeline":
        settings.ensure_runtime_dirs()
        rows = SQLiteStore(settings.db_path).recent_timeline(args.limit)
        if args.as_json:
            print(json.dumps(rows, ensure_ascii=False, indent=2, default=str))
        else:
            print(render_timeline(rows))


def render_timeline(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "还没有自主醒来记录。"
    blocks: list[str] = []
    for row in rows:
        header = (
            f"[{row.get('created_at', '未知时间')}] "
            f"{row.get('outcome', 'unknown')} · {row.get('trigger_kind', 'unknown')}"
        )
        lines = [header]
        for label, key in (("事实", "fact"), ("经历", "content"), ("想说", "share")):
            value = str(row.get(key) or "").strip()
            if value:
                lines.append(f"{label}：{value}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)
