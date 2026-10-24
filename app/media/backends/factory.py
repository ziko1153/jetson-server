"""Choose a media backend from detected hardware and the config override."""

from __future__ import annotations

from app.core.environment import EnvironmentReport
from app.core.exceptions import ConfigurationError
from app.media.backends.base import MediaBackend
from app.media.backends.jetson import JetsonBackend
from app.media.backends.linux import LinuxBackend
from app.media.backends.macos import MacOSBackend


def select_backend(report: EnvironmentReport, preference: str) -> MediaBackend:
    hardware = report.hardware if preference == "auto" else preference
    if hardware == "macos":
        return MacOSBackend(report.ffmpeg)
    if hardware == "linux":
        return LinuxBackend(report.ffmpeg)
    if hardware == "jetson":
        return JetsonBackend(
            report.ffmpeg,
            report.gstreamer,
            report.nvidia_plugins,
            report.hardware_encoder_expected,
        )
    raise ConfigurationError(f"No media backend is available for hardware '{hardware}'.")
