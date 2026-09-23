#!/usr/bin/env python3
"""醒来任务的收件箱，手动用的命令行。

  --add URL [说明]   挂一条任务
  --next             取一条还没认领的（只打印链接，没有就打印 NONE）
  --pending          列出所有任务和认领状态
  --result           看看最近一份回执
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from waketrace.inbox import Inbox  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(prog="xhs_task")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--add", nargs="+", metavar="URL")
    group.add_argument("--next", action="store_true")
    group.add_argument("--pending", action="store_true")
    group.add_argument("--result", action="store_true")
    args = parser.parse_args()

    inbox = Inbox()

    if args.add:
        target = args.add[0]
        note = " ".join(args.add[1:])
        record = inbox.add(target, note)
        print(f"{record['id']}  {record['target']}")
        return 0

    if args.next:
        task = inbox.next()
        print(task.get("target", "") if task else "NONE")
        return 0

    if args.pending:
        items = inbox.pending()
        if not items:
            print("（没有任务）")
        for task, claim in items:
            state = f"已于 {claim.get('claimed_at')} 认领" if claim else "待认领"
            print(f"{task.get('id')}  {task.get('target')}  {state}")
        return 0

    text = inbox.result_text()
    print(text if text else "（还没有回执）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())