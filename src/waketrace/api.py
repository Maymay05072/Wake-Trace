from __future__ import annotations

import hmac
from datetime import UTC, datetime
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from .config import Settings
from .engine import WakeEngine
from .lifeworld import build_lifeworld_tools
from .models import WakeSeed
from .notifiers import WebPushNotifier
from .providers import OpenAICompatibleProvider
from .storage import SQLiteStore


class WakeRequest(BaseModel):
    kind: str = Field(default="manual", max_length=64)
    summary: str = Field(min_length=1, max_length=1000)
    evidence: dict[str, Any] = Field(default_factory=dict)
    force: bool = False


class SubscriptionRequest(BaseModel):
    subscription: dict[str, Any]


class WorldEventRequest(BaseModel):
    kind: str = Field(default="external", max_length=64)
    summary: str = Field(min_length=1, max_length=1000)
    evidence: dict[str, Any] = Field(default_factory=dict)
    available_at: datetime | None = None

    @field_validator("available_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("available_at must include a timezone")
        return value


def create_app(settings: Settings | None = None, engine: WakeEngine | None = None) -> FastAPI:
    settings = settings or Settings()
    settings.ensure_runtime_dirs()
    if engine is None:
        store = SQLiteStore(settings.db_path)
        engine = WakeEngine(
            settings,
            store,
            OpenAICompatibleProvider(settings),
            build_lifeworld_tools(store),
            WebPushNotifier(settings, store),
        )

    app = FastAPI(title="WakeTrace", version="0.1.0-alpha")

    def authorize(authorization: str | None = Header(default=None)) -> None:
        if not settings.admin_token:
            raise HTTPException(503, "WAKETRACE_ADMIN_TOKEN is not configured")
        supplied = authorization or ""
        expected = f"Bearer {settings.admin_token}"
        if not hmac.compare_digest(supplied, expected):
            raise HTTPException(401, "invalid bearer token")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/status", dependencies=[Depends(authorize)])
    def status() -> dict[str, Any]:
        return {
            "next_wake_at": engine.store.get_state("next_wake_at", None),
            "last_successful_wake_at": engine.store.get_state("last_successful_wake_at", None),
            "wake_counters": engine.store.get_state("wake_counters", {}),
        }

    @app.post("/wake", dependencies=[Depends(authorize)])
    def wake(payload: WakeRequest) -> dict[str, Any]:
        result = engine.run(
            WakeSeed(payload.kind, payload.summary, datetime.now(UTC), payload.evidence),
            force=payload.force,
        )
        return {
            "cycle_id": result.cycle_id,
            "outcome": result.outcome,
            "notified": result.notified,
            "next_wake_at": result.next_wake_at.isoformat(),
        }

    @app.post("/subscriptions", dependencies=[Depends(authorize)])
    def subscribe(payload: SubscriptionRequest) -> dict[str, bool]:
        engine.store.add_subscription(payload.subscription)
        return {"ok": True}

    @app.post("/world/events", dependencies=[Depends(authorize)])
    def world_event(payload: WorldEventRequest) -> dict[str, int]:
        event_id = engine.store.enqueue_world_event(
            payload.kind,
            payload.summary,
            evidence=payload.evidence,
            available_at=payload.available_at,
        )
        return {"event_id": event_id}

    @app.get("/world/timeline", dependencies=[Depends(authorize)])
    def timeline(limit: int = Query(default=30, ge=1, le=100)) -> dict[str, Any]:
        return {"timeline": engine.store.recent_timeline(limit)}

    @app.get("/world/threads", dependencies=[Depends(authorize)])
    def threads() -> dict[str, Any]:
        return {"threads": engine.store.list_life_threads()}

    @app.get("/world/artifacts", dependencies=[Depends(authorize)])
    def artifacts(limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
        return {"artifacts": engine.store.list_life_artifacts(limit)}

    return app
