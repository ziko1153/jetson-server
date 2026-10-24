"""Read host metrics that the machine actually exposes.

Missing files and failed readers become null. NVIDIA temperature and GPU load
are left null on macOS.
"""

from __future__ import annotations

import ctypes
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

GPU_LOAD_FILES = (
    "/sys/devices/gpu.0/load",
    "/sys/devices/17000000.ga10b/load",
    "/sys/devices/15400000.nvjpg/load",
)


def _cpu_percent_sample(previous: tuple[int, int] | None, current: tuple[int, int]) -> float | None:
    if previous is None:
        return None
    total = current[0] - previous[0]
    idle = current[1] - previous[1]
    if total <= 0:
        return None
    return round((1 - idle / total) * 100, 1)


class HostSampler:
    def __init__(self) -> None:
        self._cpu: tuple[int, int] | None = None

    def collect(self, environment, disk_path: Path) -> dict:
        current = _cpu_ticks()
        percent = None
        if current is not None:
            percent = _cpu_percent_sample(self._cpu, current)
            self._cpu = current
        temperature = None if environment.system == "Darwin" else _temperature()
        gpu_file = _gpu_file()
        gpu = _gpu_percent() if gpu_file else None
        nvidia_available = environment.hardware == "jetson" and (temperature is not None or gpu_file is not None)
        return {
            "cpu_percent": percent,
            "memory": _memory(),
            "disk": _disk(disk_path),
            "uptime_seconds": _uptime(),
            "temperature_c": temperature,
            "gpu_percent": gpu,
            "nvidia_metrics": "available" if nvidia_available else "unavailable",
            "hardware": environment.hardware,
            "system": environment.system,
            "machine": environment.machine,
            "jetson_model": environment.jetson_model,
            "l4t_release": environment.l4t_release,
            "jetpack_family": environment.jetpack_family,
        }


def _cpu_ticks() -> tuple[int, int] | None:
    stat = Path("/proc/stat")
    if stat.is_file():
        parts = stat.read_text(encoding="utf-8").splitlines()[0].split()[1:]
        numbers = [int(item) for item in parts]
        idle = numbers[3] + (numbers[4] if len(numbers) > 4 else 0)
        return sum(numbers), idle
    if os.uname().sysname == "Darwin":
        return _darwin_cpu_ticks()
    return None


def _darwin_cpu_ticks() -> tuple[int, int] | None:
    class Load(ctypes.Structure):
        _fields_ = [("ticks", ctypes.c_uint32 * 4)]

    libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
    libc.mach_host_self.restype = ctypes.c_uint
    libc.host_statistics.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.POINTER(Load), ctypes.POINTER(ctypes.c_uint)]
    libc.host_statistics.restype = ctypes.c_int
    info = Load()
    count = ctypes.c_uint(4)
    if libc.host_statistics(libc.mach_host_self(), 3, ctypes.byref(info), ctypes.byref(count)) != 0:
        return None
    user, system, idle, nice = info.ticks
    return user + system + idle + nice, idle


def _memory() -> dict:
    meminfo = Path("/proc/meminfo")
    if meminfo.is_file():
        values = {}
        for line in meminfo.read_text(encoding="utf-8").splitlines():
            key, _, rest = line.partition(":")
            values[key] = int(rest.strip().split()[0]) * 1024
        total = values.get("MemTotal")
        available = values.get("MemAvailable")
        used = None if total is None or available is None else round((total - available) / total * 100, 1)
        return {"total_bytes": total, "available_bytes": available, "used_percent": used}
    if os.uname().sysname == "Darwin":
        return _darwin_memory()
    return {"total_bytes": None, "available_bytes": None, "used_percent": None}


def _darwin_memory() -> dict:
    try:
        total = int(_sysctl("hw.memsize"))
        page = int(_sysctl("hw.pagesize"))
        text = subprocess.check_output(["vm_stat"], text=True, timeout=2)
    except (OSError, subprocess.SubprocessError, ValueError):
        return {"total_bytes": None, "available_bytes": None, "used_percent": None}
    pages = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, raw = line.split(":", 1)
        number = raw.strip().strip(".")
        if number.isdigit():
            pages[key.strip()] = int(number)
    available_pages = sum(pages.get(name, 0) for name in ("Pages free", "Pages inactive", "Pages speculative"))
    available = available_pages * page
    used = round((total - available) / total * 100, 1) if total else None
    return {"total_bytes": total, "available_bytes": available, "used_percent": used}


def _disk(path: Path) -> dict:
    target = path if path.exists() else Path("/")
    try:
        usage = shutil.disk_usage(target)
    except OSError:
        return {"path": str(target), "total_bytes": None, "used_bytes": None, "free_bytes": None}
    return {
        "path": str(target),
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
    }


def _uptime() -> float | None:
    proc = Path("/proc/uptime")
    if proc.is_file():
        return round(float(proc.read_text(encoding="utf-8").split()[0]), 3)
    if os.uname().sysname != "Darwin":
        return None
    try:
        raw = _sysctl("kern.boottime")
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r"sec = (\d+)", raw)
    if not match:
        return None
    return round(time.time() - int(match.group(1)), 3)


def _temperature() -> float | None:
    root = Path("/sys/devices/virtual/thermal")
    if not root.is_dir():
        return None
    chosen = None
    fallback = None
    for zone in sorted(root.glob("thermal_zone*")):
        temp_file = zone / "temp"
        if not temp_file.is_file():
            continue
        try:
            millidegree = int(temp_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            continue
        kind = ""
        type_file = zone / "type"
        if type_file.is_file():
            kind = type_file.read_text(encoding="utf-8").strip().lower()
        celsius = millidegree / 1000.0
        if fallback is None:
            fallback = celsius
        if "cpu" in kind:
            chosen = celsius
            break
    value = chosen if chosen is not None else fallback
    if value is None:
        return None
    return round(value, 1)


def _gpu_file() -> Path | None:
    for candidate in GPU_LOAD_FILES:
        path = Path(candidate)
        if path.is_file():
            return path
    return None


def _gpu_percent() -> float | None:
    path = _gpu_file()
    if path is None:
        return None
    try:
        raw = int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    return round(raw / 10.0, 1)


def _sysctl(name: str) -> str:
    return subprocess.check_output(["sysctl", "-n", name], text=True, timeout=2).strip()
