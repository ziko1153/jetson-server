"""Host and media-process resource snapshots."""

from __future__ import annotations

import os
import subprocess


def host_resources(pids: list[int]) -> dict:
    load: tuple[float, float, float] | None
    try:
        load = os.getloadavg()
    except OSError:
        load = None
    processes = []
    for pid in pids:
        rss = _rss_bytes(pid)
        if rss is None:
            continue
        processes.append({"pid": pid, "rss_bytes": rss})
    return {
        "load_average": {"one": load[0], "five": load[1], "fifteen": load[2]} if load else None,
        "media_processes": processes,
    }


def _rss_bytes(pid: int) -> int | None:
    completed = subprocess.run(
        ["ps", "-o", "rss=", "-p", str(pid)],
        capture_output=True,
        text=True,
        timeout=2,
        check=False,
    )
    text = completed.stdout.strip()
    if completed.returncode != 0 or not text.isdigit():
        return None
    return int(text) * 1024
