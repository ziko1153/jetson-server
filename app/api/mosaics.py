"""Shared mosaic endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import client_host, context
from app.schemas.mosaic import MosaicUpdate

router = APIRouter()


@router.get("/mosaic/layouts")
def layouts(ctx=Depends(context)) -> dict:
    items = [item.model_dump() for item in ctx.mosaic.layouts()]
    return {"items": items, "count": len(items)}


@router.get("/mosaic")
def get_mosaic(host: str = Depends(client_host), ctx=Depends(context)) -> dict:
    return ctx.mosaic.view(host).model_dump(mode="json")


@router.put("/mosaic")
def put_mosaic(payload: MosaicUpdate, host: str = Depends(client_host), ctx=Depends(context)) -> dict:
    return ctx.mosaic.update(payload, host).model_dump(mode="json")


@router.post("/mosaic/start")
def start_mosaic(host: str = Depends(client_host), ctx=Depends(context)) -> dict:
    return ctx.mosaic.start(host).model_dump(mode="json")


@router.post("/mosaic/stop")
def stop_mosaic(host: str = Depends(client_host), ctx=Depends(context)) -> dict:
    return ctx.mosaic.stop(host).model_dump(mode="json")
