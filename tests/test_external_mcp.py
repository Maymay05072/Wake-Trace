import asyncio
import json
import socket
import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, ImageContent, TextContent, Tool
from starlette.responses import JSONResponse

from waketrace.config import Settings
from waketrace.engine import WakeEngine
from waketrace.external_mcp import (
    ExternalMCPRegistry,
    RemoteConfig,
    RemoteServer,
    _bounded_result,
    _headers,
    tool_alias,
    with_external_mcp,
)
from waketrace.models import ProviderTurn, ToolCall, WakeSeed
from waketrace.storage import SQLiteStore
from waketrace.tools import RegisteredTool, ToolRegistry


def server_config(**changes):
    return RemoteServer(**{
        "transport": "streamable_http", "url": "http://127.0.0.1:12345/mcp",
        "allowed_tools": ["echo"], **changes,
    })


def builtin():
    registry = ToolRegistry()
    registry.register(RegisteredTool(
        "local", "Local test tool", {"type": "object"}, lambda _: {"summary": "local ok"}
    ))
    return registry


def test_disabled_external_mcp_does_not_wrap_or_connect(tmp_path):
    registry = builtin()
    assert with_external_mcp(registry, Settings(db_path=tmp_path / "db")) is registry


@pytest.mark.parametrize("change", [
    {"transport": "stdio"}, {"allowed_tools": []},
    {"url": "https://host/mcp?token=SECRET"}, {"url": "https://name:SECRET@host/mcp"},
    {"url": "file:///etc/passwd"}, {"headers_env": {"Host": "SECRET"}},
])
def test_invalid_config_fails_without_echoing_secret(tmp_path, change):
    data = {"transport": "sse", "url": "https://host/sse", "allowed_tools": ["echo"], **change}
    path = tmp_path / "tools.json"
    path.write_text(json.dumps({"servers": {"test": data}}))
    with pytest.raises(ValueError) as error:
        with_external_mcp(builtin(), Settings(external_mcp_config=path))
    assert "SECRET" not in str(error.value)


def test_missing_file_fails_clearly(tmp_path):
    with pytest.raises(ValueError, match="invalid external MCP configuration"):
        with_external_mcp(builtin(), Settings(external_mcp_config=tmp_path / "absent"))


def test_credentials_use_environment_and_support_custom_headers(monkeypatch):
    monkeypatch.setenv("TEST_BEARER", "secret-value")
    monkeypatch.setenv("TEST_KEY", "key-value")
    config = server_config(token_env="TEST_BEARER", headers_env={"X-API-Key": "TEST_KEY"})
    assert _headers(config) == {"Authorization": "Bearer secret-value", "X-API-Key": "key-value"}
    monkeypatch.delenv("TEST_BEARER")
    with pytest.raises(ValueError, match="missing or invalid"):
        _headers(config)


def test_aliases_are_unique_valid_and_short():
    names = [tool_alias("memory", "a/b"), tool_alias("memory", "a_b"), tool_alias("other", "a/b")]
    assert len(set(names)) == 3
    assert len(tool_alias("s" * 24, "工具" * 100)) <= 64


def test_results_are_bounded_and_mcp_errors_remain_errors():
    result = CallToolResult(
        content=[TextContent(type="text", text='"\\' * 2000)], isError=True
    )
    bounded = _bounded_result(result, 256)
    assert bounded["error"] == "external_mcp_tool_error"
    assert bounded["truncated"]
    assert len(json.dumps(bounded, ensure_ascii=False)) <= 256
    binary = CallToolResult(content=[ImageContent(type="image", data="BINARY", mimeType="image/png")])
    assert "BINARY" not in json.dumps(_bounded_result(binary, 4000))


def test_failed_discovery_recovers_without_disabling_builtins(monkeypatch, caplog):
    import waketrace.external_mcp as module

    clock = [0]
    attempts = []
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])

    def request(*_args):
        attempts.append(True)
        if len(attempts) == 1:
            raise RuntimeError("SECRET URL and token must not appear in logs")
        return [Tool(name="echo", inputSchema={"type": "object"})]

    monkeypatch.setattr(module, "_run_request", request)
    registry = ExternalMCPRegistry(builtin(), RemoteConfig(servers={"memory": server_config()}))
    assert len(registry.specifications()) == 1
    assert registry.execute("local", {})[0]
    assert len(registry.specifications()) == 1
    assert len(attempts) == 1
    clock[0] = 61
    assert len(registry.specifications()) == 2
    assert len(attempts) == 2
    assert "SECRET" not in caplog.text


def test_failed_call_is_not_retried_or_reported_success(monkeypatch):
    import waketrace.external_mcp as module

    attempts = []

    def request(_server, tool=None, arguments=None):
        if tool is None:
            return [Tool(name="echo", inputSchema={"type": "object"})]
        attempts.append(True)
        raise RuntimeError("SECRET")

    monkeypatch.setattr(module, "_run_request", request)
    registry = ExternalMCPRegistry(builtin(), RemoteConfig(servers={"memory": server_config()}))
    registry.specifications()
    ok, result, _ = registry.execute(tool_alias("memory", "echo"), {})
    assert not ok and result["error"] == "external_mcp_unavailable"
    assert len(attempts) == 1
    assert "SECRET" not in json.dumps(result)


