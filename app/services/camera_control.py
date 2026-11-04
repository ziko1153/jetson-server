"""Camera encoder settings and PTZ over ONVIF.

The camera's ONVIF address comes from the registry. The service learns the PTZ
profile once per camera and keeps it, so each move is a single request. A move
always carries a short timeout, so the camera stops by itself if the operator's
link drops before the stop arrives.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from app.cameras.drivers.onvif import OnvifClient, OnvifError
from app.cameras.drivers.onvif_control import EncoderChange, Login, OnvifControl, StreamEncoder
from app.core.exceptions import UnavailableError, UnsupportedError, ValidationFailed
from app.core.logging import get_logger
from app.schemas.camera import CameraRecord
from app.schemas.camera_control import (
    CameraEncodersView,
    EncoderOptionsView,
    EncoderUpdate,
    PtzMove,
    PtzView,
    Resolution,
    StreamEncoderView,
)
from app.services.audit_service import AuditService
from app.services.camera_registry import CameraRegistry
from app.services.secrets import SecretStore

log = get_logger(__name__)

PTZ_TIMEOUT_SECONDS = 2.0
ENCODER_TIMEOUT_SECONDS = 6.0


@dataclass
class _Ptz:
    profile_token: str
    view: PtzView


class CameraControlService:
    def __init__(
        self,
        registry: CameraRegistry,
        secrets: SecretStore,
        audit: AuditService,
        *,
        encoder_client: OnvifClient | None = None,
        ptz_client: OnvifClient | None = None,
    ) -> None:
        self._registry = registry
        self._secrets = secrets
        self._audit = audit
        self._encoders = OnvifControl(encoder_client or OnvifClient(timeout=ENCODER_TIMEOUT_SECONDS))
        self._motion = OnvifControl(ptz_client or OnvifClient(timeout=PTZ_TIMEOUT_SECONDS))
        self._lock = threading.Lock()
        self._ptz: dict[str, _Ptz] = {}

    def encoders(self, camera_id: str) -> CameraEncodersView:
        camera = self._registry.get(camera_id)
        streams = self._call(camera, lambda url, login: self._encoders.streams(url, login))
        return CameraEncodersView(camera_id=camera.id, streams=[_stream_view(camera, item) for item in streams])

    def set_encoder(self, camera_id: str, encoder_token: str, update: EncoderUpdate) -> CameraEncodersView:
        camera = self._registry.get(camera_id)
        before = self.encoders(camera.id)
        current = next((item for item in before.streams if item.encoder_token == encoder_token), None)
        if current is None:
            raise ValidationFailed(
                f"Camera {camera.id} has no encoder {encoder_token}.",
                details={"encoders": [item.encoder_token for item in before.streams]},
            )
        _check_against_options(current, update)
        change = EncoderChange(**update.model_dump())
        requested = {"encoder_token": encoder_token, **update.model_dump(exclude_none=True)}
        try:
            self._call(camera, lambda url, login: self._encoders.set_encoder(url, login, encoder_token, change))
        except (UnsupportedError, UnavailableError) as exc:
            self._audit.record(
                camera_id=camera.id,
                success=False,
                requested=requested,
                previous=current.model_dump(mode="json"),
                confirmed=None,
                error=exc.message,
            )
            raise
        after = self.encoders(camera.id)
        confirmed = next((item for item in after.streams if item.encoder_token == encoder_token), None)
        self._audit.record(
            camera_id=camera.id,
            success=True,
            requested=requested,
            previous=current.model_dump(mode="json"),
            confirmed=confirmed.model_dump(mode="json") if confirmed else None,
            error=None,
        )
        return after

    def ptz(self, camera_id: str) -> PtzView:
        camera = self._registry.get(camera_id)
        try:
            return self._ptz_for(camera).view
        except (UnsupportedError, UnavailableError) as exc:
            return PtzView(camera_id=camera.id, supported=False, note=exc.message)

    def move(self, camera_id: str, move: PtzMove) -> PtzView:
        camera = self._registry.get(camera_id)
        ptz = self._ptz_for(camera)
        self._call(
            camera,
            lambda url, login: self._motion.continuous_move(
                url,
                login,
                ptz.profile_token,
                pan=move.pan if ptz.view.pan_tilt else 0,
                tilt=move.tilt if ptz.view.pan_tilt else 0,
                zoom=move.zoom if ptz.view.zoom else 0,
                timeout_seconds=move.timeout_seconds,
            ),
            forget_on_error=True,
        )
        return ptz.view

    def stop(self, camera_id: str) -> PtzView:
        camera = self._registry.get(camera_id)
        ptz = self._ptz_for(camera)
        self._call(camera, lambda url, login: self._motion.stop(url, login, ptz.profile_token), forget_on_error=True)
        return ptz.view

    def home(self, camera_id: str) -> PtzView:
        camera = self._registry.get(camera_id)
        ptz = self._ptz_for(camera)
        if not ptz.view.home:
            raise UnsupportedError(f"Camera {camera.id} does not report a home position.")
        self._call(camera, lambda url, login: self._motion.home(url, login, ptz.profile_token), forget_on_error=True)
        return ptz.view

    def _ptz_for(self, camera: CameraRecord) -> _Ptz:
        with self._lock:
            known = self._ptz.get(camera.id)
        if known is not None:
            return known

        def learn(url: str, login: Login) -> _Ptz:
            tokens = self._encoders.profile_tokens(url, login)
            if not tokens:
                raise OnvifError("The camera returned no media profile for PTZ.")
            node = self._encoders.ptz_node(url, login, tokens[0])
            supported = node.pan_tilt or node.zoom
            view = PtzView(camera_id=camera.id, supported=supported, pan_tilt=node.pan_tilt, zoom=node.zoom, home=node.home)
            return _Ptz(profile_token=node.profile_token, view=view)

        learned = self._call(camera, learn)
        if not learned.view.supported:
            raise UnsupportedError(f"Camera {camera.id} does not report pan, tilt, or zoom.")
        with self._lock:
            self._ptz[camera.id] = learned
        return learned

    def _call(self, camera: CameraRecord, action, *, forget_on_error: bool = False):
        if not camera.enabled:
            raise UnavailableError(f"Camera {camera.id} is disabled.", code="camera_disabled")
        credentials = self._secrets.camera(camera.credentials_ref or camera.id)
        login = Login(credentials.username, credentials.password)
        url = f"http://{camera.connection.host}:{camera.connection.onvif_port}{camera.connection.onvif_path}"
        try:
            return action(url, login)
        except OnvifError as exc:
            if forget_on_error:
                with self._lock:
                    self._ptz.pop(camera.id, None)
            log.info("onvif request failed camera_id=%s error=%s", camera.id, exc)
            if "request failed" in str(exc):
                raise UnavailableError(
                    f"Camera {camera.id} did not answer ONVIF.", code="camera_unreachable", details={"reason": str(exc)}
                ) from exc
            raise UnsupportedError(f"Camera {camera.id} rejected the ONVIF request.", details={"reason": str(exc)}) from exc


def _stream_view(camera: CameraRecord, stream: StreamEncoder) -> StreamEncoderView:
    connection = camera.connection
    gateway = None
    if stream.path and stream.path == connection.path:
        gateway = "main"
    elif stream.path and connection.sub_path and stream.path == connection.sub_path:
        gateway = "sub"
    name = stream.profile_name.lower()
    role = "main" if "main" in name else "sub" if "sub" in name else "other"
    return StreamEncoderView(
        profile_token=stream.profile_token,
        profile_name=stream.profile_name,
        encoder_token=stream.encoder_token,
        role=role,  # type: ignore[arg-type]
        path=stream.path,
        gateway_stream=gateway,  # type: ignore[arg-type]
        codec=stream.codec,
        width=stream.width,
        height=stream.height,
        fps=stream.fps,
        bitrate_kbps=stream.bitrate_kbps,
        gov_length=stream.gov_length,
        encoding_profile=stream.encoding_profile,
        constant_bitrate=stream.constant_bitrate,
        options=[
            EncoderOptionsView(
                codec=item.codec,
                resolutions=[Resolution(width=width, height=height) for width, height in item.resolutions],
                frame_rates=item.frame_rates,
                bitrate_kbps_min=item.bitrate_min,
                bitrate_kbps_max=item.bitrate_max,
                gov_length_min=item.gov_min,
                gov_length_max=item.gov_max,
                profiles=item.profiles,
            )
            for item in stream.options
        ],
    )


def _check_against_options(current: StreamEncoderView, update: EncoderUpdate) -> None:
    """Rejects values the camera did not list, so a bad request never reaches the encoder."""
    if not current.options:
        return
    codec = (update.codec or current.codec).upper()
    option = next((item for item in current.options if item.codec == codec), None)
    if option is None:
        raise ValidationFailed(
            f"The camera does not offer {codec} on this stream.",
            details={"codecs": [item.codec for item in current.options]},
        )
    width = update.width or current.width
    height = update.height or current.height
    if option.resolutions and not any(item.width == width and item.height == height for item in option.resolutions):
        raise ValidationFailed(
            f"The camera does not offer {width}x{height} for {codec}.",
            details={"resolutions": [item.model_dump() for item in option.resolutions]},
        )
    fps = update.fps or current.fps
    if option.frame_rates and fps not in option.frame_rates:
        raise ValidationFailed(f"The camera does not offer {fps} fps.", details={"frame_rates": option.frame_rates})
    bitrate = update.bitrate_kbps or current.bitrate_kbps
    low, high = option.bitrate_kbps_min, option.bitrate_kbps_max
    if (low is not None and bitrate < low) or (high is not None and bitrate > high):
        raise ValidationFailed(f"Bitrate must be between {low} and {high} kbps.")
    gov = update.gov_length
    if gov is not None:
        gov_low, gov_high = option.gov_length_min, option.gov_length_max
        if (gov_low is not None and gov < gov_low) or (gov_high is not None and gov > gov_high):
            raise ValidationFailed(f"Keyframe interval must be between {gov_low} and {gov_high} frames.")
