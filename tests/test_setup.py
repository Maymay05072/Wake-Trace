import json
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from waketrace.api import create_app
from waketrace.config import Settings
from waketrace.engine import WakeEngine
from waketrace.providers import ProviderError
from waketrace.setup import probe_model
from waketrace.storage import SQLiteStore
from waketrace.tools import ToolRegistry


def setup_app(tmp_path):
    settings = Settings(
        db_path=tmp_path / "test.db", admin_token="admin-test", web_token="web-test",
        mcp_token="mcp-test", api_key="SECRET_MODEL_KEY", model="test-model",
        api_base_url="https://SECRET_ENDPOINT.test/v1/chat/completions",
        companion_name="小机", user_name="用户", timezone="Asia/Shanghai",
    )
    notifier = SimpleNamespace(send=lambda *a, **kw: pytest.fail("must not send"))
    engine = WakeEngine(settings, SQLiteStore(settings.db_path), None, ToolRegistry(), notifier)
    client = TestClient(create_app(settings, engine))
    return settings, engine, client


def test_checklist_is_read_only_and_does_not_expose_credentials(tmp_path, monkeypatch):
    import waketrace.setup as module

    _, engine, client = setup_app(tmp_path)
    monkeypatch.setattr(module, "probe_model", lambda *_: pytest.fail("must not call model"))
    engine.store.start_cycle("SECRET_SEED", "SECRET_CHAT", datetime.now(UTC))
    assert client.get("/world/setup").status_code == 401
    assert client.get("/world/setup", headers={"Authorization": "Bearer mcp-test"}).status_code == 401
    response = client.get("/world/setup", headers={"Authorization": "Bearer web-test"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    data = response.json()
    assert data["model"]["configuration_complete"]
    assert data["timezone"] == "Asia/Shanghai"
    assert data["identity"]["companion_name"] == "小机"
    assert "SECRET" not in response.text


@pytest.mark.parametrize("target", ["model", "notification"])
def test_probes_require_admin_and_are_rate_limited_across_apps(tmp_path, monkeypatch, target):
    import waketrace.setup as module

    settings, engine, client = setup_app(tmp_path)
    calls = []
    monkeypatch.setattr(module, "probe_model", lambda *_: calls.append("model"))
    engine.notifier.send = lambda *a, **kw: calls.append((a, kw)) or True
    url = f"/admin/tests/{target}"
    for token in (None, "web-test", "mcp-test"):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        assert client.post(url, headers=headers).status_code == 401
    headers = {"Authorization": "Bearer admin-test"}
    response = client.post(url, headers=headers)
    assert response.json()["ok"] is True
    assert response.headers["cache-control"] == "no-store"
    another = TestClient(create_app(settings, engine))
    assert another.post(url, headers=headers).status_code == 429
    assert len(calls) == 1
    if target == "notification":
        assert "通知测试" in calls[0][0][0]
        assert calls[0][1]["message_id"].startswith("waketrace-test-")
    assert engine.store.diagnostic_cycles() == []
    assert engine.store.recent_timeline() == []
    assert engine.store.get_state("next_wake_at") is None
    assert engine.store.get_state("last_share") is None
    assert engine.store.get_state("wake_counters") is None


@pytest.mark.parametrize("exception,code", [
    (ProviderError("provider returned HTTP 401"), "provider returned HTTP 401"),
    (ProviderError("SECRET_RAW_ERROR"), "other_error"),
    (RuntimeError("SECRET_RAW_ERROR"), "other_error"),
])
def test_probe_errors_are_sanitized(tmp_path, monkeypatch, exception, code):
    import waketrace.setup as module

    _, _, client = setup_app(tmp_path)

    def fail(_):
        raise exception

    monkeypatch.setattr(module, "probe_model", fail)
    response = client.post("/admin/tests/model", headers={"Authorization": "Bearer admin-test"})
    assert response.json() == {"ok": False, "code": code}
    assert "SECRET" not in response.text


def test_model_probe_has_fixed_short_input_and_no_tools(tmp_path, monkeypatch):
    import waketrace.setup as module

    settings, _, _ = setup_app(tmp_path)
    captured = []

    def handle(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{
            "message": {"content": "SECRET_MODEL_OUTPUT"}, "finish_reason": "stop",
        }]})

    original_client = httpx.Client
    monkeypatch.setattr(module.httpx, "Client", lambda **kw: original_client(
        transport=httpx.MockTransport(handle), **kw,
    ))
    assert probe_model(settings) is None
    assert captured[0]["max_tokens"] == 128
    assert "tools" not in captured[0]
    assert len(captured[0]["messages"]) == 1
    assert settings.max_tokens == 1200


def test_failed_notification_test_does_not_claim_delivery(tmp_path):
    _, engine, client = setup_app(tmp_path)
    engine.notifier.send = lambda *a, **kw: False
    response = client.post("/admin/tests/notification", headers={"Authorization": "Bearer admin-test"})
    assert response.json() == {"ok": False, "code": "notification_not_delivered"}


def test_missing_model_configuration_never_calls_provider(tmp_path):
    _, engine, client = setup_app(tmp_path)
    engine.settings.api_key = ""
    response = client.post("/admin/tests/model", headers={"Authorization": "Bearer admin-test"})
    assert response.json() == {"ok": False, "code": "configuration_incomplete"}
