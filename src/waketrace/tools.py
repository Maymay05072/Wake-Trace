from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

ToolHandler = Callable[[dict[str, Any]], Any]
EvidenceBuilder = Callable[[dict[str, Any], Any], str]


def _default_evidence(arguments: dict[str, Any], result: Any) -> str:
    del arguments
    if isinstance(result, dict):
        if result.get("error"):
            return f"tool failed: {result['error']}"
        for key in ("summary", "message", "title", "status"):
            if result.get(key):
                return str(result[key])[:400]
    return json.dumps(result, ensure_ascii=False, default=str)[:400]


@dataclass(frozen=True, slots=True)
class RegisteredTool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler
    evidence_builder: EvidenceBuilder = _default_evidence

    def specification(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register(self, tool: RegisteredTool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def specifications(self) -> list[dict[str, Any]]:
        return [tool.specification() for tool in self._tools.values()]

    def execute(self, name: str, arguments: dict[str, Any]) -> tuple[bool, Any, str]:
        tool = self._tools.get(name)
        if not tool:
            result = {"error": f"unknown tool: {name}"}
            return False, result, result["error"]
        try:
            result = tool.handler(arguments)
            ok = not (isinstance(result, dict) and result.get("error"))
            return ok, result, tool.evidence_builder(arguments, result)
        except Exception as exc:  # noqa: BLE001 - 外部工具适配器可能抛出任意异常
            result = {"error": type(exc).__name__}
            return False, result, f"{name} failed with {type(exc).__name__}"
