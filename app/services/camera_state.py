"""Runtime camera status that is not part of the human-edited registry."""

from __future__ import annotations

import threading
from pathlib import Path

from app.infrastructure.persistence.json_store import atomic_write_json, read_json
from app.schemas.camera import CapabilityReport, PhysicalSettings


class CameraStateStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._items: dict[str, dict] = {}
        if path.is_file():
            payload = read_json(path)
            if isinstance(payload, dict):
                self._items = {key: value for key, value in payload.items() if isinstance(value, dict)}

    def get(self, camera_id: str) -> dict:
        with self._lock:
            return dict(self._items.get(camera_id, {}))

    def update(self, camera_id: str, **changes: object) -> dict:
        with self._lock:
            current = dict(self._items.get(camera_id, {}))
            current.update(changes)
            self._items[camera_id] = current
            self._persist()
            return dict(current)

    def capabilities(self, camera_id: str) -> CapabilityReport:
        raw = self.get(camera_id).get("capabilities")
        if not isinstance(raw, dict):
            return CapabilityReport(
                camera_id=camera_id,
                limitations=["Capabilities have not been probed. Probe does not run until it is requested."],
            )
        return CapabilityReport.model_validate(raw)

    def physical_settings(self, camera_id: str) -> PhysicalSettings | None:
        raw = self.get(camera_id).get("physical_settings")
        if not isinstance(raw, dict):
            return None
        return PhysicalSettings.model_validate(raw)

    def _persist(self) -> None:
        atomic_write_json(self._path, self._items)
