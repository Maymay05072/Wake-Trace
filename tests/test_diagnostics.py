import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from waketrace.api import create_app
from waketrace.config import Settings
from waketrace.diagnostics import safe_error_code
from waketrace.engine import WakeEngine
from waketrace.external_mcp import ExternalMCPRegistry, RemoteConfig, RemoteServer
from waketrace.models import WakeSeed
from waketrace.notifiers import WebPushNotifier
from waketrace.providers import OpenAICompatibleProvider
from waketrace.storage import SQLiteStore
from waketrace.tools import ToolRegistry


def diagnostic_engine(tmp_path):
    settings = Settings(
        db_path=tmp_path / "wake.db", api_key="SECRET_MODEL_KEY",
        api_base_url="https://SECRET_ENDPOINT.example.com/v1/chat/completions",
        model="test-model", admin_token="SECRET_ADMIN_TOKEN", web_token="web-token",
        mcp_token="SECRET_MCP_TOKEN", vapid_private_key="SECRET_PUSH_KEY",
    )
    store = SQLiteStore(settings.db_path)
    provider = SimpleNamespace(complete=lambda *_: pytest.fail("must not call model"))
    engine = WakeEngine(settings, store, provider, ToolRegistry(), WebPushNotifier(settings, store))
    return settings, store, engine


def test_web_diagnostics_include_failures_without_private_fields(tmp_path):
    settings, store, engine = diagnostic_engine(tmp_path)
    now = datetime(2026, 10, 18, 2, tzinfo=UTC)
    first = store.start_cycle("SECRET_KIND", "SECRET_SEED", now)
    store.finish_cycle(first, status="completed", outcome="silent", now=now)
    second = store.start_cycle("test", "SECRET_CHAT", now + timedelta(minutes=30))
    store.finish_cycle(second, status="failed", error_code="provider_request_timeout", now=now)
    third = store.start_cycle("test", "SECRET_PROMPT", now + timedelta(minutes=60))
    store.finish_cycle(third, status="failed", error_code="SECRET_ERROR_BODY", now=now)
    next_at = now + timedelta(hours=2)
    store.set_state("next_wake_at", next_at.isoformat())
    client = TestClient(create_app(settings, engine))
    assert client.get("/world/diagnostics").status_code == 401
    assert client.get("/world/diagnostics", headers={"Authorization": "Bearer SECRET_MCP_TOKEN"}).status_code == 401
    response = client.get("/world/diagnostics", headers={"Authorization": "Bearer web-token"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    data = response.json()
    assert data["last_success_at"] == now.isoformat()
    assert data["next_wake_at"] == next_at.isoformat()
    assert [row["status"] for row in data["cycles"]] == ["failed", "failed", "completed"]
    assert data["cycles"][0]["error_code"] == "other_error"
    assert data["cycles"][1]["error_code"] == "provider_request_timeout"
    assert data["model"]["configuration_complete"]
    assert "SECRET" not in response.text
    # The existing admin status endpoint stays admin-only.
    assert client.get("/status", headers={"Authorization": "Bearer web-token"}).status_code == 401


def test_diagnostics_neither_discover_nor_execute_remote_tools(tmp_path, monkeypatch):
    import waketrace.external_mcp as module

    settings, _store, engine = diagnostic_engine(tmp_path)
    engine.tools = ExternalMCPRegistry(ToolRegistry(), RemoteConfig(servers={
        "memory": RemoteServer(
            transport="sse", url="https://SECRET_REMOTE.example.com/sse",
            token_env="SECRET_ENV_NAME", allowed_tools=["SECRET_TOOL_NAME"],
        ),
    }))
    monkeypatch.setattr(module, "_run_request", lambda *_: pytest.fail("must not connect"))
    client = TestClient(create_app(settings, engine))
    response = client.get("/world/diagnostics", headers={"Authorization": "Bearer web-token"})
    assert response.json()["external_mcp"][0]["state"] == "pending"
    assert "SECRET" not in response.text


def test_api_reports_live_scheduler_and_empty_records(tmp_path):
    settings, _store, engine = diagnostic_engine(tmp_path)
    with TestClient(create_app(settings, engine, run_scheduler=True)) as client:
        response = client.get("/world/diagnostics", headers={"Authorization": "Bearer web-token"})
        data = response.json()
        assert data["scheduler"]["running_in_this_process"]
        assert data["last_success_at"] is None and data["cycles"] == []


@pytest.mark.parametrize("error_class, code", [
    (httpx.ReadTimeout, "provider_request_timeout"),
    (httpx.ConnectError, "provider_connection_error"),
])
def test_provider_network_failure_is_saved_as_failure(tmp_path, error_class, code):
    settings, store, engine = diagnostic_engine(tmp_path)

    def fail(request):
        raise error_class("SECRET_NETWORK_DETAILS", request=request)

    engine.provider = OpenAICompatibleProvider(settings, httpx.Client(transport=httpx.MockTransport(fail)))
    result = engine.run(WakeSeed("test", "SECRET_SEED"), force=True)
    assert result.outcome == "error"
    assert store.diagnostic_cycles()[0]["status"] == "failed"
    assert store.diagnostic_cycles()[0]["error_code"] == code
    assert "SECRET_NETWORK_DETAILS" not in json.dumps(store.diagnostic_cycles())


def test_error_codes_are_allowlisted():
    assert safe_error_code("provider returned HTTP 429") == "provider returned HTTP 429"
    assert safe_error_code("https://secret-host/api?key=secret") == "other_error"


def test_http_200_with_invalid_message_is_saved_as_failure(tmp_path):
    settings, store, engine = diagnostic_engine(tmp_path)
    engine.provider = OpenAICompatibleProvider(settings, httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json={"choices": [{"message": None}]})
    )))
    assert engine.run(WakeSeed("test", "test"), force=True).outcome == "error"
    assert store.diagnostic_cycles()[0]["error_code"] == "provider returned an invalid response"
