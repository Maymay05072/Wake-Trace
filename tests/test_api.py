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
