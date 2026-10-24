"""Software FFmpeg pipelines shared by macOS and generic Linux."""

from __future__ import annotations

from app.media.backends.base import BackendCapabilities, MediaBackend
from app.media.mosaic.pipeline import ffmpeg_mosaic_command, ffmpeg_transcode_command
from app.schemas.mosaic import MosaicOutput, MosaicTile


class SoftwareBackend(MediaBackend):
    def __init__(self, name: str, ffmpeg: str | None, notes: list[str] | None = None) -> None:
        self._name = name
        self._ffmpeg = ffmpeg
        self._notes = notes or []

    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            name=self._name,
            acceleration="software",
            mosaic_encoder="libx264" if self._ffmpeg else "unavailable",
            ffmpeg=self._ffmpeg,
            gstreamer=None,
            nvidia_encoder=False,
            notes=self._notes,
        )

    def mosaic_command(self, sources, tiles: list[MosaicTile], output: MosaicOutput, publish_url: str) -> list[str]:
        self._require_ffmpeg()
        return ffmpeg_mosaic_command(self._ffmpeg or "", sources, tiles, output, publish_url)

    def transcode_command(self, source_url, publish_url, *, width, height, fps, bitrate_kbps) -> list[str]:
        self._require_ffmpeg()
        return ffmpeg_transcode_command(
            self._ffmpeg or "",
            source_url,
            publish_url,
            width=width,
            height=height,
            fps=fps,
            bitrate_kbps=bitrate_kbps,
        )

    def _require_ffmpeg(self) -> None:
        if not self._ffmpeg:
            from app.core.exceptions import UnavailableError

            raise UnavailableError("FFmpeg is not installed.", code="ffmpeg_missing")
