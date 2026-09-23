"""醒来任务的收件箱（写给 Operit 那边的工作流去跑）。

醒来那一刻如果读不了、或者只想把一条帖子留着慢慢看，就把它挂成一条任务。
那边的工作流每十五分钟取一条，用我们自己的 xhs 模块读完，写进 last_result.txt，
下次醒来用 xhs_results 取回来。同一条只跑一次。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .config import Settings
from .inbox import Inbox
from .tools import RegisteredTool, ToolRegistry


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n…（已截断，原文共 {len(text)} 字符）"


def register_task_tools(registry: ToolRegistry, settings: Settings) -> ToolRegistry:
    inbox = Inbox(settings.hands_task_dir)
    result_path = Path(settings.hands_task_dir) / "last_result.txt"
    limit_default = int(settings.hands_max_chars)

    def xhs_task(arguments: dict[str, Any]) -> dict[str, Any]:
        target = str(arguments.get("target") or "").strip()
        note = str(arguments.get("note") or "").strip()
        if not re.match(r"^https?://", target):
            return {"error": "target_must_be_url"}
        record = inbox.add(target, note[:500])
        return {**record, "summary": f"已把小红书任务挂出去（{record['id']}）：{target}"}

    registry.register(
        RegisteredTool(
            name="xhs_task",
            description=(
                "把一条想留着看的小红书帖子挂成任务，Operit 那边的工作流会在十五分钟内读完，"
                f"写进 {result_path}，下次醒来用 xhs_results 取。"
                "急着看的那一条不用挂——手里有 xhs_read，当场就能读。"
            ),
            parameters={
                "type": "object",
                "required": ["target"],
                "properties": {
                    "target": {"type": "string", "description": "小红书帖子链接"},
                    "note": {"type": "string", "description": "为什么想看这一条，写给自己"},
                },
                "additionalProperties": False,
            },
            handler=xhs_task,
        )
    )

    def xhs_results(arguments: dict[str, Any]) -> dict[str, Any]:
        limit = int(arguments.get("limit") or 3)
        items = inbox.pending()
        tasks = [task for task, _ in items]
        last_result = _truncate(inbox.result_text(), limit_default)
        return {
            "tasks": tasks[-limit:],
            "last_result": last_result or "（那边还没写回执）",
            "summary": f"共挂过 {len(tasks)} 条任务；回执{'有' if last_result else '还没有'}",
        }

    registry.register(
        RegisteredTool(
            name="xhs_results",
            description=(
                "取那边替我跑完的小红书回执，顺便看自己挂过哪些任务。"
                "回执没来就说明还没跑到，不要假装已经看过帖子。"
            ),
            parameters={
                "type": "object",
                "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 20}},
                "additionalProperties": False,
            },
            handler=xhs_results,
        )
    )

    return registry