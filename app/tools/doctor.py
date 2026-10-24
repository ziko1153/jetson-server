"""Print detected platform capabilities."""

from __future__ import annotations

import argparse
import json
import sys

from app.core.config import load_settings
from app.core.environment import detect_environment
from app.services.context import _media_binary


def main() -> None:
    parser = argparse.ArgumentParser(description="Check gateway dependencies and platform detection.")
    parser.add_argument("--require-runtime", action="store_true", help="Exit non-zero when FFmpeg or MediaMTX is missing.")
    args = parser.parse_args()
    settings = load_settings()
    binary = _media_binary(settings)
    report = detect_environment(mediamtx_path=binary)
    payload = report.as_dict()
    payload["auth_mode"] = settings.auth.mode
    payload["health_checks_enabled"] = settings.health.enabled
    payload["manage_media_server"] = settings.streaming.manage_media_server
    payload["mavlink_enabled"] = settings.mavlink.enabled
    payload["mavlink_bind"] = f"{settings.mavlink.bind_host}:{settings.mavlink.bind_port}"
    payload["rcwm_transport"] = settings.rcwm.transport
    payload["rcwm_hardware_motion"] = settings.rcwm.allow_hardware_motion
    print(json.dumps(payload, indent=2))
    if not args.require_runtime:
        return
    missing = []
    if not report.ffmpeg or not report.ffprobe:
        missing.append("ffmpeg/ffprobe")
    if settings.streaming.manage_media_server and not report.mediamtx:
        missing.append("mediamtx")
    if missing:
        print(f"Missing runtime dependencies: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
