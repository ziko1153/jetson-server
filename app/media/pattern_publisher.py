"""Publish one virtual camera whose picture is this computer's clock."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time

from app.media.labels import render_clock_frame
from app.media.virtual import _publish_args


def pattern_publisher_command(
    python: str,
    publish_url: str,
    camera_id: str,
    width: int,
    height: int,
    fps: int,
    accent: tuple[int, int, int],
) -> list[str]:
    return [
        python,
        "-m",
        "app.media.pattern_publisher",
        "--camera",
        camera_id,
        "--width",
        str(width),
        "--height",
        str(height),
        "--fps",
        str(fps),
        "--url",
        publish_url,
        "--red",
        str(accent[0]),
        "--green",
        str(accent[1]),
        "--blue",
        str(accent[2]),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Publish a clock test pattern over RTSP.")
    parser.add_argument("--camera", required=True)
    parser.add_argument("--width", type=int, required=True)
    parser.add_argument("--height", type=int, required=True)
    parser.add_argument("--fps", type=int, required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--red", type=int, required=True)
    parser.add_argument("--green", type=int, required=True)
    parser.add_argument("--blue", type=int, required=True)
    args = parser.parse_args(argv)
    binary = shutil.which("ffmpeg")
    if binary is None:
        print("ffmpeg is required to generate a virtual camera", file=sys.stderr)
        return 1
    command = [
        binary,
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-video_size",
        f"{args.width}x{args.height}",
        "-framerate",
        str(args.fps),
        "-i",
        "pipe:0",
    ]
    command.extend(_publish_args(args.fps, args.url))
    process = subprocess.Popen(command, stdin=subprocess.PIPE)
    if process.stdin is None:
        return 1
    period = 1 / args.fps
    next_at = time.monotonic()
    accent = (args.red, args.green, args.blue)
    try:
        while process.poll() is None:
            now = time.time()
            clock = time.strftime("%H:%M:%S", time.localtime(now)) + f".{int(now * 10) % 10}"
            frame = render_clock_frame(
                args.width,
                args.height,
                args.camera,
                clock,
                accent,
                int(now * args.fps),
            )
            process.stdin.write(frame)
            process.stdin.flush()
            next_at += period
            delay = next_at - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            else:
                next_at = time.monotonic()
    except (BrokenPipeError, OSError):
        return 1
    finally:
        process.stdin.close()
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=5)
    return process.returncode or 0


if __name__ == "__main__":
    raise SystemExit(main())
