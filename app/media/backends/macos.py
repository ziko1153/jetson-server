"""macOS software media backend."""

from __future__ import annotations

from app.media.backends.software import SoftwareBackend


class MacOSBackend(SoftwareBackend):
    def __init__(self, ffmpeg: str | None) -> None:
        super().__init__(
            "macos",
            ffmpeg,
            notes=["macOS uses a software FFmpeg pipeline. NVIDIA encoding is not available on this machine."],
        )
