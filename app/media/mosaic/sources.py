"""Which mosaic cameras can be pulled right now.

A camera that does not accept a TCP connection on its RTSP port is drawn as a
NO SIGNAL tile, so one missing camera does not stop the whole mosaic. Only
cameras already in the registry are contacted.
"""

from __future__ import annotations

import socket
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

NO_SIGNAL_TEXT = "NO SIGNAL"
NO_SIGNAL_IMAGE = Path(__file__).with_name("no_signal.png")


def reachable(endpoints: dict[str, tuple[str, int]], timeout: float) -> frozenset[str]:
    if not endpoints:
        return frozenset()

    def check(item: tuple[str, tuple[str, int]]) -> str | None:
        camera_id, (host, port) = item
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return camera_id
        except OSError:
            return None

    with ThreadPoolExecutor(max_workers=len(endpoints)) as pool:
        return frozenset(camera_id for camera_id in pool.map(check, endpoints.items()) if camera_id)
