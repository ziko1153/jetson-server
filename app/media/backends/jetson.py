"""Jetson media backend.

NVIDIA elements are selected only when gst-inspect has already confirmed them.
Otherwise the same FFmpeg pipeline used on macOS is used, and the capability
report says so.
"""

from __future__ import annotations

from app.media.backends.base import BackendCapabilities
from app.media.backends.software import SoftwareBackend
from app.media.mosaic.compositor import gstreamer_mosaic_command
from app.schemas.mosaic import MosaicOutput, MosaicTile


class JetsonBackend(SoftwareBackend):
    def __init__(
        self,
        ffmpeg: str | None,
        gstreamer: str | None,
        nvidia_plugins: dict[str, bool],
        hardware_encoder_expected: bool | None,
    ) -> None:
        super().__init__("jetson", ffmpeg, notes=[])
        self._gstreamer = gstreamer
        self._plugins = nvidia_plugins
        self._expected = hardware_encoder_expected

    @property
    def nvidia_ready(self) -> bool:
        required = ("nvv4l2decoder", "nvv4l2h264enc", "nvvidconv")
        return bool(self._gstreamer) and all(self._plugins.get(name) for name in required)

    def capabilities(self) -> BackendCapabilities:
        notes = [
            "Jetson pipelines are chosen from detected plugins, not from the CPU architecture.",
            "The NVIDIA mosaic pipeline still needs to be verified on the target Orin NX.",
        ]
        if self._expected is False:
            notes.append("This board does not advertise an Orin NX hardware encoder.")
        if not self.nvidia_ready:
            notes.append("NVIDIA mosaic elements are unavailable. Mosaic encoding falls back to software FFmpeg.")
        return BackendCapabilities(
            name="jetson",
            acceleration="nvidia" if self.nvidia_ready else "software",
            mosaic_encoder="nvv4l2h264enc" if self.nvidia_ready else ("libx264" if self._ffmpeg else "unavailable"),
            ffmpeg=self._ffmpeg,
            gstreamer=self._gstreamer,
            nvidia_encoder=self.nvidia_ready,
            notes=notes,
        )

    def mosaic_command(self, sources, tiles: list[MosaicTile], output: MosaicOutput, publish_url: str) -> list[str]:
        if self.nvidia_ready and self._gstreamer:
            return gstreamer_mosaic_command(self._gstreamer, sources, tiles, output, publish_url)
        return super().mosaic_command(sources, tiles, output, publish_url)
