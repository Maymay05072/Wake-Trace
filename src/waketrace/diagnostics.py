"""Read-only, body-free diagnostics for the Web viewer."""
from __future__ import annotations

import re
from datetime import UTC, datetime
from urllib.parse import urlsplit

from .engine import WakeEngine
from .notifiers import ConsoleNotifier, WebPushNotifier

_KNOWN_ERRORS = {
    "WAKETRACE_API_KEY is not configured", "provider returned an invalid response",
    "provider returned an invalid tool call", "incomplete tool-call response",
    "missing final response", "final_response_is_not_json", "final_response_is_not_object",
    "invalid_outcome", "message_without_share", "silent_with_share", "invalid_next_wake",
    "invalid_min_minutes", "invalid_max_minutes", "tool_round_limit", "missing_final_response",
    "provider_request_timeout", "provider_connection_error", "external_wake_aborted",
}


def safe_error_code(value: str | None) -> str | None:
    if not value:
        return None
    if value in _KNOWN_ERRORS or re.fullmatch(r"provider returned HTTP [1-5][0-9]{2}", value):
        return value
    return "other_error"


def _timestamp(value) -> str | None:
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.astimezone(UTC).isoformat() if parsed.tzinfo else None
    except (TypeError, ValueError):
        return None


def runtime_diagnostics(engine: WakeEngine, scheduler, scheduler_running: bool) -> dict:
    settings, store = engine.settings, engine.store
    cycles = store.diagnostic_cycles()
    for cycle in cycles:
        cycle["error_code"] = safe_error_code(cycle["error_code"])
        # Custom hosts may store arbitrary outcomes; expose only the protocol states.
        if cycle["outcome"] not in {"silent", "trace", "message", None}:
            cycle["outcome"] = "unknown"
        if cycle["status"] not in {"running", "completed", "failed"}:
            cycle["status"] = "unknown"
    try:
        model_url = urlsplit(settings.api_base_url)
        endpoint_set = model_url.scheme in {"http", "https"} and bool(model_url.hostname)
        endpoint_set = endpoint_set and model_url.hostname != "api.example.com"
    except ValueError:
        endpoint_set = False
    model_set = bool(settings.model.strip()) and settings.model != "your-model-name"
    key_set = bool(settings.api_key.strip())
    notifier = engine.notifier
    if isinstance(notifier, WebPushNotifier):
        notifications = {
            "kind": "webpush", "key_configured": bool(settings.vapid_private_key),
            "subscriptions": len(store.subscriptions()),
        }
    else:
        notifications = {"kind": "console" if isinstance(notifier, ConsoleNotifier) else "custom"}
    external_diagnostics = getattr(engine.tools, "diagnostics", None)
    return {
        "checked_at": datetime.now(UTC).isoformat(),
        "timezone": settings.timezone,
        "scheduler": {
            "enabled": settings.scheduler_enabled,
            "running_in_this_process": scheduler_running,
            "last_poll_at": (
                scheduler.last_poll_at.isoformat() if scheduler and scheduler.last_poll_at else None
            ),
        },
        "last_success_at": _timestamp(store.last_completed_cycle_at()),
        "next_wake_at": _timestamp(store.get_state("next_wake_at", None)),
        "intervals": {
            "minimum_minutes": settings.min_interval_minutes,
            "maximum_minutes": settings.max_interval_minutes,
            "night_minimum_minutes": settings.night_min_interval_minutes,
            "daily_limit": settings.max_wakes_per_day,
            "quiet_start": settings.quiet_hours_start, "quiet_end": settings.quiet_hours_end,
        },
        "model": {
            "key_configured": key_set, "name_configured": model_set,
            "endpoint_configured": endpoint_set,
            "configuration_complete": key_set and model_set and endpoint_set,
        },
        "notifications": notifications,
        "external_mcp": external_diagnostics() if external_diagnostics else [],
        "cycles": cycles,
    }
