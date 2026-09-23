#!/usr/bin/env python3
"""取一条醒来任务 → 读小红书 → 写回执。

给 Operit 那边的工作流调用：每 15 分钟跑一次，没有没认领的任务就打印 NONE 直接退出。
读取用的是我们自己的 xhs 模块（短链也认），不走会读空的插件。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from waketrace import xhs  # noqa: E402
from waketrace.inbox import Inbox  # noqa: E402


def main() -> int:
    inbox = Inbox()
    task = inbox.next()
    if not task:
        print("NONE")
        return 0

    target = str(task.get("target") or "")
    print(f"认领 {task.get('id')} → {target}")

    try:
        note = xhs.read(target, comment_limit=8)
    except Exception as exc:
        text = f"[读取失败] {target}\n{type(exc).__name__}: {exc}"
        inbox.save_result(text)
        print(text)
        return 1

    text = xhs.render(note, 6000)
    inbox.save_result(text)
    print(f"已写入回执（{len(text)} 字符）：{note.get('title') or '（无标题）'}")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())