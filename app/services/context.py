"""Wire the services that the API and process lifecycle share."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import Settings
from app.core.environment import detect_environment
from app.core.exceptions import ConfigurationError
from app.core.security import AuthSettings, Authenticator
from app.health.metrics import HostSampler
from app.mavlink.gateway import MavlinkGateway
from app.rcwm.service import RcwmService
from app.infrastructure.networking.urls import source_rtsp_url
from app.infrastructure.persistence.json_store import AuditStore
from app.media.backends.factory import select_backend
from app.media.rtsp.mediamtx import MediaMTXServer, render_config
from app.services.audit_service import AuditService
from app.services.camera_configuration import CameraConfigurationService
from app.services.camera_health import CameraHealthMonitor
from app.services.camera_manager import CameraManager
from app.services.camera_registry import CameraRegistry
from app.services.camera_state import CameraStateStore
from app.services.mosaic_manager import MosaicManager
from app.services.secrets import SecretStore, load_secrets
from app.services.stream_manager import StreamManager


@dataclass
class AppContext:
    settings: Settings
    environment: object
    authenticator: Authenticator
    secrets: SecretStore
    registry: CameraRegistry
    state: CameraStateStore
    health: CameraHealthMonitor
    configuration: CameraConfigurationService
    cameras: CameraManager
    streams: StreamManager
    mosaic: MosaicManager
    media: MediaMTXServer
    backend: object
    audit: AuditService
    mavlink: MavlinkGateway
    rcwm: RcwmService
    host: HostSampler
    started_at: datetime

    def media_config(self) -> str:
        token = None
        if self.settings.streaming.playback_authentication == "bearer":
            token = self.secrets.api_token
            if not token:
                raise ConfigurationError(
                    "streaming.playback_authentication is bearer, but no API token is configured."
                )
        sources = {}
        for camera in self.registry.list_cameras():
            credentials = self.secrets.camera(camera.credentials_ref or camera.id)
            sources[camera.id] = source_rtsp_url(camera, credentials.username, credentials.password)
        return render_config(
            cameras=self.registry.list_cameras(),
            source_urls=sources,
            rtsp_port=self.settings.streaming.rtsp_port,
            control_port=self.settings.streaming.control_port,
            playback_token=token,
            rtsp_bind_host=self.settings.streaming.rtsp_bind_host,
        )


def build_context(settings: Settings) -> AppContext:
    settings.log_directory.mkdir(parents=True, exist_ok=True)
    settings.backup_directory.mkdir(parents=True, exist_ok=True)
    secrets = load_secrets(settings.secrets_path)
    binary = _media_binary(settings)
    environment = detect_environment(mediamtx_path=binary)
    backend = select_backend(environment, settings.environment.media_backend)
    authenticator = Authenticator(
        AuthSettings(mode=settings.auth.mode, exempt_paths=tuple(settings.auth.exempt_paths), token=secrets.api_token)
    )
    audit = AuditService(AuditStore(settings.audit_path))
    registry = CameraRegistry(settings.cameras_path, settings.backup_directory)
    state = CameraStateStore(settings.camera_state_path)
    media = MediaMTXServer(
        binary,
        settings.media_server_config_path,
        settings.log_directory / "mediamtx.log",
        settings.streaming.control_port,
        settings.limits.subprocess_stop_timeout_seconds,
        settings.root / "data" / "run" / "mediamtx.pid",
    )
    streams = StreamManager(settings, registry, secrets, media, backend)
    health = CameraHealthMonitor(
        registry,
        state,
        enabled=settings.health.enabled,
        interval_seconds=settings.health.interval_seconds,
        timeout_seconds=settings.health.probe_timeout_seconds,
    )
    configuration = CameraConfigurationService(registry, state, secrets, audit, environment.ffprobe)
    cameras = CameraManager(settings, registry, state, streams)
    mosaic = MosaicManager(settings, registry, secrets, media, backend)
    rcwm = RcwmService(
        settings.rcwm,
        settings.rcwm_state_path,
        allowed_system_ids=tuple(settings.mavlink.allowed_gcs_system_ids),
    )
    mavlink_gateway = MavlinkGateway(settings.mavlink, rcwm.handle)
    return AppContext(
        settings=settings,
        environment=environment,
        authenticator=authenticator,
        secrets=secrets,
        registry=registry,
        state=state,
        health=health,
        configuration=configuration,
        cameras=cameras,
        streams=streams,
        mosaic=mosaic,
        media=media,
        backend=backend,
        audit=audit,
        mavlink=mavlink_gateway,
        rcwm=rcwm,
        host=HostSampler(),
        started_at=datetime.now(timezone.utc),
    )


def _media_binary(settings: Settings) -> Path | None:
    if settings.streaming.media_server_binary:
        return Path(settings.streaming.media_server_binary)
    bundled = settings.root / "vendor" / "mediamtx" / "mediamtx"
    if bundled.is_file():
        return bundled
    found = shutil.which("mediamtx")
    if found:
        return Path(found)
    return None
