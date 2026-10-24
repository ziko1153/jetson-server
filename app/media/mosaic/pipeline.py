"""FFmpeg mosaic and transcode argument builders."""

from __future__ import annotations

from app.schemas.mosaic import MosaicOutput, MosaicTile


def ffmpeg_mosaic_command(
    ffmpeg: str,
    sources: list[str],
    tiles: list[MosaicTile],
    output: MosaicOutput,
    publish_url: str,
) -> list[str]:
    ordered = [tile for tile in sorted(tiles, key=lambda item: item.z) if tile.visible]
    command = [ffmpeg, "-hide_banner", "-loglevel", "warning"]
    command.extend(["-f", "lavfi", "-i", f"color=c=black:s={output.width}x{output.height}:r={output.fps}"])
    for source in sources:
        command.extend(
            [
                "-rtsp_transport",
                "tcp",
                "-fflags",
                "nobuffer",
                "-flags",
                "low_delay",
                "-probesize",
                "32",
                "-analyzeduration",
                "1",
                "-i",
                source,
            ]
        )
    filters: list[str] = []
    current = "[0:v]"
    for index, tile in enumerate(ordered):
        label = f"t{index}"
        filters.append(
            f"[{index + 1}:v]fps={output.fps}:round=near,setpts=PTS-STARTPTS,{_scale(tile)}[{label}]"
        )
        next_label = "vout" if index == len(ordered) - 1 else f"b{index}"
        filters.append(f"{current}[{label}]overlay={tile.x}:{tile.y}:eof_action=pass[{next_label}]")
        current = f"[{next_label}]"
    gop = max(output.fps, output.fps * 2)
    buffer = max(output.bitrate_kbps // 2, 100)
    command.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[vout]",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-tune",
            "zerolatency",
            "-pix_fmt",
            "yuv420p",
            "-b:v",
            f"{output.bitrate_kbps}k",
            "-maxrate",
            f"{output.bitrate_kbps}k",
            "-bufsize",
            f"{buffer}k",
            "-r",
            str(output.fps),
            "-g",
            str(gop),
            "-f",
            "rtsp",
            "-rtsp_transport",
            "tcp",
            publish_url,
        ]
    )
    return command


def ffmpeg_transcode_command(
    ffmpeg: str,
    source_url: str,
    publish_url: str,
    *,
    width: int,
    height: int,
    fps: int,
    bitrate_kbps: int,
) -> list[str]:
    return [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "warning",
        "-rtsp_transport",
        "tcp",
        "-i",
        source_url,
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-tune",
        "zerolatency",
        "-pix_fmt",
        "yuv420p",
        "-vf",
        f"scale={width}:{height}",
        "-r",
        str(fps),
        "-b:v",
        f"{bitrate_kbps}k",
        "-f",
        "rtsp",
        "-rtsp_transport",
        "tcp",
        publish_url,
    ]


def _scale(tile: MosaicTile) -> str:
    size = f"{tile.width}:{tile.height}"
    if tile.scaling == "stretch":
        return f"scale={size},setsar=1"
    if tile.scaling == "fill":
        return f"scale={size}:force_original_aspect_ratio=increase,crop={size},setsar=1"
    return (
        f"scale={size}:force_original_aspect_ratio=decrease,"
        f"pad={size}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1"
    )
