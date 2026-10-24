"""Optional TCP reachability checks. Disabled unless config turns them on."""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone

from app.core.logging import get_logger
from app.services.camera_registry import CameraRegistry
from app.services.camera_state import CameraStateStore

log = get_logger(__name__)

Probe = Callable[[str, int, float], bool]


def tcp_probe(host: str, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class CameraHealthMonitor:
    def __init__(
        self,
        registry: CameraRegistry,
        state: CameraStateStore,
        *,
        enabled: bool,
        interval_seconds: float,
        timeout_seconds: float,
        probe: Probe = tcp_probe,
    ) -> None:
        self._registry = registry
        self._state = state
        self.enabled = enabled
        self._interval = interval_seconds
        self._timeout = timeout_seconds
        self._probe = probe
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not self.enabled or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="camera-health", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self._interval + 1)

    def check_once(self) -> None:
        for camera in self._registry.list_cameras():
            if not camera.enabled:
                self._state.update(camera.id, network_reachable=None, connection_status="unknown")
                continue
            reachable = self._probe(camera.connection.host, camera.connection.port, self._timeout)
            status = "online" if reachable else "offline"
            changes: dict[str, object] = {"network_reachable": reachable, "connection_status": status}
            if reachable:
                changes["last_success_at"] = datetime.now(timezone.utc).isoformat()
                changes["last_error"] = None
            else:
                changes["last_error"] = "TCP connection to the camera RTSP port failed."
            self._state.update(camera.id, **changes)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.check_once()
            except Exception:
                log.exception("camera health check failed")
            self._stop.wait(self._interval)
