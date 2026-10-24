"""One shared mosaic. A revision stops one client from overwriting another unnoticed."""

from __future__ import annotations

import threading

from pydantic import ValidationError

from app.core.config import Settings
from app.core.exceptions import ConflictError, UnavailableError, ValidationFailed
from app.infrastructure.networking.urls import public_rtsp_url, source_rtsp_url
from app.infrastructure.persistence.json_store import atomic_write_json, read_json
from app.infrastructure.processes.supervisor import ManagedProcess
from app.media.backends.base import MediaBackend
from app.media.mosaic.layouts import LAYOUTS, tiles_for, validate_tiles
from app.media.rtsp.mediamtx import MediaMTXServer
from app.media.rtsp.publisher import local_publish_url
from app.schemas.mosaic import LayoutInfo, MosaicDocument, MosaicOutput, MosaicStatus, MosaicTile, MosaicUpdate, MosaicView
from app.services.camera_registry import CameraRegistry
from app.services.secrets import SecretStore


class MosaicManager:
    def __init__(
        self,
        settings: Settings,
        registry: CameraRegistry,
        secrets: SecretStore,
        media: MediaMTXServer,
        backend: MediaBackend,
    ) -> None:
        self._settings = settings
        self._registry = registry
        self._secrets = secrets
        self._media = media
        self._backend = backend
        self._lock = threading.Lock()
        self._document = self._load()
        self._process: ManagedProcess | None = None
        self._reconnect_required = False
        self._error: str | None = None

    def layouts(self) -> list[LayoutInfo]:
        return list(LAYOUTS.values())

    def view(self, public_host: str) -> MosaicView:
        with self._lock:
            document = self._document
            tiles = self._resolved_tiles(document)
            running = self._process is not None and self._process.running
            return MosaicView(
                revision=document.revision,
                owner=document.owner,
                enabled=document.enabled,
                layout=document.layout,
                output=document.output,
                camera_ids=[tile.camera_id for tile in tiles],
                tiles=tiles,
                gateway_stream_url=public_rtsp_url(
                    public_host, self._settings.streaming.rtsp_port, document.output.stream_name
                ),
                running=running,
                reconnect_required=self._reconnect_required,
                effective_output=document.output,
                adjustments=self._adjustments(document),
            )

    def status(self, public_host: str) -> MosaicStatus:
        media = self._backend.capabilities()
        with self._lock:
            running = self._process is not None and self._process.running
            return MosaicStatus(
                running=running,
                reconnect_required=self._reconnect_required,
                revision=self._document.revision,
                owner=self._document.owner,
                stream_url=public_rtsp_url(
                    public_host, self._settings.streaming.rtsp_port, self._document.output.stream_name
                ),
                pid=self._process.pid if self._process else None,
                restarts=self._process.restarts if self._process else 0,
                error=self._error or (self._process.last_error if self._process else None),
                backend=media.name,
                acceleration=media.acceleration,
            )

    def update(self, payload: MosaicUpdate, public_host: str) -> MosaicView:
        with self._lock:
            current = self._document
            self._check_concurrency(current, payload)
            document = self._build(payload, current)
            self._validate_document(document)
            self._document = document
            self._persist()
            if self._process is not None and self._process.running:
                self._reconnect_required = True
        return self.view(public_host)

    def start(self, public_host: str) -> MosaicStatus:
        with self._lock:
            document = self._document
            if not document.enabled:
                raise ConflictError("The mosaic is disabled.", code="mosaic_disabled")
            tiles = self._resolved_tiles(document)
            self._validate_against_registry(tiles)
            self._check_limits(document.output)
            if not self._media.running:
                raise UnavailableError("The RTSP server is not running.", code="media_server_unavailable")
            sources = [self._source(tile.camera_id) for tile in tiles if tile.visible]
            publish = local_publish_url(self._settings.streaming.rtsp_port, document.output.stream_name)
            command = self._backend.mosaic_command(sources, tiles, document.output, publish)
            self._stop_locked()
            self._process = ManagedProcess(
                name="mosaic",
                args=command,
                log_path=self._settings.log_directory / "mosaic.log",
                restart_attempts=self._settings.limits.mosaic_restart_attempts,
                restart_backoff_seconds=self._settings.limits.mosaic_restart_backoff_seconds,
                stop_timeout_seconds=self._settings.limits.subprocess_stop_timeout_seconds,
                pid_file=self._settings.root / "data" / "run" / "mosaic.pid",
            )
            self._process.start()
            self._reconnect_required = False
            self._error = None
        return self.status(public_host)

    def stop(self, public_host: str) -> MosaicStatus:
        with self._lock:
            self._stop_locked()
            self._reconnect_required = False
        return self.status(public_host)

    def reload_from_disk(self) -> None:
        with self._lock:
            if self._process is not None and self._process.running:
                self._reconnect_required = True
            self._document = self._load()

    def _check_concurrency(self, current: MosaicDocument, payload: MosaicUpdate) -> None:
        if payload.expected_revision is not None and payload.expected_revision != current.revision:
            raise ConflictError(
                "The mosaic was changed by someone else. Reload it and send the current revision.",
                code="revision_conflict",
                details={"revision": current.revision},
            )
        caller_owns_it = bool(current.owner and payload.owner == current.owner)
        if current.owner and not caller_owns_it and payload.expected_revision != current.revision:
            raise ConflictError(
                "This mosaic is owned by another session. Send the current revision to replace it.",
                code="owner_conflict",
                details={"owner": current.owner, "revision": current.revision},
            )
        if not current.owner and current.revision > 1 and payload.expected_revision != current.revision:
            raise ConflictError(
                "Send expected_revision from the current mosaic before replacing it.",
                code="revision_conflict",
                details={"revision": current.revision},
            )

    def terminate_now(self) -> None:
        if self._process is not None:
            self._process.terminate_now()

    def shutdown(self) -> None:
        with self._lock:
            self._stop_locked()

    def _stop_locked(self) -> None:
        if self._process is not None:
            self._process.stop()
            self._process = None

    def _build(self, payload: MosaicUpdate, current: MosaicDocument) -> MosaicDocument:
        owner = payload.owner if payload.owner is not None else current.owner
        enabled = current.enabled if payload.enabled is None else payload.enabled
        try:
            return MosaicDocument(
                schema_version=1,
                revision=current.revision + 1,
                owner=owner,
                enabled=enabled,
                layout=payload.layout,
                output=payload.output,
                camera_ids=payload.camera_ids or [tile.camera_id for tile in (payload.tiles or [])],
                tiles=payload.tiles,
            )
        except ValidationError as exc:
            raise ValidationFailed("Mosaic configuration was rejected.", details={"errors": _json_errors(exc)}) from exc

    def _resolved_tiles(self, document: MosaicDocument) -> list[MosaicTile]:
        if document.layout == "custom":
            if not document.tiles:
                raise ValidationFailed("A custom mosaic requires tiles.")
            validate_tiles(document.tiles, document.output)
            return document.tiles
        return tiles_for(document.layout, document.camera_ids, document.output)

    def _validate_document(self, document: MosaicDocument) -> None:
        tiles = self._resolved_tiles(document)
        self._validate_against_registry(tiles)
        self._check_limits(document.output)

    def _validate_against_registry(self, tiles: list[MosaicTile]) -> None:
        for tile in tiles:
            if not tile.visible:
                continue
            camera = self._registry.get(tile.camera_id)
            if not camera.enabled:
                raise ValidationFailed(f"Camera {camera.id} is disabled.", code="camera_disabled")

    def _check_limits(self, output: MosaicOutput) -> None:
        limits = self._settings.limits
        pixels = output.width * output.height
        if pixels > limits.max_mosaic_pixels:
            raise ValidationFailed(
                "The mosaic output is larger than the configured limit.",
                code="resource_limit",
                details={"pixels": pixels, "max_mosaic_pixels": limits.max_mosaic_pixels},
            )
        if output.fps > limits.max_mosaic_fps or output.bitrate_kbps > limits.max_mosaic_bitrate_kbps:
            raise ValidationFailed(
                "The mosaic frame rate or bitrate exceeds the configured limit.",
                code="resource_limit",
            )

    def _source(self, camera_id: str) -> str:
        camera = self._registry.get(camera_id)
        credentials = self._secrets.camera(camera.credentials_ref or camera.id)
        return source_rtsp_url(camera, credentials.username, credentials.password)

    def _adjustments(self, document: MosaicDocument) -> list[str]:
        notes = []
        if self._reconnect_required:
            notes.append("The published mosaic still uses the previous configuration. Start it again to reconnect viewers.")
        if document.layout != "custom":
            notes.append("Tiles were generated from the preset layout. They do not change camera encoder settings.")
        return notes

    def _load(self) -> MosaicDocument:
        if not self._settings.mosaic_path.is_file():
            raise ValidationFailed("mosaic.json is missing.")
        try:
            return MosaicDocument.model_validate(read_json(self._settings.mosaic_path))
        except ValidationError as exc:
            raise ValidationFailed(f"mosaic.json is invalid: {exc}") from exc

    def _persist(self) -> None:
        atomic_write_json(
            self._settings.mosaic_path,
            self._document.model_dump(mode="json"),
            self._settings.backup_directory,
        )


def _json_errors(exc: ValidationError) -> list[dict]:
    safe: list[dict] = []
    for error in exc.errors():
        item = dict(error)
        context = item.get("ctx")
        if isinstance(context, dict):
            item["ctx"] = {key: str(value) for key, value in context.items()}
        safe.append(item)
    return safe
