from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .config import Settings
from .models import WakeResult, WakeSeed
from .storage import SQLiteStore
from .tools import RegisteredTool, ToolRegistry


@dataclass(frozen=True, slots=True)
class SelectedSeed:
    seed: WakeSeed
    event_id: int | None = None
    claim_token: str = ""


class LifeWorld:
    """把外部事件、线头和自由时段整理成一次只包含一个入口的醒来种子。"""

    def __init__(self, settings: Settings, store: SQLiteStore):
        self.settings = settings
        self.store = store

    def select_seed(self, now: datetime) -> SelectedSeed:
        claim_token = uuid.uuid4().hex
        event = self.store.claim_world_event(now=now, claim_token=claim_token)
        if event:
            evidence = dict(event["evidence"])
            evidence["world_event_id"] = event["id"]
            evidence["available_at"] = event["available_at"]
            return SelectedSeed(
                WakeSeed(event["kind"], event["summary"], now, evidence),
                event_id=event["id"],
                claim_token=claim_token,
            )

        local = now.astimezone(ZoneInfo(self.settings.timezone))
        daypart = _daypart(local.hour)
        return SelectedSeed(
            WakeSeed(
                "free_window",
                f"{local.date().isoformat()}，{daypart}。没有新的外部事件，这是一个自由醒来窗口。",
                now,
                {"local_time": local.isoformat(), "daypart": daypart},
            )
        )

    def settle_seed(self, selected: SelectedSeed, result: WakeResult) -> None:
        if selected.event_id is None:
            return
        consumed = result.outcome in {"silent", "trace", "message"}
        self.store.settle_world_event(
            selected.event_id,
            selected.claim_token,
            consumed=consumed,
        )

    def release_seed(self, selected: SelectedSeed) -> None:
        if selected.event_id is not None:
            self.store.settle_world_event(
                selected.event_id,
                selected.claim_token,
                consumed=False,
            )


def build_lifeworld_tools(store: SQLiteStore) -> ToolRegistry:
    registry = ToolRegistry()

    registry.register(
        RegisteredTool(
            name="thread_list",
            description="查看仍在生长的线头。线头不是待办，不要为了调用工具而巡检。",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            handler=lambda _: {"threads": store.list_life_threads()},
            evidence_builder=lambda _args, result: f"看见 {len(result.get('threads', []))} 根现有线头",
        )
    )
    registry.register(
        RegisteredTool(
            name="thread_open",
            description="留下一个以后确实想继续的具体念头；能当场完成的事情不要创建线头。",
            parameters={
                "type": "object",
                "required": ["title", "origin"],
                "properties": {
                    "title": {"type": "string", "maxLength": 100},
                    "origin": {"type": "string", "maxLength": 1000},
                    "next_pull": {"type": "string", "maxLength": 300},
                    "revisit_after_minutes": {"type": "integer", "minimum": 30, "maximum": 10080},
                },
                "additionalProperties": False,
            },
            handler=lambda args: store.create_life_thread(
                str(args.get("title", "")),
                str(args.get("origin", "")),
                next_pull=str(args.get("next_pull", "")),
                revisit_after_minutes=_optional_int(args.get("revisit_after_minutes")),
            ),
            evidence_builder=_thread_evidence("新建"),
        )
    )
    registry.register(
        RegisteredTool(
            name="thread_continue",
            description="在线头上留下真实的新进展，也可以安排它以后重新浮现。",
            parameters={
                "type": "object",
                "required": ["thread_id", "note"],
                "properties": {
                    "thread_id": {"type": "integer"},
                    "note": {"type": "string", "maxLength": 1000},
                    "next_pull": {"type": "string", "maxLength": 300},
                    "revisit_after_minutes": {"type": "integer", "minimum": 30, "maximum": 10080},
                },
                "additionalProperties": False,
            },
            handler=lambda args: store.continue_life_thread(
                int(args.get("thread_id", 0)),
                str(args.get("note", "")),
                next_pull=str(args.get("next_pull", "")),
                revisit_after_minutes=_optional_int(args.get("revisit_after_minutes")),
            ),
            evidence_builder=_thread_evidence("继续"),
        )
    )
    registry.register(
        RegisteredTool(
            name="thread_close",
            description="当一根线已经完成或自然放下时结束它。",
            parameters={
                "type": "object",
                "required": ["thread_id"],
                "properties": {
                    "thread_id": {"type": "integer"},
                    "reason": {"type": "string", "maxLength": 1000},
                },
                "additionalProperties": False,
            },
            handler=lambda args: store.close_life_thread(
                int(args.get("thread_id", 0)), str(args.get("reason", ""))
            ),
            evidence_builder=_thread_evidence("结束"),
        )
    )
    registry.register(
        RegisteredTool(
            name="artifact_list",
            description="查看近期保存的小作品标题；没有具体缘由时不要反复巡视。",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            handler=lambda _: {"artifacts": store.list_life_artifacts()},
            evidence_builder=lambda _args, result: f"看见 {len(result.get('artifacts', []))} 件近期作品",
        )
    )
    registry.register(
        RegisteredTool(
            name="artifact_create",
            description="把这次真正完成的一小段文字或 Markdown 保存为作品。",
            parameters={
                "type": "object",
                "required": ["title", "content"],
                "properties": {
                    "title": {"type": "string", "maxLength": 120},
                    "content": {"type": "string", "maxLength": 12000},
                    "media_type": {
                        "type": "string",
                        "enum": ["text/plain", "text/markdown"],
                    },
                },
                "additionalProperties": False,
            },
            handler=lambda args: store.create_life_artifact(
                str(args.get("title", "")),
                str(args.get("content", "")),
                media_type=str(args.get("media_type") or "text/markdown"),
            ),
            evidence_builder=lambda _args, result: (
                f"保存作品《{result.get('title', '未命名')}》"
                if result.get("ok")
                else f"保存作品失败：{result.get('error', '未知错误')}"
            ),
        )
    )
    return registry


def _thread_evidence(action: str):
    def build(_args: dict[str, Any], result: Any) -> str:
        if isinstance(result, dict) and result.get("ok"):
            return f"{action}线头《{result.get('title', '未命名')}》"
        if isinstance(result, dict):
            return f"{action}线头失败：{result.get('error', '未知错误')}"
        return f"{action}线头"

    return build


def _optional_int(value: Any) -> int | None:
    if value in {None, ""}:
        return None
    return int(value)


def _daypart(hour: int) -> str:
    if 5 <= hour < 9:
        return "清晨"
    if 9 <= hour < 12:
        return "上午"
    if 12 <= hour < 14:
        return "中午"
    if 14 <= hour < 18:
        return "下午"
    if 18 <= hour < 23:
        return "晚上"
    return "深夜"
