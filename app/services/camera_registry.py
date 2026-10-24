"""Authoritative camera registry. Identifiers are independent of IP addresses."""

from __future__ import annotations

import threading
from pathlib import Path

from pydantic import ValidationError

from app.core.exceptions import ConfigurationError, NotFoundError, ValidationFailed
from app.infrastructure.persistence.json_store import atomic_write_json, read_json
from app.schemas.camera import CameraFile, CameraPatch, CameraRecord, ConnectionSettings


class CameraRegistry:
    def __init__(self, path: Path, backup_directory: Path) -> None:
        self._path = path
        self._backup_directory = backup_directory
        self._lock = threading.Lock()
        self._cameras = self._load()

    def list_cameras(self) -> list[CameraRecord]:
        with self._lock:
            return list(self._cameras.values())

    def get(self, camera_id: str) -> CameraRecord:
        with self._lock:
            camera = self._cameras.get(camera_id)
        if camera is None:
            raise NotFoundError(f"Camera {camera_id} is not registered.")
        return camera

    def replace(self, camera: CameraRecord) -> CameraRecord:
        with self._lock:
            if camera.id not in self._cameras:
                raise NotFoundError(f"Camera {camera.id} is not registered.")
            self._cameras[camera.id] = camera
            self._persist()
            return camera

    def reload(self) -> None:
        with self._lock:
            self._cameras = self._load()

    def update(self, camera_id: str, patch: CameraPatch) -> CameraRecord:
        with self._lock:
            current = self._cameras.get(camera_id)
            if current is None:
                raise NotFoundError(f"Camera {camera_id} is not registered.")
            updated = _apply_patch(current, patch)
            self._cameras[camera_id] = updated
            self._persist()
            return updated

    def _load(self) -> dict[str, CameraRecord]:
        if not self._path.is_file():
            raise ConfigurationError(f"Camera registry is missing: {self._path}")
        try:
            document = CameraFile.model_validate(read_json(self._path))
        except (ValidationError, ValueError) as exc:
            raise ConfigurationError(f"cameras.json is invalid: {exc}") from exc
        if document.schema_version != 1:
            raise ConfigurationError("cameras.json schema_version must be 1")
        cameras: dict[str, CameraRecord] = {}
        for camera in document.cameras:
            if camera.id in cameras:
                raise ConfigurationError(f"Duplicate camera id {camera.id}")
            cameras[camera.id] = camera
        if not cameras:
            raise ConfigurationError("cameras.json does not define any cameras")
        return cameras

    def _persist(self) -> None:
        payload = CameraFile(schema_version=1, cameras=list(self._cameras.values())).model_dump(mode="json")
        atomic_write_json(self._path, payload, self._backup_directory)


def _safe_errors(exc: ValidationError) -> list[dict]:
    safe: list[dict] = []
    for error in exc.errors():
        item = dict(error)
        context = item.get("ctx")
        if isinstance(context, dict):
            item["ctx"] = {key: str(value) for key, value in context.items()}
        safe.append(item)
    return safe


def _apply_patch(camera: CameraRecord, patch: CameraPatch) -> CameraRecord:
    data = camera.model_dump()
    connection = data["connection"]
    configuration = data["configuration"]
    for field in ("name", "enabled", "manufacturer", "model"):
        value = getattr(patch, field)
        if value is not None:
            data[field] = value
    for field in ("host", "port", "protocol", "path", "onvif_port", "onvif_path"):
        value = getattr(patch, field)
        if value is not None:
            connection[field] = value
    if patch.driver is not None:
        configuration["driver"] = patch.driver
    if patch.profile is not None:
        configuration["profile"] = patch.profile
    try:
        connection_model = ConnectionSettings.model_validate(connection)
        updated = CameraRecord.model_validate({**data, "connection": connection_model.model_dump()})
    except ValidationError as exc:
        raise ValidationFailed("Camera update was rejected.", details={"errors": _safe_errors(exc)}) from exc
    return updated
