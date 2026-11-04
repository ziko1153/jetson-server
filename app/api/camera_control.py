"""Camera encoder settings and PTZ, sent to the camera over ONVIF."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import context
from app.schemas.camera_control import EncoderUpdate, PtzMove

router = APIRouter()


@router.get("/cameras/{camera_id}/encoders")
def encoders(camera_id: str, ctx=Depends(context)) -> dict:
    return ctx.control.encoders(camera_id).model_dump(mode="json")


@router.put("/cameras/{camera_id}/encoders/{encoder_token}")
def set_encoder(camera_id: str, encoder_token: str, update: EncoderUpdate, ctx=Depends(context)) -> dict:
    return ctx.control.set_encoder(camera_id, encoder_token, update).model_dump(mode="json")


@router.get("/cameras/{camera_id}/ptz")
def ptz(camera_id: str, ctx=Depends(context)) -> dict:
    return ctx.control.ptz(camera_id).model_dump(mode="json")


@router.post("/cameras/{camera_id}/ptz/move")
def ptz_move(camera_id: str, move: PtzMove, ctx=Depends(context)) -> dict:
    return ctx.control.move(camera_id, move).model_dump(mode="json")


@router.post("/cameras/{camera_id}/ptz/stop")
def ptz_stop(camera_id: str, ctx=Depends(context)) -> dict:
    return ctx.control.stop(camera_id).model_dump(mode="json")


@router.post("/cameras/{camera_id}/ptz/home")
def ptz_home(camera_id: str, ctx=Depends(context)) -> dict:
    return ctx.control.home(camera_id).model_dump(mode="json")
