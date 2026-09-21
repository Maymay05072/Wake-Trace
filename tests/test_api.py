from datetime import UTC, datetime

from fastapi.testclient import TestClient

from waketrace.api import create_app
from waketrace.config import Settings
from waketrace.engine import WakeEngine
from waketrace.storage import SQLiteStore
from waketrace.tools import ToolRegistry


class UnusedProvider:
    def complete(self, messages, tools):
        raise AssertionError("provider should not be called")


class UnusedNotifier:
    def send(self, title, body, *, message_id):
        raise AssertionError("notifier should not be called")


def test_status_is_fail_closed_and_health_is_public(tmp_path):
    settings = Settings(
        db_path=tmp_path / "wake.db",
        admin_token="a-long-test-token",
    )
    engine = WakeEngine(
        settings,
        SQLiteStore(settings.db_path),
        UnusedProvider(),
        ToolRegistry(),
        UnusedNotifier(),
    )
    client = TestClient(create_app(settings, engine))

    assert client.get("/health").status_code == 200
    assert client.get("/status").status_code == 401
    response = client.get(
        "/status", headers={"Authorization": "Bearer a-long-test-token"}
    )
    assert response.status_code == 200


def test_world_endpoints_are_authenticated(tmp_path):
    settings = Settings(
        db_path=tmp_path / "wake.db",
        admin_token="a-long-test-token",
    )
    store = SQLiteStore(settings.db_path)
    engine = WakeEngine(
        settings,
        store,
        UnusedProvider(),
        ToolRegistry(),
        UnusedNotifier(),
    )
    client = TestClient(create_app(settings, engine))
    payload = {
        "kind": "weather",
        "summary": "窗外开始下雨。",
        "evidence": {"source": "local sensor"},
    }

    assert client.post("/world/events", json=payload).status_code == 401
    response = client.post(
        "/world/events",
        json=payload,
        headers={"Authorization": "Bearer a-long-test-token"},
    )
    assert response.status_code == 200
    assert response.json()["event_id"] > 0

    response = client.get(
        "/world/threads",
        headers={"Authorization": "Bearer a-long-test-token"},
    )
    assert response.json() == {"threads": []}


def test_timeline_detail_returns_safe_wake_context(tmp_path):
    settings = Settings(
        db_path=tmp_path / "wake.db",
        admin_token="a-long-test-token",
    )
    store = SQLiteStore(settings.db_path)
    engine = WakeEngine(
        settings,
        store,
        UnusedProvider(),
        ToolRegistry(),
        UnusedNotifier(),
    )
    client = TestClient(create_app(settings, engine))
    now = datetime(2026, 9, 20, 1, 30, tzinfo=UTC)
    cycle_id = store.start_cycle("weather", "窗外开始下雨。", now)
    store.record_tool_event(
        cycle_id,
        "call-1",
        "read_weather",
        True,
        "读到一场小雨。",
        {"private_raw_result": "must not be returned"},
        now,
    )
    store.add_trace(
        cycle_id,
        outcome="trace",
        fact="听了一会儿雨。",
        content="雨落得很轻，我停下来听了一会儿。",
        share="",
        notified=False,
        fact_source="self_report",
        evidence=[{"tool_name": "read_weather", "ok": True}],
        now=now,
    )
    store.finish_cycle(cycle_id, status="completed", outcome="trace", now=now)
    trace_id = store.recent_timeline(1)[0]["id"]

    assert client.get(f"/world/timeline/{trace_id}").status_code == 401

    response = client.get(
        f"/world/timeline/{trace_id}",
        headers={"Authorization": "Bearer a-long-test-token"},
    )
    assert response.status_code == 200
    entry = response.json()["entry"]
    assert entry["seed_summary"] == "窗外开始下雨。"
    assert entry["content"] == "雨落得很轻，我停下来听了一会儿。"
    assert entry["outcome"] == "trace"
    assert entry["tool_events"] == [
        {
            "tool_name": "read_weather",
            "ok": 1,
            "summary": "读到一场小雨。",
            "created_at": now.isoformat(),
        }
    ]
    assert "result_json" not in entry["tool_events"][0]

    missing = client.get(
        "/world/timeline/9999",
        headers={"Authorization": "Bearer a-long-test-token"},
    )
    assert missing.status_code == 404


def test_configured_web_origin_receives_cors_headers(tmp_path):
    settings = Settings(
        db_path=tmp_path / "wake.db",
        admin_token="a-long-test-token",
        web_origins="https://trace.example.com",
    )
    engine = WakeEngine(
        settings,
        SQLiteStore(settings.db_path),
        UnusedProvider(),
        ToolRegistry(),
        UnusedNotifier(),
    )
    client = TestClient(create_app(settings, engine))

    response = client.options(
        "/world/timeline",
        headers={
            "Origin": "https://trace.example.com",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://trace.example.com"


def test_web_token_is_read_only(tmp_path):
    settings = Settings(
        db_path=tmp_path / "wake.db",
        admin_token="a-long-test-token",
        web_token="a-different-read-only-token",
    )
    engine = WakeEngine(
        settings,
        SQLiteStore(settings.db_path),
        UnusedProvider(),
        ToolRegistry(),
        UnusedNotifier(),
    )
    client = TestClient(create_app(settings, engine))
    web_headers = {"Authorization": "Bearer a-different-read-only-token"}

    assert client.get("/world/timeline", headers=web_headers).status_code == 200
    assert client.get("/world/threads", headers=web_headers).status_code == 200
    assert client.get("/world/artifacts", headers=web_headers).status_code == 200
    assert client.get("/status", headers=web_headers).status_code == 401
    assert client.post(
        "/world/events",
        headers=web_headers,
        json={"kind": "manual", "summary": "不应被写入。"},
    ).status_code == 401

    admin_headers = {"Authorization": "Bearer a-long-test-token"}
    assert client.get("/world/timeline", headers=admin_headers).status_code == 200
