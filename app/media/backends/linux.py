"""Generic Linux software media backend."""

from __future__ import annotations

from app.media.backends.software import SoftwareBackend


class LinuxBackend(SoftwareBackend):
    def __init__(self, ffmpeg: str | None) -> None:
        super().__init__(
            "linux",
            ffmpeg,
            notes=["This Linux host is not a Jetson. Video processing uses software FFmpeg."],
        )
