from __future__ import annotations

import hmac
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from threading import Event, Thread
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from . import __version__
from .config import Settings
from .engine import WakeEngine
from .hands import build_all_tools
from .mcp_server import build_mcp_server
from .models import WakeSeed
from .notifiers import WebPushNotifier
from .providers import OpenAICompatibleProvider
from .scheduler import WakeScheduler
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


def create_app(
    settings: Settings | None = None,
    engine: WakeEngine | None = None,
    *,
    run_scheduler: bool = False,
    mount_web: bool = False,
    poll_seconds: float = 5.0,
) -> FastAPI:
    settings = settings or Settings()
    settings.ensure_runtime_dirs()
    if engine is None:
        store = SQLiteStore(settings.db_path)
        engine = WakeEngine(
            settings,
            store,
            OpenAICompatibleProvider(settings),
            build_all_tools(store, settings),
            WebPushNotifier(settings, store),
        )

    mcp_server = build_mcp_server(settings, engine)
    mcp_app = mcp_server.streamable_http_app()
    stop_scheduler = Event()
    scheduler_thread: Thread | None = None

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        nonlocal scheduler_thread
        async with mcp_server.session_manager.run():
            if run_scheduler and settings.scheduler_enabled:
                scheduler = WakeScheduler(engine, poll_seconds)
                scheduler_thread = Thread(
                    target=scheduler.run_forever,
                    args=(stop_scheduler,),
                    name="waketrace-scheduler",
                    daemon=True,
                )
                scheduler_thread.start()
            yield
            stop_scheduler.set()
            if scheduler_thread is not None:
                scheduler_thread.join(timeout=max(2.0, poll_seconds + 1.0))

    app = FastAPI(title="WakeTrace", version=__version__, lifespan=lifespan)
    web_origins = [origin.strip() for origin in settings.web_origins.split(",") if origin.strip()]
    if web_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=web_origins,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type"],
        )

    @app.middleware("http")
    async def authorize_mcp(request: Request, call_next):
        if request.url.path == "/mcp":
            if not settings.mcp_token:
                return JSONResponse(
                    {"detail": "WAKETRACE_MCP_TOKEN is not configured"},
                    status_code=503,
                )
            authorization = request.headers.get("authorization", "")
            if not hmac.compare_digest(authorization, f"Bearer {settings.mcp_token}"):
                return JSONResponse({"detail": "invalid bearer token"}, status_code=401)
        return await call_next(request)

    def token_matches(authorization: str | None, token: str) -> bool:
        return bool(token) and hmac.compare_digest(authorization or "", f"Bearer {token}")

    def authorize_admin(authorization: str | None = Header(default=None)) -> None:
        if not settings.admin_token:
            raise HTTPException(503, "WAKETRACE_ADMIN_TOKEN is not configured")
        if not token_matches(authorization, settings.admin_token):
            raise HTTPException(401, "invalid bearer token")

    def authorize_read(authorization: str | None = Header(default=None)) -> None:
        if token_matches(authorization, settings.web_token):
            return
        if token_matches(authorization, settings.admin_token):
            return
        if not settings.web_token and not settings.admin_token:
            raise HTTPException(503, "no WakeTrace access token is configured")
        raise HTTPException(401, "invalid bearer token")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/status", dependencies=[Depends(authorize_admin)])
    def status() -> dict[str, Any]:
        return {
            "next_wake_at": engine.store.get_state("next_wake_at", None),
            "last_successful_wake_at": engine.store.get_state("last_successful_wake_at", None),
            "wake_counters": engine.store.get_state("wake_counters", {}),
        }

    @app.post("/wake", dependencies=[Depends(authorize_admin)])
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

    @app.post("/subscriptions", dependencies=[Depends(authorize_admin)])
    def subscribe(payload: SubscriptionRequest) -> dict[str, bool]:
        engine.store.add_subscription(payload.subscription)
        return {"ok": True}

    @app.post("/world/events", dependencies=[Depends(authorize_admin)])
    def world_event(payload: WorldEventRequest) -> dict[str, int]:
        event_id = engine.store.enqueue_world_event(
            payload.kind,
            payload.summary,
            evidence=payload.evidence,
            available_at=payload.available_at,
        )
        return {"event_id": event_id}

    @app.get("/world/timeline", dependencies=[Depends(authorize_read)])
    def timeline(limit: int = Query(default=30, ge=1, le=100)) -> dict[str, Any]:
        return {"timeline": engine.store.recent_timeline(limit)}

    @app.get("/world/timeline/{trace_id}", dependencies=[Depends(authorize_read)])
    def timeline_detail(trace_id: int) -> dict[str, Any]:
        detail = engine.store.timeline_detail(trace_id)
        if detail is None:
            raise HTTPException(404, "timeline entry not found")
        return {"entry": detail}

    @app.get("/world/threads", dependencies=[Depends(authorize_read)])
    def threads() -> dict[str, Any]:
        return {"threads": engine.store.list_life_threads()}

    @app.get("/world/artifacts", dependencies=[Depends(authorize_read)])
    def artifacts(limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
        return {"artifacts": engine.store.list_life_artifacts(limit)}

    # FastMCP's own lifespan is entered above; only its protocol route is shared.
    app.router.routes.extend(mcp_app.routes)

    if mount_web and settings.web_dist_path.is_dir():
        app.mount("/", StaticFiles(directory=settings.web_dist_path, html=True), name="web")

    return app
