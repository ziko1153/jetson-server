"""Media backend contract."""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.mosaic import MosaicOutput, MosaicTile


@dataclass(frozen=True)
class BackendCapabilities:
    name: str
    acceleration: str
    mosaic_encoder: str
    ffmpeg: str | None
    gstreamer: str | None
    nvidia_encoder: bool
    notes: list[str]


class MediaBackend:
    def capabilities(self) -> BackendCapabilities:
        raise NotImplementedError

    def mosaic_command(
        self,
        sources: list[str],
        tiles: list[MosaicTile],
        output: MosaicOutput,
        publish_url: str,
    ) -> list[str]:
        raise NotImplementedError

    def transcode_command(
        self,
        source_url: str,
        publish_url: str,
        *,
        width: int,
        height: int,
        fps: int,
        bitrate_kbps: int,
    ) -> list[str]:
        raise NotImplementedError
