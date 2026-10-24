"""GStreamer mosaic command used only when NVIDIA elements were detected."""

from __future__ import annotations

from app.schemas.mosaic import MosaicOutput, MosaicTile


def gstreamer_mosaic_command(
    gst_launch: str,
    sources: list[str],
    tiles: list[MosaicTile],
    output: MosaicOutput,
    publish_url: str,
) -> list[str]:
    ordered = [tile for tile in sorted(tiles, key=lambda item: item.z) if tile.visible]
    command = [gst_launch, "-e"]
    for source, tile in zip(sources, ordered, strict=True):
        command.extend(
            [
                "rtspsrc",
                f"location={source}",
                "latency=80",
                "protocols=tcp",
                "!",
                "rtph264depay",
                "!",
                "h264parse",
                "!",
                "nvv4l2decoder",
                "!",
                "nvvidconv",
                "!",
                f"video/x-raw,width={tile.width},height={tile.height}",
                "!",
                "queue",
                "!",
                "comp.",
            ]
        )
    command.append("compositor")
    command.append("name=comp")
    for index, tile in enumerate(ordered):
        command.append(f"sink_{index}::xpos={tile.x}")
        command.append(f"sink_{index}::ypos={tile.y}")
    interval = max(output.fps, 1)
    bitrate = output.bitrate_kbps * 1000
    command.extend(
        [
            "!",
            f"video/x-raw,width={output.width},height={output.height},framerate={output.fps}/1",
            "!",
            "nvvidconv",
            "!",
            "video/x-raw(memory:NVMM),format=NV12",
            "!",
            "nvv4l2h264enc",
            f"bitrate={bitrate}",
            f"iframeinterval={interval}",
            "insert-sps-pps=true",
            "!",
            "h264parse",
            "!",
            "rtspclientsink",
            f"location={publish_url}",
            "protocols=tcp",
        ]
    )
    return command
