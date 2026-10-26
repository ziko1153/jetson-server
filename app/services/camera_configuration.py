"""Physical camera configuration, kept apart from gateway output settings."""

from __future__ import annotations

from app.cameras.drivers.onvif import OnvifClient, OnvifError
from app.cameras.drivers.readonly_rtsp import ReadonlyRtspDriver
from app.cameras.drivers.vendor import VendorDriver
from app.core.exceptions import UnsupportedError, ValidationFailed
from app.core.logging import get_logger
from app.schemas.camera import CameraRecord, CapabilityReport, GatewayOverrides, SettingsResponse, SettingsUpdate
from app.services.camera_registry import CameraRegistry
from app.services.camera_state import CameraStateStore
from app.services.secrets import SecretStore

log = get_logger(__name__)

PHYSICAL_NOTE = (
    "Physical settings are sent to the camera. Gateway profile and tile settings "
    "do not change the camera encoder."
)


class CameraConfigurationService:
    def __init__(
        self,
        registry: CameraRegistry,
        state: CameraStateStore,
        secrets: SecretStore,
        audit,
        ffprobe_bin: str | None,
    ) -> None:
        self._registry = registry
        self._state = state
        self._secrets = secrets
        self._audit = audit
        self._onvif = OnvifClient()
        self._readonly = ReadonlyRtspDriver(ffprobe_bin)
        self._vendor = VendorDriver()

    def capabilities(self, camera_id: str) -> CapabilityReport:
        self._registry.get(camera_id)
        return self._state.capabilities(camera_id)

    def settings(self, camera_id: str) -> SettingsResponse:
        camera = self._registry.get(camera_id)
        physical = self._state.physical_settings(camera_id)
        if physical is None:
            physical_payload = self._state.capabilities(camera_id)
            from app.schemas.camera import PhysicalSettings

            physical = PhysicalSettings(
                supported=physical_payload.configuration_supported,
                source=physical_payload.source,
                codec=physical_payload.detected_codec,
                width=physical_payload.detected_width,
                height=physical_payload.detected_height,
                fps=physical_payload.detected_fps,
                bitrate_kbps=(
                    int(physical_payload.detected_bitrate_kbps)
                    if physical_payload.detected_bitrate_kbps is not None
                    else None
                ),
            )
        return SettingsResponse(
            camera_id=camera.id,
            physical=physical,
            gateway_profile=camera.configuration.profile,
            gateway_overrides=camera.configuration.gateway_overrides,
            note=PHYSICAL_NOTE,
        )

    def probe(self, camera_id: str) -> CapabilityReport:
        camera = self._registry.get(camera_id)
        credentials = self._secrets.camera(camera.credentials_ref or camera.id)
        driver_name = camera.configuration.driver
        try:
            if driver_name == "vendor":
                result = self._vendor.probe(camera, credentials.username, credentials.password)
            elif driver_name == "readonly_rtsp":
                result = self._readonly.probe(camera, credentials.username, credentials.password)
            elif driver_name == "onvif":
                result = self._onvif.probe(camera, credentials.username, credentials.password)
            else:
                result = self._probe_auto(camera, credentials.username, credentials.password)
        except (OnvifError, UnsupportedError, OSError, TimeoutError) as exc:
            log.info("camera probe failed camera_id=%s error=%s", camera.id, exc.__class__.__name__)
            if driver_name == "auto":
                result = self._readonly.probe(camera, credentials.username, credentials.password)
            else:
                raise UnsupportedError(str(exc) or "Camera probe failed.") from exc
        self._state.update(
            camera.id,
            capabilities=result.capabilities.model_dump(mode="json"),
            physical_settings=result.settings.model_dump(mode="json"),
        )
        return result.capabilities

    def update_settings(self, camera_id: str, update: SettingsUpdate) -> SettingsResponse:
        camera = self._registry.get(camera_id)
        previous = self.settings(camera_id).model_dump(mode="json")
        requested = update.model_dump(mode="json")
        try:
            if update.target == "gateway" or update.allow_gateway_processing:
                response = self._apply_gateway(camera, update)
                self._audit.record(
                    camera_id=camera.id,
                    success=True,
                    requested=requested,
                    previous=previous,
                    confirmed=response.model_dump(mode="json"),
                    error=None,
                )
                return response
            response = self._apply_physical(camera, update)
        except UnsupportedError as exc:
            self._audit.record(
                camera_id=camera.id,
                success=False,
                requested=requested,
                previous=previous,
                confirmed=None,
                error=exc.message,
            )
            raise
        self._audit.record(
            camera_id=camera.id,
            success=True,
            requested=requested,
            previous=previous,
            confirmed=response.model_dump(mode="json"),
            error=None,
        )
        return response

    def _apply_physical(self, camera: CameraRecord, update: SettingsUpdate) -> SettingsResponse:
        credentials = self._secrets.camera(camera.credentials_ref or camera.id)
        driver_name = camera.configuration.driver
        try:
            if driver_name == "vendor":
                physical = self._vendor.apply(camera, credentials.username, credentials.password, update)
            elif driver_name in {"auto", "onvif"}:
                physical = self._onvif.apply(camera, credentials.username, credentials.password, update)
            else:
                physical = self._readonly.apply(camera, credentials.username, credentials.password, update)
        except OnvifError as exc:
            raise UnsupportedError(
                "The camera did not accept the ONVIF configuration request.",
                details={"reason": str(exc)},
            ) from exc
        self._state.update(camera.id, physical_settings=physical.model_dump(mode="json"))
        response = self.settings(camera.id)
        response.applied_to = "physical"
        return response

    def _apply_gateway(self, camera: CameraRecord, update: SettingsUpdate) -> SettingsResponse:
        if update.target == "physical" and not update.allow_gateway_processing:
            raise ValidationFailed("Gateway processing was not requested.")
        overrides = GatewayOverrides(
            width=update.width,
            height=update.height,
            fps=update.fps,
            bitrate_kbps=update.bitrate_kbps,
            codec=update.codec,
        )
        profile = camera.configuration.profile
        if update.stream_profile in {"low", "medium", "high", "custom"}:
            profile = update.stream_profile
        configuration = camera.configuration.model_copy(update={"profile": profile, "gateway_overrides": overrides})
        self._registry.replace(camera.model_copy(update={"configuration": configuration}))
        response = self.settings(camera.id)
        response.applied_to = "gateway"
        response.note = (
            "Gateway overrides were stored. Individual camera streams stay in passthrough "
            "until a client starts that stream with mode transcode. The physical camera was not changed."
        )
        return response

    def _probe_auto(self, camera: CameraRecord, username: str, password: str):
        try:
            return self._onvif.probe(camera, username, password)
        except (OnvifError, UnsupportedError, OSError, TimeoutError):
            return self._readonly.probe(camera, username, password)
