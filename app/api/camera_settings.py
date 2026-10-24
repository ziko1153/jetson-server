"""Physical and gateway camera settings."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import context
from app.schemas.camera import SettingsUpdate

router = APIRouter()


@router.get("/cameras/{camera_id}/capabilities")
def capabilities(camera_id: str, ctx=Depends(context)) -> dict:
    return ctx.configuration.capabilities(camera_id).model_dump(mode="json")


@router.get("/cameras/{camera_id}/settings")
def get_settings(camera_id: str, ctx=Depends(context)) -> dict:
    return ctx.configuration.settings(camera_id).model_dump(mode="json")


@router.put("/cameras/{camera_id}/settings")
def put_settings(camera_id: str, update: SettingsUpdate, ctx=Depends(context)) -> dict:
    return ctx.configuration.update_settings(camera_id, update).model_dump(mode="json")
