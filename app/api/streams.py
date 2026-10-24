"""Managed RTSP streams."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import client_host, context
from app.schemas.stream import StreamStartRequest, StreamStopRequest

router = APIRouter()


@router.get("/streams")
def list_streams(host: str = Depends(client_host), ctx=Depends(context)) -> dict:
    items = [item.model_dump(mode="json") for item in ctx.streams.list_streams(host)]
    return {"items": items, "count": len(items)}


@router.get("/streams/{camera_id}")
def get_stream(camera_id: str, host: str = Depends(client_host), ctx=Depends(context)) -> dict:
    return ctx.streams.view(camera_id, host).model_dump(mode="json")


@router.post("/streams/{camera_id}/start")
def start_stream(
    camera_id: str,
    body: StreamStartRequest | None = None,
    host: str = Depends(client_host),
    ctx=Depends(context),
) -> dict:
    mode = body.mode if body else "passthrough"
    return ctx.streams.start(camera_id, mode, host).model_dump(mode="json")


@router.post("/streams/{camera_id}/stop")
def stop_stream(
    camera_id: str,
    body: StreamStopRequest | None = None,
    host: str = Depends(client_host),
    ctx=Depends(context),
) -> dict:
    force = body.force if body else False
    return ctx.streams.stop(camera_id, host, force=force).model_dump(mode="json")


@router.get("/streams/{camera_id}/metrics")
def stream_metrics(camera_id: str, ctx=Depends(context)) -> dict:
    return ctx.streams.metrics(camera_id).model_dump(mode="json")
