"""GStreamer mosaic command used only when NVIDIA elements were detected.

Each camera is decoded into its own inter-video channel, and the compositor
reads only those channels and the NO SIGNAL tiles. Every compositor input is
therefore live from the first frame, so a camera that is slow to connect or
stops sending cannot hold back the mosaic. parsebin selects the RTP
depayloader and parser, so H.264 and H.265 cameras use the same pipeline.
"""

from __future__ import annotations

from urllib.parse import unquote, urlsplit, urlunsplit

from app.media.mosaic.layouts import drawn_tiles
from app.media.mosaic.sources import NO_SIGNAL_TEXT
from app.schemas.mosaic import MosaicOutput, MosaicTile

CAMERA_TIMEOUT_NS = 1_000_000_000
# The PoE cameras often send nothing to GStreamer over interleaved TCP.
CAMERA_PROTOCOLS = "udp+tcp"
# The cameras send 704x576 with non-square pixels. The compositor keeps that shape
# and would draw each picture narrower than its tile.
SQUARE_PIXELS = "video/x-raw,pixel-aspect-ratio=(fraction)1/1"


def gstreamer_mosaic_command(
    gst_launch: str,
    sources: list[str | None],
    tiles: list[MosaicTile],
    output: MosaicOutput,
    publish_url: str,
) -> list[str]:
    ordered = drawn_tiles(tiles)
    command = [gst_launch, "-e"]
    for index, (source, tile) in enumerate(zip(sources, ordered, strict=True)):
        if source:
            channel = f"mosaic-tile-{index}"
            command.extend([*_camera_branch(source, tile, channel), *_channel_tile(channel, tile, output.fps)])
        else:
            command.extend(_no_signal_tile(tile, output.fps))
        command.extend(["!", "queue", "!", "comp."])
    command.extend(["compositor", "name=comp", "background=black"])
    for index, tile in enumerate(ordered):
        command.append(f"sink_{index}::xpos={tile.x}")
        command.append(f"sink_{index}::ypos={tile.y}")
        command.append(f"sink_{index}::width={tile.width}")
        command.append(f"sink_{index}::height={tile.height}")
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
            f"idrinterval={interval}",
            "insert-sps-pps=true",
            "maxperf-enable=true",
            "!",
            "h264parse",
            "!",
            "rtspclientsink",
            f"location={publish_url}",
            "protocols=tcp",
        ]
    )
    return command


def _camera_branch(source: str, tile: MosaicTile, channel: str) -> list[str]:
    return [
        "rtspsrc",
        *_rtsp_source(source),
        "latency=80",
        f"protocols={CAMERA_PROTOCOLS}",
        "!",
        "parsebin",
        "!",
        "nvv4l2decoder",
        "!",
        "nvvidconv",
        "!",
        _tile_caps(tile),
        "!",
        "capssetter",
        f"caps={SQUARE_PIXELS}",
        "!",
        "intervideosink",
        f"channel={channel}",
        "sync=false",
    ]


def _rtsp_source(source: str) -> list[str]:
    """The login goes in rtspsrc properties, so gst-launch progress lines in the log never carry it."""
    parts = urlsplit(source)
    if parts.username is None:
        return [f"location={source}"]
    host = parts.hostname or ""
    netloc = f"{host}:{parts.port}" if parts.port else host
    location = urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    return [f"location={location}", f"user-id={unquote(parts.username)}", f"user-pw={unquote(parts.password or '')}"]


def _channel_tile(channel: str, tile: MosaicTile, fps: int) -> list[str]:
    return ["intervideosrc", f"channel={channel}", f"timeout={CAMERA_TIMEOUT_NS}", "!", _tile_caps(tile, fps)]


def _no_signal_tile(tile: MosaicTile, fps: int) -> list[str]:
    return [
        "videotestsrc",
        "pattern=black",
        "is-live=true",
        "!",
        _tile_caps(tile, fps),
        "!",
        "textoverlay",
        f"text={NO_SIGNAL_TEXT}",
        "valignment=center",
        "halignment=center",
        f"font-desc=Sans Bold {max(10, tile.height // 13)}",
    ]


def _tile_caps(tile: MosaicTile, fps: int | None = None) -> str:
    caps = f"video/x-raw,format=I420,width={tile.width},height={tile.height}"
    return f"{caps},framerate={fps}/1" if fps else caps
