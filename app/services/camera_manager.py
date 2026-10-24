"""Camera views returned to the ground control station."""

from __future__ import annotations

from app.core.config import Settings
from app.infrastructure.networking.urls import assert_public_url_has_no_credentials, direct_rtsp_url, public_rtsp_url
from app.media.rtsp.mediamtx import camera_path
from app.schemas.camera import CameraStatus, CameraView
from app.services.camera_registry import CameraRegistry
from app.services.camera_state import CameraStateStore
from app.services.stream_manager import StreamManager


class CameraManager:
    def __init__(
        self,
        settings: Settings,
        registry: CameraRegistry,
        state: CameraStateStore,
        streams: StreamManager,
    ) -> None:
        self._settings = settings
        self._registry = registry
        self._state = state
        self._streams = streams

    def list_cameras(self, public_host: str) -> list[CameraView]:
        return [self.view(camera.id, public_host) for camera in self._registry.list_cameras()]

    def view(self, camera_id: str, public_host: str) -> CameraView:
        camera = self._registry.get(camera_id)
        runtime = self._state.get(camera.id)
        capabilities = self._state.capabilities(camera.id)
        stream = self._streams.view(camera.id, public_host)
        direct = direct_rtsp_url(camera.connection)
        gateway = public_rtsp_url(public_host, self._settings.streaming.rtsp_port, camera_path(camera.id))
        assert_public_url_has_no_credentials(direct)
        assert_public_url_has_no_credentials(gateway)
        return CameraView(
            id=camera.id,
            name=camera.name,
            enabled=camera.enabled,
            manufacturer=camera.manufacturer,
            model=camera.model,
            connection=camera.connection,
            driver=camera.configuration.driver,
            profile=camera.configuration.profile,
            connection_status=runtime.get("connection_status", "unknown"),
            network_reachable=runtime.get("network_reachable"),
            last_success_at=runtime.get("last_success_at"),
            stream_phase=stream.phase,
            gateway_stream_url=gateway,
            direct_stream_url=direct,
            capabilities_known=capabilities.source != "unknown",
            backup_stream_url=direct,
        )

    def status(self, camera_id: str, public_host: str) -> CameraStatus:
        view = self.view(camera_id, public_host)
        runtime = self._state.get(camera_id)
        return CameraStatus(
            camera_id=view.id,
            enabled=view.enabled,
            network_reachable=view.network_reachable,
            connection_status=view.connection_status,  # type: ignore[arg-type]
            last_success_at=view.last_success_at,
            stream_phase=view.stream_phase,
            last_error=runtime.get("last_error"),
        )
