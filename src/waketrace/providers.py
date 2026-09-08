from __future__ import annotations

import json
from typing import Any, Protocol

import httpx

from .config import Settings
from .models import ProviderTurn, ToolCall


class ProviderError(RuntimeError):
    pass


class LanguageProvider(Protocol):
    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ProviderTurn: ...


class OpenAICompatibleProvider:
    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.settings = settings
        self.client = client or httpx.Client(timeout=60)

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ProviderTurn:
        if not self.settings.api_key:
            raise ProviderError("WAKETRACE_API_KEY is not configured")
        body: dict[str, Any] = {
            "model": self.settings.model,
            "messages": messages,
            "temperature": self.settings.temperature,
            "max_tokens": self.settings.max_tokens,
        }
        if tools:
            body["tools"] = tools
        response = self.client.post(
            self.settings.api_base_url,
            headers={
                "Authorization": f"Bearer {self.settings.api_key}",
                "Content-Type": "application/json",
            },
            json=body,
        )
        if not 200 <= response.status_code < 300:
            raise ProviderError(f"provider returned HTTP {response.status_code}")
        try:
            payload = response.json()
            choice = payload["choices"][0]
            message = choice["message"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError("provider returned an invalid response") from exc

        raw_calls = message.get("tool_calls") or []
        calls: list[ToolCall] = []
        for item in raw_calls:
            try:
                arguments = json.loads(item["function"].get("arguments") or "{}")
                calls.append(
                    ToolCall(
                        id=str(item["id"]),
                        name=str(item["function"]["name"]),
                        arguments=arguments,
                    )
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ProviderError("provider returned an invalid tool call") from exc

        finish_reason = str(choice.get("finish_reason") or "")
        if calls and finish_reason != "tool_calls":
            raise ProviderError("incomplete tool-call response")
        content = message.get("content") or ""
        if not calls and (finish_reason != "stop" or not str(content).strip()):
            raise ProviderError("missing final response")
        return ProviderTurn(str(content), tuple(calls), finish_reason)

