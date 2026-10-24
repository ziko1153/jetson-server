"""Read-only RTSP driver.

Stream probing can describe the active program. It cannot list every encoder
option, and it never changes the camera.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone

from app.cameras.drivers.base import DriverResult
from app.core.exceptions import UnsupportedError
from app.infrastructure.networking.urls import source_rtsp_url
from app.schemas.camera import CameraRecord, CapabilityReport, PhysicalSettings, SettingsUpdate


class ReadonlyRtspDriver:
    name = "readonly_rtsp"

    def __init__(self, ffprobe_bin: str | None, timeout: float = 8) -> None:
        self._ffprobe = ffprobe_bin
        self._timeout = timeout

    def probe(self, camera: CameraRecord, username: str, password: str) -> DriverResult:
        if not self._ffprobe:
            report = CapabilityReport(
                camera_id=camera.id,
                source="unknown",
                limitations=["ffprobe is not installed, so the active RTSP stream was not inspected."],
            )
            return DriverResult(capabilities=report, settings=PhysicalSettings(source="unknown"))
        url = source_rtsp_url(camera, username, password)
        completed = subprocess.run(
            [
                self._ffprobe,
                "-v",
                "error",
                "-rw_timeout",
                str(int(self._timeout * 1_000_000)),
                "-print_format",
                "json",
                "-show_streams",
                "-select_streams",
                "v:0",
                url,
            ],
            capture_output=True,
            text=True,
            timeout=self._timeout + 2,
            check=False,
        )
        if completed.returncode != 0:
            report = CapabilityReport(
                camera_id=camera.id,
                source="rtsp_probe",
                probed_at=_now(),
                configuration_supported=False,
                limitations=[
                    "The RTSP probe did not receive a video stream.",
                    "Probing does not reveal encoder options that are not present on the active stream.",
                ],
            )
            return DriverResult(capabilities=report, settings=PhysicalSettings(source="rtsp_probe"))
        payload = json.loads(completed.stdout or "{}")
        streams = payload.get("streams") or []
        video = streams[0] if streams else {}
        codec = video.get("codec_name")
        width = video.get("width")
        height = video.get("height")
        fps = _frame_rate(video.get("avg_frame_rate"))
        bitrate = _bitrate(video.get("bit_rate"))
        report = CapabilityReport(
            camera_id=camera.id,
            source="rtsp_probe",
            probed_at=_now(),
            codecs=[codec] if codec else None,
            resolutions=None,
            frame_rates=[fps] if fps is not None else None,
            configuration_supported=False,
            limitations=[
                "RTSP probing reports the active stream only.",
                "Resolution, frame rate, and codec lists are not inferred beyond that stream.",
                "Physical encoder settings cannot be changed through this driver.",
            ],
            detected_codec=codec,
            detected_width=width,
            detected_height=height,
            detected_fps=fps,
            detected_bitrate_kbps=bitrate,
        )
        settings = PhysicalSettings(
            supported=False,
            source="rtsp_probe",
            codec=codec,
            width=width,
            height=height,
            fps=fps,
            bitrate_kbps=int(bitrate) if bitrate is not None else None,
        )
        return DriverResult(capabilities=report, settings=settings)

    def apply(
        self,
        camera: CameraRecord,
        username: str,
        password: str,
        update: SettingsUpdate,
    ) -> PhysicalSettings:
        raise UnsupportedError(
            "This camera driver can read the active RTSP stream and cannot change the physical encoder.",
            details={"camera_id": camera.id, "driver": self.name},
        )


def _frame_rate(value: object) -> float | None:
    if not isinstance(value, str) or "/" not in value:
        return None
    numerator, denominator = value.split("/", 1)
    try:
        left = float(numerator)
        right = float(denominator)
    except ValueError:
        return None
    if right == 0:
        return None
    rate = left / right
    if rate <= 0:
        return None
    return round(rate, 3)


def _bitrate(value: object) -> float | None:
    if value in (None, "N/A", ""):
        return None
    try:
        bits = float(value)
    except (TypeError, ValueError):
        return None
    if bits <= 0:
        return None
    return round(bits / 1000, 3)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
