#!/usr/bin/env python3
"""醒来任务的收件箱：给 Operit 那边的工作流用。

- --next         取一条还没派出去的完的任务，只打印链接（没有就打印 NONE），并记下认领时间
- --pending      列出待办与认领状态
- --result FILE  把 Operit 侧跑出来的正文落成回执，供醒来时读取
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

TASK_DIR = Path("/sdcard/Download/Operit/wake_tasks")
INBOX = TASK_DIR / "inbox.jsonl"
CLAIMS = TASK_DIR / "claims.jsonl"
RESULT = TASK_DIR / "last_result.txt"


def _lines(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _append(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def next_task() -> int:
    tasks = _lines(INBOX)
    claimed = {item.get("id") for item in _lines(CLAIMS)}
    for task in tasks:
        if task.get("id") not in claimed:
            _append(
                CLAIMS,
                {
                    "id": task.get("id"),
                    "target": task.get("target"),
                    "claimed_at": datetime.now(UTC).isoformat(),
                },
            )
            print(task.get("target", ""))
            return 0
    print("NONE")
    return 0


def pending() -> int:
    tasks = _lines(INBOX)
    claims = {item.get("id"): item for item in _lines(CLAIMS)}
    for task in tasks:
        claim = claims.get(task.get("id"))
        state = f"已于 {claim.get('claimed_at')} 认领" if claim else "待认领"
        print(f"{task.get('id')}  {task.get('target')}  {state}")
    if not tasks:
        print("（没有任务）")
    return 0


def save_result(source: str) -> int:
    text = Path(source).read_text(encoding="utf-8", errors="replace")
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(f"# 回执 {datetime.now(UTC).isoformat()}\n\n{text}", encoding="utf-8")
    print(f"已写入 {RESULT}（{len(text)} 字符）")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="xhs_task")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--next", action="store_true")
    group.add_argument("--pending", action="store_true")
    group.add_argument("--result", metavar="FILE")
    args = parser.parse_args()
    if args.next:
        return next_task()
    if args.pending:
        return pending()
    return save_result(args.result)


if __name__ == "__main__":
    raise SystemExit(main())