"""醒来任务的收件箱（写给 Operit 那边的工作流去跑）。

小红书网页版读不到内容，所以这里只做两件事：
把想看的帖子链接挂成一条任务，等那边的工作流拿插件读完，再把回执取回来。
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import Settings
from .tools import RegisteredTool, ToolRegistry


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n…（已截断，原文共 {len(text)} 字符）"


def register_task_tools(registry: ToolRegistry, settings: Settings) -> ToolRegistry:
    tasks_dir = Path(settings.hands_task_dir)
    inbox_path = tasks_dir / "inbox.jsonl"
    result_path = tasks_dir / "last_result.txt"
    limit_default = int(settings.hands_max_chars)

    def xhs_task(arguments: dict[str, Any]) -> dict[str, Any]:
        target = str(arguments.get("target") or "").strip()
        note = str(arguments.get("note") or "").strip()
        if not re.match(r"^https?://", target):
            return {"error": "target_must_be_url"}
        record = {
            "id": uuid.uuid4().hex[:8],
            "created_at": datetime.now(UTC).isoformat(),
            "target": target,
            "note": note[:500],
            "status": "pending",
        }
        tasks_dir.mkdir(parents=True, exist_ok=True)
        with inbox_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return {**record, "summary": f"已把小红书任务挂出去（{record['id']}）：{target}"}

    registry.register(
        RegisteredTool(
            name="xhs_task",
            description=(
                "小红书在醒来时读不了（网页版只回一句“打开 App”），所以这里是派活：把想看的"
                "帖子链接写成一条任务，Operit 那边的工作流会在十五分钟内拿着小红书插件去读，"
                f"读完写进 {result_path}，下次醒来用 xhs_results 取。一次只挂真的想看的那一条。"
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
        tasks: list[dict[str, Any]] = []
        if inbox_path.exists():
            for line in inbox_path.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    tasks.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        last_result = ""
        if result_path.exists():
            last_result = _truncate(
                result_path.read_text(encoding="utf-8", errors="replace"), limit_default
            )
        return {
            "tasks": tasks[-limit:],
            "last_result": last_result or "（那边还没写回执）",
            "summary": f"共挂过 {len(tasks)} 条任务；回执{'有' if last_result else '还没有'}",
        }

    registry.register(
        RegisteredTool(
            name="xhs_results",
            description=(
                "取 Operit 那边替我跑完的小红书回执，顺便看自己挂过哪些任务。"
                "回执没来就说明那边还没跑到，不要假装已经看过帖子。"
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