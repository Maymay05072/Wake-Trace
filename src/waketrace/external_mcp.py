"""Opt-in remote MCP tools for the synchronous wake engine.

Each operation owns its transport/session in one async task. This avoids sharing
an MCP session across the API thread pool and autonomous scheduler thread.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

import anyio
import httpx
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .config import Settings
from .tools import RegisteredTool, ToolRegistry

logger = logging.getLogger(__name__)


class RemoteServer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transport: Literal["sse", "streamable_http"]
    url: str
    token_env: str | None = None
    headers_env: dict[str, str] = Field(default_factory=dict)
    allowed_tools: list[str] = Field(min_length=1, max_length=64)
    timeout_seconds: float = Field(default=20, ge=0.1, le=120)
    max_result_chars: int = Field(default=4000, ge=256, le=16000)

    @field_validator("url")
    @classmethod
    def remote_url(cls, value: str) -> str:
        parts = urlsplit(value)
        if (
            parts.scheme not in {"http", "https"} or not parts.hostname
            or parts.username is not None or parts.password is not None
            or parts.query or parts.fragment
        ):
            raise ValueError("use an HTTP(S) URL without credentials, query, or fragment")
        return value

    @field_validator("token_env")
    @classmethod
    def token_name(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
            raise ValueError("token_env must name an environment variable")
        return value

    @field_validator("headers_env")
    @classmethod
    def header_names(cls, value: dict[str, str]) -> dict[str, str]:
        for header, variable in value.items():
            if not re.fullmatch(r"[A-Za-z0-9-]+", header):
                raise ValueError("invalid header name")
            if header.lower() in {"host", "content-length", "connection"}:
                raise ValueError("transport headers cannot be overridden")
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", variable):
                raise ValueError("headers_env values must name environment variables")
        return value


class RemoteConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    servers: dict[str, RemoteServer] = Field(default_factory=dict, max_length=16)

    @field_validator("servers")
    @classmethod
    def server_names(cls, value: dict[str, RemoteServer]) -> dict[str, RemoteServer]:
        if any(not re.fullmatch(r"[A-Za-z0-9_-]{1,24}", name) for name in value):
            raise ValueError("server names must be 1-24 ASCII letters, digits, underscores or hyphens")
        return value


def _load_config(path: Path) -> RemoteConfig:
    try:
        if path.stat().st_size > 128_000:
            raise ValueError("configuration too large")
        return RemoteConfig.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # Pydantic's detailed error can contain credentials supplied by mistake.
        raise ValueError("invalid external MCP configuration; check the file and documented format") from None


def tool_alias(server: str, remote_name: str) -> str:
    readable = re.sub(r"[^A-Za-z0-9_-]", "_", remote_name)[:24]
    digest = hashlib.sha256(f"{server}\0{remote_name}".encode()).hexdigest()[:10]
    return f"mcp_{server}_{readable}_{digest}"


def _headers(server: RemoteServer) -> dict[str, str]:
    result = {}
    for name, variable in server.headers_env.items():
        value = os.environ.get(variable, "").strip()
        if not value or "\r" in value or "\n" in value:
            raise ValueError("missing or invalid MCP credential")
        result[name] = value
    if server.token_env:
        value = os.environ.get(server.token_env, "").strip()
        if not value or "\r" in value or "\n" in value:
            raise ValueError("missing or invalid MCP credential")
        result["Authorization"] = f"Bearer {value}"
    return result


async def _request(server: RemoteServer, tool: str | None, arguments: dict[str, Any]):
    transport = sse_client if server.transport == "sse" else streamablehttp_client
    with anyio.fail_after(server.timeout_seconds):
        async with transport(
            server.url, headers=_headers(server), timeout=server.timeout_seconds,
            sse_read_timeout=server.timeout_seconds,
        ) as streams, ClientSession(streams[0], streams[1]) as session:
            await session.initialize()
            if tool is not None:
                return await session.call_tool(tool, arguments)
            found = {}
            cursor = None
            seen_cursors = set()
            for _ in range(10):
                page = await session.list_tools(cursor=cursor)
                for item in page.tools:
                    if item.name in server.allowed_tools:
                        found[item.name] = item
                cursor = page.nextCursor
                if not cursor or set(found) == set(server.allowed_tools):
                    return list(found.values())
                if cursor in seen_cursors:
                    raise ValueError("repeated MCP tools cursor")
                seen_cursors.add(cursor)
            raise ValueError("MCP tools pagination limit")


def _run_request(server: RemoteServer, tool: str | None = None, arguments=None):
    # Also works when construction happens inside a host's running event loop.
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="waketrace-mcp") as worker:
        return worker.submit(
            lambda: asyncio.run(_request(server, tool, arguments or {}))
        ).result()


def _bounded_result(result: Any, limit: int) -> dict[str, Any]:
    # Binary blobs are never passed into the text-only wake provider or database.
    content = []
    for item in result.content:
        if item.type == "text":
            content.append({"type": "text", "text": item.text})
        else:
            content.append({"type": "omitted", "original_type": item.type})
    payload = {"content": content}
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        payload["structuredContent"] = structured
    if result.isError:
        payload["error"] = "external_mcp_tool_error"
    encoded = json.dumps(payload, ensure_ascii=False, default=str)
    if len(encoded) > limit:
        # Keep the complete envelope within the limit, even with escaped strings.
        bounded = {"truncated": True, "text": ""}
        if result.isError:
            bounded["error"] = "external_mcp_tool_error"
        low, high = 0, len(encoded)
        while low < high:
            middle = (low + high + 1) // 2
            bounded["text"] = encoded[:middle]
            if len(json.dumps(bounded, ensure_ascii=False)) <= limit:
                low = middle
            else:
                high = middle - 1
        bounded["text"] = encoded[:low]
        return bounded
    return payload


def _failure_code(error: BaseException) -> str:
    if isinstance(error, BaseExceptionGroup):
        codes = [_failure_code(item) for item in error.exceptions]
        return next((code for code in codes if code != "transport_error"), "transport_error")
    if isinstance(error, (TimeoutError, httpx.TimeoutException)):
        return "timeout"
    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
        return "authentication_failed" if status in {401, 403} else f"http_{status}"
    if isinstance(error, httpx.TransportError):
        return "connection_error"
    if isinstance(error, ValueError):
        return "configuration_or_discovery_error"
    return "transport_error"


class ExternalMCPRegistry(ToolRegistry):
    def __init__(self, builtin: ToolRegistry, config: RemoteConfig):
        super().__init__()
        self.builtin = builtin
        self.config = config
        self._discovered: set[str] = set()
        self._retry_after: dict[str, float] = {}
        self._lock = threading.RLock()
        self._diagnostic_status: dict[str, dict[str, Any]] = {}

    def diagnostics(self) -> list[dict[str, Any]]:
        # Read snapshots without waiting for a network discovery holding _lock.
        return [
            {
                "name": name, "transport": server.transport,
                "allowed_count": len(server.allowed_tools),
                "state": "pending", "tool_count": 0, "missing_count": 0,
                **self._diagnostic_status.get(name, {}),
            }
            for name, server in self.config.servers.items()
        ]

    def specifications(self) -> list[dict[str, Any]]:
        with self._lock:
            for name, server in self.config.servers.items():
                if name in self._discovered or time.monotonic() < self._retry_after.get(name, 0):
                    continue
                try:
                    available = _run_request(server)
                    for tool in available:
                        self.register(RegisteredTool(
                            name=tool_alias(name, tool.name),
                            description=(
                                f"External MCP tool from {name}. "
                                + (tool.description or "")[:1000]
                            ),
                            parameters=tool.inputSchema,
                            handler=self._handler(name, server, tool.name),
                            evidence_builder=lambda _args, output: (
                                "external MCP tool failed" if output.get("error")
                                else "external MCP tool completed"
                            ),
                        ))
                    missing = set(server.allowed_tools) - {item.name for item in available}
                    if missing:
                        logger.warning(
                            "external MCP tools missing server=%s count=%s", name, len(missing)
                        )
                    self._discovered.add(name)
                    self._diagnostic_status[name] = {
                        "state": "partial" if missing else "ready",
                        "tool_count": len(available), "missing_count": len(missing),
                        "checked_at": datetime.now(UTC).isoformat(), "error_code": None,
                    }
                    logger.info("external MCP ready server=%s tools=%s", name, len(available))
                except Exception as exc:  # noqa: BLE001 - isolate third-party transport failures
                    self._retry_after[name] = time.monotonic() + 60
                    self._diagnostic_status[name] = {
                        "state": "unavailable", "tool_count": 0,
                        "checked_at": datetime.now(UTC).isoformat(),
                        "error_code": _failure_code(exc),
                    }
                    logger.warning(
                        "external MCP discovery failed server=%s error_code=%s "
                        "error_type=%s retry_seconds=60",
                        name, _failure_code(exc), type(exc).__name__,
                    )
            return self.builtin.specifications() + super().specifications()

    def execute(self, name: str, arguments: dict[str, Any]) -> tuple[bool, Any, str]:
        with self._lock:
            external = name in self._tools
        if external:
            return super().execute(name, arguments)
        return self.builtin.execute(name, arguments)

    def _handler(self, name: str, server: RemoteServer, remote_name: str):
        def call(arguments: dict[str, Any]) -> dict[str, Any]:
            try:
                result = _run_request(server, remote_name, arguments)
                previous = self._diagnostic_status.get(name, {})
                self._diagnostic_status[name] = {
                    **previous, "state": "partial" if previous.get("missing_count") else "ready",
                    "checked_at": datetime.now(UTC).isoformat(), "error_code": None,
                }
                return _bounded_result(result, server.max_result_chars)
            except Exception as exc:  # noqa: BLE001 - external MCP errors vary by transport
                self._diagnostic_status[name] = {
                    **self._diagnostic_status.get(name, {}), "state": "unavailable",
                    "checked_at": datetime.now(UTC).isoformat(), "error_code": _failure_code(exc),
                }
                logger.warning(
                    "external MCP call failed server=%s error_code=%s error_type=%s",
                    name, _failure_code(exc), type(exc).__name__,
                )
                return {
                    "error": "external_mcp_unavailable", "error_code": _failure_code(exc),
                    "error_type": type(exc).__name__,
                }
        return call


def with_external_mcp(builtin: ToolRegistry, settings: Settings) -> ToolRegistry:
    if settings.external_mcp_config is None:
        return builtin
    return ExternalMCPRegistry(builtin, _load_config(settings.external_mcp_config))
