"""Camera registry endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import client_host, context
from app.schemas.camera import CameraPatch

router = APIRouter()


@router.get("/cameras")
def list_cameras(host: str = Depends(client_host), ctx=Depends(context)) -> dict:
    items = [item.model_dump(mode="json") for item in ctx.cameras.list_cameras(host)]
    return {"items": items, "count": len(items)}


@router.get("/cameras/{camera_id}")
def get_camera(camera_id: str, host: str = Depends(client_host), ctx=Depends(context)) -> dict:
    return ctx.cameras.view(camera_id, host).model_dump(mode="json")


@router.patch("/cameras/{camera_id}")
def patch_camera(camera_id: str, patch: CameraPatch, host: str = Depends(client_host), ctx=Depends(context)) -> dict:
    ctx.registry.update(camera_id, patch)
    ctx.streams.refresh_path(camera_id)
    return ctx.cameras.view(camera_id, host).model_dump(mode="json")


@router.get("/cameras/{camera_id}/status")
def camera_status(camera_id: str, host: str = Depends(client_host), ctx=Depends(context)) -> dict:
    return ctx.cameras.status(camera_id, host).model_dump(mode="json")


@router.post("/cameras/{camera_id}/probe")
def probe_camera(camera_id: str, ctx=Depends(context)) -> dict:
    return ctx.configuration.probe(camera_id).model_dump(mode="json")
