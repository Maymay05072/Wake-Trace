from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

Outcome = Literal["silent", "trace", "message"]


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class WakeSeed:
    """一次醒来的有限缘由；内容应当简短并尽量保持事实性。"""

    kind: str
    summary: str
    occurred_at: datetime = field(default_factory=utc_now)
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ProviderTurn:
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    finish_reason: str = "stop"


@dataclass(frozen=True, slots=True)
class WakeDraft:
    outcome: Outcome
    fact: str = ""
    content: str = ""
    share: str = ""
    residue: str = ""
    next_min_minutes: int | None = None
    next_max_minutes: int | None = None
    next_reason: str = ""


@dataclass(frozen=True, slots=True)
class ToolEvidence:
    call_id: str
    tool_name: str
    ok: bool
    summary: str


@dataclass(frozen=True, slots=True)
class WakeResult:
    cycle_id: int
    outcome: str
    notified: bool
    next_wake_at: datetime
    fact: str = ""
    content: str = ""
    share: str = ""
    evidence: tuple[ToolEvidence, ...] = ()
