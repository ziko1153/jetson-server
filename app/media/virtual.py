"""Synthetic local RTSP cameras. The default command stays a test pattern."""

from __future__ import annotations

import shutil

PATTERNS = {
    "testsrc": "testsrc=size={width}x{height}:rate={fps}",
    "testsrc2": "testsrc2=size={width}x{height}:rate={fps}",
    "smptebars": "smptebars=size={width}x{height}:rate={fps}",
    "smptehdbars": "smptehdbars=size={width}x{height}:rate={fps}",
    "rgbtestsrc": "rgbtestsrc=size={width}x{height}:rate={fps}",
    "yuvtestsrc": "yuvtestsrc=size={width}x{height}:rate={fps}",
    "mandelbrot": "mandelbrot=size={width}x{height}:rate={fps}:maxiter=64",
}


def virtual_camera_command(
    publish_url: str,
    *,
    width: int = 640,
    height: int = 360,
    fps: int = 10,
    ffmpeg: str | None = None,
    pattern: str = "testsrc",
    hue_speed: int = 0,
    media_file: str | None = None,
    label_image: str | None = None,
) -> list[str]:
    binary = ffmpeg or shutil.which("ffmpeg")
    if binary is None:
        raise RuntimeError("ffmpeg is required to generate a virtual camera")
    if width % 2 or height % 2 or width < 2 or height < 2:
        raise ValueError("virtual camera dimensions must be positive even numbers")
    if fps < 1 or fps > 60:
        raise ValueError("virtual camera frame rate must be from 1 to 60")
    if media_file:
        return _file_command(binary, publish_url, media_file, width, height, fps, label_image)
    if pattern not in PATTERNS:
        raise ValueError(f"unsupported test pattern {pattern}")
    if label_image or hue_speed or pattern != "testsrc":
        return _pattern_command(binary, publish_url, pattern, width, height, fps, hue_speed, label_image)
    return [
        binary,
        "-hide_banner",
        "-loglevel",
        "error",
        "-re",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=size={width}x{height}:rate={fps},format=yuv420p",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-tune",
        "zerolatency",
        "-pix_fmt",
        "yuv420p",
        "-g",
        str(max(fps, 1) * 2),
        "-f",
        "rtsp",
        "-rtsp_transport",
        "tcp",
        publish_url,
    ]


def _pattern_command(
    binary: str,
    publish_url: str,
    pattern: str,
    width: int,
    height: int,
    fps: int,
    hue_speed: int,
    label_image: str | None,
) -> list[str]:
    graph = PATTERNS[pattern].format(width=width, height=height, fps=fps)
    if hue_speed:
        graph += f",hue=h=t*{int(hue_speed)}"
    graph += ",format=yuv420p"
    command = [binary, "-hide_banner", "-loglevel", "error", "-re", "-f", "lavfi", "-i", graph]
    if label_image:
        command.extend(["-loop", "1", "-i", label_image, "-filter_complex", "[0:v][1:v]overlay=16:16:eof_action=repeat"])
    command.extend(_publish_args(fps, publish_url))
    return command


def _file_command(
    binary: str,
    publish_url: str,
    media_file: str,
    width: int,
    height: int,
    fps: int,
    label_image: str | None,
) -> list[str]:
    command = [binary, "-hide_banner", "-loglevel", "error", "-re", "-stream_loop", "-1", "-i", media_file]
    scale = (
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1"
    )
    if label_image:
        command.extend(["-loop", "1", "-i", label_image])
        scale += "[bg];[bg][1:v]overlay=16:16:eof_action=repeat"
    command.extend(["-filter_complex", scale])
    command.extend(_publish_args(fps, publish_url))
    return command


def _publish_args(fps: int, publish_url: str) -> list[str]:
    return [
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-tune",
        "zerolatency",
        "-pix_fmt",
        "yuv420p",
        "-bf",
        "0",
        "-g",
        str(max(fps, 1) * 2),
        "-f",
        "rtsp",
        "-rtsp_transport",
        "tcp",
        publish_url,
    ]
