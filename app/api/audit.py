"""Configuration audit history."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import context

router = APIRouter()


@router.get("/audit/camera-configurations")
def camera_configurations(
    camera_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    ctx=Depends(context),
) -> dict:
    items = ctx.audit.list_events(limit=limit, offset=offset, camera_id=camera_id)
    return {"items": items, "count": len(items)}
