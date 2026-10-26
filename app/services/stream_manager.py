"""Individual camera streams. Passthrough does not decode."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

from app.core.config import Settings
from app.core.exceptions import ConflictError, UnavailableError, ValidationFailed
from app.infrastructure.networking.urls import direct_rtsp_url, public_rtsp_url, source_rtsp_url
from app.infrastructure.processes.supervisor import ManagedProcess
from app.media.backends.base import MediaBackend
from app.media.rtsp.mediamtx import MediaMTXServer, camera_path
from app.media.rtsp.proxy import passthrough_conf, publisher_conf
from app.media.rtsp.publisher import local_publish_url
from app.media.rtsp.session import StreamSession
from app.schemas.stream import StreamMetrics, StreamView
from app.services.camera_registry import CameraRegistry
from app.services.secrets import SecretStore


class StreamManager:
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
        self._sessions = {camera.id: StreamSession(camera.id) for camera in registry.list_cameras()}
        self._transcoders: dict[str, ManagedProcess] = {}

    def list_streams(self, public_host: str) -> list[StreamView]:
        return [self.view(camera.id, public_host) for camera in self._registry.list_cameras()]

    def view(self, camera_id: str, public_host: str) -> StreamView:
        camera = self._registry.get(camera_id)
        session = self._session(camera_id)
        info = self._safe_info(camera_id)
        readers = len(info.get("readers") or []) if info else None
        online = _online(info)
        return StreamView(
            camera_id=camera.id,
            name=camera.name,
            phase=session.phase,
            mode=session.mode,  # type: ignore[arg-type]
            gateway_stream_url=public_rtsp_url(public_host, self._settings.streaming.rtsp_port, camera_path(camera.id)),
            direct_stream_url=direct_rtsp_url(camera.connection),
            readers=readers,
            online=online,
            error=session.error,
        )

    def start(self, camera_id: str, mode: str, public_host: str, stream: str = "main") -> StreamView:
        camera = self._registry.get(camera_id)
        if not camera.enabled:
            raise ConflictError(f"Camera {camera.id} is disabled.", code="camera_disabled")
        if not self._media.running:
            raise UnavailableError("The RTSP server is not running.", code="media_server_unavailable")
        credentials = self._secrets.camera(camera.credentials_ref or camera.id)
        source = source_rtsp_url(camera, credentials.username, credentials.password, stream)
        with self._lock:
            if mode == "transcode":
                self._start_transcode(camera.id, source)
            else:
                self._stop_transcode_locked(camera.id)
                self._media.upsert(camera_path(camera.id), passthrough_conf(source, on_demand=False))
            session = self._session(camera.id)
            session.phase = "active"
            session.mode = mode
            session.stream = stream
            session.error = None
            session.started_monotonic = time.monotonic()
        return self.view(camera.id, public_host)

    def stop(self, camera_id: str, public_host: str, *, force: bool) -> StreamView:
        camera = self._registry.get(camera_id)
        info = self._safe_info(camera_id)
        readers = len(info.get("readers") or []) if info else 0
        if readers and not force:
            raise ConflictError(
                "Viewers are connected. Stop them, or send force=true.",
                code="stream_in_use",
                details={"readers": readers},
            )
        credentials = self._secrets.camera(camera.credentials_ref or camera.id)
        session = self._session(camera.id)
        source = source_rtsp_url(camera, credentials.username, credentials.password, session.stream)
        with self._lock:
            self._stop_transcode_locked(camera.id)
            if self._media.running:
                self._media.upsert(camera_path(camera.id), passthrough_conf(source, on_demand=True))
            session.phase = "idle"
            session.mode = "none"
            session.stream = "main"
            session.started_monotonic = None
        return self.view(camera.id, public_host)

    def metrics(self, camera_id: str) -> StreamMetrics:
        camera = self._registry.get(camera_id)
        session = self._session(camera_id)
        info = self._safe_info(camera_id)
        online = _online(info)
        if session.last_online is False and online is True:
            session.reconnect_count += 1
        session.last_online = online
        measured_bitrate = self._bitrate(session, info)
        codec, width, height = _track(info)
        profile = self._settings.profiles[camera.configuration.profile]
        notes = [
            "configured_fps and configured_bitrate_kbps come from the selected profile.",
            "They are not measurements.",
        ]
        if measured_bitrate is None:
            notes.append("measured_bitrate_kbps needs two local samples from the RTSP server.")
        notes.append("last_frame_at is unavailable without decoding the stream.")
        uptime = None
        if session.started_monotonic is not None and session.phase == "active":
            uptime = round(time.monotonic() - session.started_monotonic, 3)
        return StreamMetrics(
            camera_id=camera.id,
            phase=session.phase,
            connected=online,
            configured_fps=float(profile.fps),
            measured_fps=None,
            configured_bitrate_kbps=profile.bitrate_kbps,
            measured_bitrate_kbps=measured_bitrate,
            codec=codec,
            width=width,
            height=height,
            last_frame_at=None,
            uptime_seconds=uptime,
            reconnect_count=session.reconnect_count,
            error=session.error,
            measurement_notes=notes,
        )

    def refresh_path(self, camera_id: str) -> None:
        if not self._media.running:
            return
        camera = self._registry.get(camera_id)
        path = camera_path(camera.id)
        if not camera.enabled:
            self._media.delete(path)
            return
        session = self._session(camera.id)
        if session.mode == "transcode":
            return
        credentials = self._secrets.camera(camera.credentials_ref or camera.id)
        source = source_rtsp_url(camera, credentials.username, credentials.password, session.stream)
        on_demand = not (session.phase == "active" and session.mode == "passthrough")
        self._media.upsert(path, passthrough_conf(source, on_demand=on_demand))

    def terminate_now(self) -> None:
        for process in self._transcoders.values():
            process.terminate_now()

    def stop_all(self) -> None:
        with self._lock:
            for camera_id in list(self._transcoders):
                self._stop_transcode_locked(camera_id)

    def _start_transcode(self, camera_id: str, source: str) -> None:
        active = [item for item in self._transcoders.values() if item.running]
        if len(active) >= self._settings.limits.max_transcode_streams and camera_id not in self._transcoders:
            raise ValidationFailed(
                "The transcode limit has been reached.",
                code="resource_limit",
                details={"max_transcode_streams": self._settings.limits.max_transcode_streams},
            )
        camera = self._registry.get(camera_id)
        profile = self._settings.profiles[camera.configuration.profile]
        overrides = camera.configuration.gateway_overrides
        width = overrides.width if overrides and overrides.width else profile.width
        height = overrides.height if overrides and overrides.height else profile.height
        fps = overrides.fps if overrides and overrides.fps else profile.fps
        bitrate = overrides.bitrate_kbps if overrides and overrides.bitrate_kbps else profile.bitrate_kbps
        publish = local_publish_url(self._settings.streaming.rtsp_port, camera_path(camera_id))
        self._media.upsert(camera_path(camera_id), publisher_conf())
        self._stop_transcode_locked(camera_id)
        command = self._backend.transcode_command(
            source,
            publish,
            width=width,
            height=height,
            fps=fps,
            bitrate_kbps=bitrate,
        )
        process = ManagedProcess(
            name=f"transcode-{camera_id}",
            args=command,
            log_path=self._settings.log_directory / f"transcode-{camera_id}.log",
            restart_attempts=self._settings.limits.mosaic_restart_attempts,
            restart_backoff_seconds=self._settings.limits.mosaic_restart_backoff_seconds,
            stop_timeout_seconds=self._settings.limits.subprocess_stop_timeout_seconds,
            pid_file=self._settings.root / "data" / "run" / f"transcode-{camera_id}.pid",
        )
        process.start()
        self._transcoders[camera_id] = process

    def _stop_transcode_locked(self, camera_id: str) -> None:
        process = self._transcoders.pop(camera_id, None)
        if process is not None:
            process.stop()

    def _session(self, camera_id: str) -> StreamSession:
        session = self._sessions.get(camera_id)
        if session is None:
            session = StreamSession(camera_id)
            self._sessions[camera_id] = session
        return session

    def _safe_info(self, camera_id: str) -> dict | None:
        if not self._media.running:
            return None
        try:
            return self._media.path_info(camera_path(camera_id))
        except UnavailableError:
            return None

    def _bitrate(self, session: StreamSession, info: dict | None) -> float | None:
        if not info:
            return None
        raw = info.get("inboundBytes")
        if not isinstance(raw, int):
            return None
        now = time.monotonic()
        measured = None
        if session.last_bytes is not None and session.last_sample_at is not None:
            elapsed = now - session.last_sample_at
            delta = raw - session.last_bytes
            if elapsed > 0 and delta >= 0:
                measured = round((delta * 8 / 1000) / elapsed, 3)
        session.last_bytes = raw
        session.last_sample_at = now
        return measured


def _online(info: dict | None) -> bool | None:
    if info is None:
        return None
    if "online" in info:
        return bool(info["online"])
    if "ready" in info:
        return bool(info["ready"])
    return None


def _track(info: dict | None) -> tuple[str | None, int | None, int | None]:
    if not info:
        return None, None, None
    tracks = info.get("tracks2") or []
    if not tracks:
        legacy = info.get("tracks") or []
        if legacy and isinstance(legacy[0], str):
            return legacy[0].lower(), None, None
        return None, None, None
    track = tracks[0]
    codec = track.get("codec")
    props = track.get("codecProps") or {}
    width = props.get("width")
    height = props.get("height")
    return (
        str(codec).lower() if codec else None,
        width if isinstance(width, int) else None,
        height if isinstance(height, int) else None,
    )


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
