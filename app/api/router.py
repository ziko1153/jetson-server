"""HTTP application."""

from __future__ import annotations

import signal
import threading
import uuid
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.audit import router as audit_router
from app.api.camera_settings import router as settings_router
from app.api.cameras import router as cameras_router
from app.api.deps import require_auth
from app.api.errors import install_error_handlers
from app.api.health import router as health_router
from app.api.mosaics import router as mosaic_router
from app.api.streams import router as streams_router
from app.core.config import Settings, load_settings
from app.core.logging import configure_logging, request_id_var
from app.services.context import build_context


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        token = request_id_var.set(request_id)
        request.state.request_id = request_id
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = request_id
        return response


def _install_stop_handlers(ctx) -> dict:
    if threading.current_thread() is not threading.main_thread():
        return {}
    previous: dict = {}

    def handler(signum, frame) -> None:
        ctx.mosaic.terminate_now()
        ctx.streams.terminate_now()
        ctx.media.terminate_now()
        earlier = previous.get(signum)
        if callable(earlier):
            earlier(signum, frame)

    for signum in (signal.SIGTERM, signal.SIGINT):
        previous[signum] = signal.signal(signum, handler)
    return previous


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        current = app.state.settings_override or load_settings()
        configure_logging(current.logging.level, current.log_directory)
        ctx = build_context(current)
        app.state.ctx = ctx
        if current.streaming.manage_media_server:
            ctx.media.start(ctx.media_config())
        ctx.health.start()
        ctx.rcwm.start()
        ctx.mavlink.start()
        previous_handlers = _install_stop_handlers(ctx)
        try:
            yield
        finally:
            for signum, handler in previous_handlers.items():
                signal.signal(signum, handler)
            ctx.mavlink.stop()
            ctx.rcwm.stop()
            ctx.mosaic.shutdown()
            ctx.streams.stop_all()
            ctx.health.stop()
            ctx.media.stop()

    app = FastAPI(
        title="UGV Jetson Gateway",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings_override = settings
    app.add_middleware(RequestIdMiddleware)
    install_error_handlers(app)
    api = APIRouter(prefix="/api/v1", dependencies=[Depends(require_auth)])
    api.include_router(health_router)
    api.include_router(cameras_router)
    api.include_router(settings_router)
    api.include_router(streams_router)
    api.include_router(mosaic_router)
    api.include_router(audit_router)
    app.include_router(api)

    @app.get("/")
    def root() -> dict:
        return {"name": "ugv-jetson-gateway", "api": "/api/v1", "docs": "/docs"}

    return app
