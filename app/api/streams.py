"""Managed RTSP streams."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import client_host, context
from app.schemas.stream import StreamStartRequest, StreamStopRequest

router = APIRouter()


@router.post("/streams/{camera_id}/start")
def start_stream(
    camera_id: str,
    body: StreamStartRequest | None = None,
    host: str = Depends(client_host),
    ctx=Depends(context),
) -> dict:
    mode = body.mode if body else "passthrough"
    stream = body.stream if body else "main"
    return ctx.streams.start(camera_id, mode, host, stream).model_dump(mode="json")


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