@contextmanager
def running_mcp(transport, expected_token=None):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    service = FastMCP("test-remote", stateless_http=True, log_level="ERROR")
    calls = []

    @service.tool()
    def echo(text: str) -> str:
        calls.append(text)
        return "echo:" + text

    @service.tool()
    def forbidden() -> str:
        return "should not be offered"

    @service.tool()
    async def slow() -> str:
        await asyncio.sleep(2)
        return "too late"

    @service.tool()
    def broken() -> str:
        raise ValueError("remote error")

    app = service.sse_app() if transport == "sse" else service.streamable_http_app()
    received_auth = []

    async def record_auth(scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope["headers"])
            value = headers.get(b"authorization")
            received_auth.append(value.decode() if value else None)
            if expected_token and value != f"Bearer {expected_token}".encode():
                await JSONResponse({"error": "unauthorized"}, status_code=401)(scope, receive, send)
                return
        await app(scope, receive, send)

    server = uvicorn.Server(uvicorn.Config(record_auth, log_level="error", lifespan="on"))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    try:
        while not server.started:
            if time.monotonic() >= deadline or not thread.is_alive():
                raise RuntimeError("test MCP server did not start")
            time.sleep(0.01)
        endpoint = "sse" if transport == "sse" else "mcp"
        yield f"http://127.0.0.1:{port}/{endpoint}", calls, received_auth
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()


@pytest.mark.parametrize("transport", ["sse", "streamable_http"])
def test_real_mcp_discovery_call_allowlist_and_wake_evidence(tmp_path, monkeypatch, transport):
    monkeypatch.setenv("REMOTE_TEST_TOKEN", "local-test-secret")
    with running_mcp(transport) as (url, calls, received_auth):
        config = RemoteConfig(servers={"memory": server_config(
            transport=transport, url=url, token_env="REMOTE_TEST_TOKEN"
        )})
        registry = ExternalMCPRegistry(builtin(), config)
        specs = registry.specifications()
        assert len(specs) == 2
        alias = tool_alias("memory", "echo")
        assert {item["function"]["name"] for item in specs} == {"local", alias}
        assert not registry.execute(tool_alias("memory", "forbidden"), {})[0]
        store = SQLiteStore(tmp_path / "wake.db")
        turns = iter([
            ProviderTurn("", (ToolCall("c1", alias, {"text": "hello"}),), "tool_calls"),
            ProviderTurn(json.dumps({"outcome": "trace", "content": "Kept a trace."}), (), "stop"),
        ])
        provider = SimpleNamespace(complete=lambda *_: next(turns))
        engine = WakeEngine(
            Settings(db_path=tmp_path / "wake.db"), store, provider, registry,
            SimpleNamespace(send=lambda *_args, **_kwargs: True),
        )
        result = engine.run(WakeSeed("test", "try echo"), force=True)
        assert result.evidence[0].ok
        assert result.evidence[0].tool_name == alias
        assert calls == ["hello"]
        assert received_auth and all(value == "Bearer local-test-secret" for value in received_auth)
        # A second call reopens a connection rather than reusing the old session.
        ok, output, _ = registry.execute(alias, {"text": "again"})
        assert ok and "echo:again" in json.dumps(output)


def test_real_tool_error_and_timeout():
    with running_mcp("streamable_http") as (url, _calls, _auth):
        server = server_config(url=url, allowed_tools=["broken", "slow"], timeout_seconds=1)
        registry = ExternalMCPRegistry(builtin(), RemoteConfig(servers={"test": server}))
        assert len(registry.specifications()) == 3
        ok, result, _ = registry.execute(tool_alias("test", "broken"), {})
        assert not ok and result["error"] == "external_mcp_tool_error"
        start = time.monotonic()
        ok, result, _ = registry.execute(tool_alias("test", "slow"), {})
        assert not ok and result["error"] == "external_mcp_unavailable"
        assert result["error_code"] == "timeout"
        assert time.monotonic() - start < 2


@pytest.mark.parametrize("transport", ["sse", "streamable_http"])
def test_auth_failure_keeps_builtin_tools_and_logs_safe_reason(transport, caplog):
    with running_mcp(transport, expected_token="secret") as (url, _calls, _auth):
        registry = ExternalMCPRegistry(
            builtin(), RemoteConfig(servers={"test": server_config(url=url, transport=transport)})
        )
        assert len(registry.specifications()) == 1
        assert registry.execute("local", {})[0]
        assert "authentication_failed" in caplog.text
        assert "Bearer secret" not in caplog.text


def test_cli_and_api_use_external_registry(tmp_path, monkeypatch):
    from waketrace import api
    from waketrace.cli import build_engine

    path = tmp_path / "tools.json"
    path.write_text('{"servers": {}}')
    settings = Settings(db_path=tmp_path / "db", external_mcp_config=path)
    assert isinstance(build_engine(settings).tools, ExternalMCPRegistry)
    wrapped = []

    def record(registry, config):
        result = with_external_mcp(registry, config)
        wrapped.append(result)
        return result

    monkeypatch.setattr(api, "with_external_mcp", record)
    api.create_app(settings)
    assert len(wrapped) == 1 and isinstance(wrapped[0], ExternalMCPRegistry)
