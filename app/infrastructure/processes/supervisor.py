"""Supervised subprocesses. Commands are argument lists, never a shell."""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from app.core.logging import get_logger

log = get_logger(__name__)


@dataclass
class ManagedProcess:
    name: str
    args: list[str]
    log_path: Path | None = None
    restart_attempts: int = 0
    restart_backoff_seconds: float = 2
    stop_timeout_seconds: float = 5
    pid_file: Path | None = None
    env: dict[str, str] | None = None
    cwd: str | None = None
    _process: subprocess.Popen[str] | None = field(default=None, init=False)
    _restarts: int = field(default=0, init=False)
    _stop: threading.Event = field(default_factory=threading.Event, init=False)
    _watcher: threading.Thread | None = field(default=None, init=False)
    last_error: str | None = None

    @property
    def pid(self) -> int | None:
        if self._process is None or self._process.poll() is not None:
            return None
        return self._process.pid

    @property
    def restarts(self) -> int:
        return self._restarts

    @property
    def running(self) -> bool:
        return self.pid is not None

    def start(self) -> None:
        self._stop.clear()
        self._spawn()
        if self.restart_attempts and self._watcher is None:
            self._watcher = threading.Thread(target=self._watch, name=f"watch-{self.name}", daemon=True)
            self._watcher.start()

    def stop(self) -> None:
        self._stop.set()
        self._terminate(self._process)
        self._clear_pid_file()

    def terminate_now(self) -> None:
        """Signal-handler safe stop. It does not wait or log."""
        process = self._process
        if process is None or process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return

    def _spawn(self) -> None:
        log_handle = None
        stdout = subprocess.DEVNULL
        if self.log_path is not None:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            log_handle = self.log_path.open("a", encoding="utf-8")
            stdout = log_handle
        self._process = subprocess.Popen(
            self.args,
            stdout=stdout,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            text=True,
            env=self.env,
            cwd=self.cwd,
        )
        if self.pid_file is not None:
            self.pid_file.parent.mkdir(parents=True, exist_ok=True)
            self.pid_file.write_text(f"{self._process.pid}\n", encoding="utf-8")
        log.info("process started name=%s pid=%s", self.name, self._process.pid)

    def _watch(self) -> None:
        while not self._stop.is_set():
            process = self._process
            if process is None:
                return
            code = process.wait()
            if self._stop.is_set():
                return
            self.last_error = f"{self.name} exited with status {code}"
            if self._restarts >= self.restart_attempts:
                log.error("process gave up name=%s status=%s", self.name, code)
                return
            self._restarts += 1
            time.sleep(self.restart_backoff_seconds)
            if self._stop.is_set():
                return
            log.info("process restarting name=%s attempt=%s", self.name, self._restarts)
            self._spawn()

    def _terminate(self, process: subprocess.Popen[str] | None) -> None:
        if process is None or process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        deadline = time.monotonic() + self.stop_timeout_seconds
        while time.monotonic() < deadline:
            if process.poll() is not None:
                return
            time.sleep(0.1)
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        process.wait(timeout=self.stop_timeout_seconds)

    def _clear_pid_file(self) -> None:
        if self.pid_file is not None:
            self.pid_file.unlink(missing_ok=True)
