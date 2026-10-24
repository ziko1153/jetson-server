"""Health and system endpoints."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request

from app.api.deps import context
from app.media.capabilities import system_capabilities
from app.services.resources import host_resources

router = APIRouter()


@router.get("/health")
def health(ctx=Depends(context)) -> dict:
    return {
        "status": "ok",
        "hardware": ctx.environment.hardware,
        "auth": ctx.authenticator.mode,
        "media_server": "running" if ctx.media.running else "stopped",
    }


@router.get("/system/capabilities")
def capabilities(ctx=Depends(context)) -> dict:
    return system_capabilities(ctx.environment, ctx.backend, ctx.settings.profiles)


@router.get("/system/status")
def status(ctx=Depends(context)) -> dict:
    pids = []
    if ctx.media.pid:
        pids.append(ctx.media.pid)
    mosaic_status = ctx.mosaic.status("127.0.0.1")
    if mosaic_status.pid:
        pids.append(mosaic_status.pid)
    uptime = (datetime.now(timezone.utc) - ctx.started_at).total_seconds()
    rcwm = ctx.rcwm.snapshot()
    return {
        "started_at": ctx.started_at.isoformat(),
        "uptime_seconds": round(uptime, 3),
        "auth_mode": ctx.authenticator.mode,
        "health_checks_enabled": ctx.health.enabled,
        "camera_count": len(ctx.registry.list_cameras()),
        "resources": host_resources(pids),
        "cameras": {
            "count": len(ctx.registry.list_cameras()),
            "media_server": "running" if ctx.media.running else "stopped",
            "health_checks": "running" if ctx.health.enabled else "stopped",
        },
        "host": ctx.host.collect(ctx.environment, ctx.settings.root),
        "mavlink": ctx.mavlink.snapshot(),
        "rcwm": rcwm,
        "esp32": rcwm["esp32"],
    }


@router.post("/system/reload")
def reload_config(request: Request, ctx=Depends(context)) -> dict:
    ctx.registry.reload()
    ctx.mosaic.reload_from_disk()
    return {"reloaded": True, "request_id": request.state.request_id}
