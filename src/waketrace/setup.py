"""Configuration checks and explicit administrator-only connection probes."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from importlib.util import find_spec

import httpx
from fastapi import HTTPException

from .config import Settings
from .diagnostics import runtime_diagnostics, safe_error_code
from .engine import WakeEngine
from .providers import OpenAICompatibleProvider, ProviderError


def configuration_checklist(engine: WakeEngine) -> dict:
    data = runtime_diagnostics(engine, None, False)
    settings = engine.settings
    notifications = data["notifications"]
    if notifications["kind"] == "webpush":
        notifications["dependency_installed"] = find_spec("pywebpush") is not None
    return {
        "checked_at": data["checked_at"],
        "model": data["model"],
        "identity": {
            "companion_name": settings.companion_name,
            "user_name": settings.user_name,
            "using_default_names": (
                settings.companion_name == "Companion" or settings.user_name == "User"
            ),
        },
        "timezone": settings.timezone,
        "notifications": notifications,
        "external_mcp": data["external_mcp"],
        "admin_tests_available": bool(settings.admin_token),
    }


def probe_model(settings: Settings) -> None:
    # Fixed text only: no history, wake protocol, tools, or caller-supplied destination.
    probe_settings = settings.model_copy(update={"max_tokens": 128})
    with httpx.Client(timeout=20) as client:
        OpenAICompatibleProvider(probe_settings, client).complete(
            [{"role": "user", "content": "Connection test. Please reply with OK only."}], []
        )


def run_connection_test(engine: WakeEngine, target: str) -> dict:
    now = datetime.now(UTC)
    # Keep this short lease until expiry, including on failure: limits repeated costs
    # and duplicate test pushes across worker processes without touching wake state.
    if not engine.store.acquire_lease(
        f"connection_test:{target}", uuid.uuid4().hex,
        now=now, expires_at=now + timedelta(seconds=60),
    ):
        raise HTTPException(429, "test cooldown", headers={"Retry-After": "60"})
    if target == "model":
        if not configuration_checklist(engine)["model"]["configuration_complete"]:
            return {"ok": False, "code": "configuration_incomplete"}
        try:
            probe_model(engine.settings)
        except ProviderError as exc:
            return {"ok": False, "code": safe_error_code(str(exc))}
        except Exception:  # noqa: BLE001 - never expose raw third-party error bodies
            return {"ok": False, "code": "other_error"}
        return {"ok": True, "code": "response_received"}
    try:
        delivered = engine.notifier.send(
            "WakeTrace · 通知测试",
            "这是一条手动测试通知，不是小机的自主醒来消息。",
            message_id=f"waketrace-test-{uuid.uuid4().hex}",
        )
    except Exception:  # noqa: BLE001 - custom notifier errors may contain credentials
        return {"ok": False, "code": "notification_error"}
    return {
        "ok": bool(delivered),
        "code": "channel_accepted" if delivered else "notification_not_delivered",
    }
