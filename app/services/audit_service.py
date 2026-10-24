"""Audit log used by camera configuration."""

from __future__ import annotations

from app.infrastructure.persistence.json_store import AuditStore


class AuditService:
    def __init__(self, store: AuditStore) -> None:
        self._store = store

    def record(self, **kwargs: object) -> None:
        self._store.record(**kwargs)  # type: ignore[arg-type]

    def list_events(self, *, limit: int, offset: int, camera_id: str | None = None) -> list[dict]:
        return self._store.list_events(limit=limit, offset=offset, camera_id=camera_id)
