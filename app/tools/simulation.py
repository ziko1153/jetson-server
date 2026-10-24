"""Keep the gateway, six virtual cameras, and the mosaic running until stopped."""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import socket
import sys
import threading
import time
from pathlib import Path

import httpx
from pydantic import ValidationError

from app.core.config import load_settings
from app.core.exceptions import ConfigurationError
from app.core.paths import project_root
from app.infrastructure.processes.supervisor import ManagedProcess
from app.media.labels import write_label
from app.media.pattern_publisher import pattern_publisher_command
from app.media.simulation import (
    ACCENTS,
    SimulationFile,
    advertise_host_for,
    gateway_environment,
    generated_cameras,
    load_camera_file,
    load_simulation,
    playback_host,
    ready_banner,
    render_publisher_config,
    resolve_bind_host,
    resolve_media_file,
    validate_sources,
)
from app.media.virtual import virtual_camera_command
from app.services.context import _media_binary
from app.services.secrets import load_secrets
from app.tools.rover_sitl import RoverSession, restore_saved_session


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the camera gateway with local virtual cameras.")
    parser.add_argument("command", choices=("run", "print-urls", "restore-sitl"))
    parser.add_argument("--bind-host", default="")
    parser.add_argument("--bind-interface", default="")
    parser.add_argument("--advertise-host", default="")
    args = parser.parse_args(argv)
    try:
        if args.command == "print-urls":
            print(describe(project_root(), args), end="")
            return
        if args.command == "restore-sitl":
            message = restore_saved_session(project_root())
            if message:
                print(message)
            return
        raise SystemExit(run(project_root(), args))
    except ConfigurationError as exc:
        print(exc.message, file=sys.stderr)
        raise SystemExit(1) from exc


def run(root: Path, args: argparse.Namespace) -> int:
    runtime = SimulationRuntime(root, args)
    signal.signal(signal.SIGINT, runtime.request_stop)
    signal.signal(signal.SIGTERM, runtime.request_stop)
    try:
        runtime.start()
        runtime.wait()
        return 0
    except ConfigurationError as exc:
        print(exc.message, file=sys.stderr)
        return 1
    finally:
        runtime.shutdown()


def describe(root: Path, args: argparse.Namespace) -> str:
    simulation = _simulation(root, args)
    bind_host = resolve_bind_host(simulation)
    host = playback_host(bind_host)
    interfaces = _interfaces() if host == "127.0.0.1" else []
    return ready_banner(host, simulation.api_port, simulation.rtsp_port, [item.id for item in simulation.cameras], interfaces)


class SimulationRuntime:
    def __init__(self, root: Path, args: argparse.Namespace) -> None:
        self.root = root
        self.args = args
        self.stop = threading.Event()
        self.processes: list[ManagedProcess] = []
        self.gateway: ManagedProcess | None = None
        self._closed = False
        self._pid_path = root / "data" / "simulation.pid"
        self.simulation: SimulationFile | None = None

    def request_stop(self, _signum, _frame) -> None:
        self.stop.set()

    def start(self) -> None:
        _refuse_if_running(self._pid_path, "Simulation")
        _refuse_if_running(self.root / "data" / "gateway.pid", "Gateway")
        self._pid_path.parent.mkdir(parents=True, exist_ok=True)
        self._pid_path.write_text(f"{os.getpid()}\n", encoding="utf-8")
        simulation = _simulation(self.root, self.args)
        self.simulation = simulation
        settings = load_settings(self.root)
        cameras = load_camera_file(self.root / "config" / "cameras.simulation.json")
        secrets = load_secrets(settings.secrets_path)
        validate_sources(self.root, simulation, cameras, secrets)
        bind_host = resolve_bind_host(simulation)
        advertised = advertise_host_for(simulation, bind_host)
        if self.args.advertise_host:
            advertised = self.args.advertise_host
        binary = _media_binary(settings)
        ffmpeg = shutil.which("ffmpeg")
        if binary is None or not binary.is_file() or ffmpeg is None:
            raise ConfigurationError("FFmpeg and MediaMTX are required. Run scripts/setup-mac.sh first.")
        if settings.auth.mode == "bearer" and not secrets.api_token:
            raise ConfigurationError("auth.mode is bearer, but no API token is configured.")
        self._require_ports(simulation, bind_host, generated_cameras(simulation, cameras))
        self._start_publishers(simulation, cameras, binary, ffmpeg)
        self._start_gateway(simulation, bind_host, advertised)
        if simulation.sitl.enabled:
            print(RoverSession(self.root, simulation).prepare(), flush=True)
        self._publish_gateway_streams(simulation, cameras, bind_host, settings.auth.mode, secrets.api_token)
        if simulation.sitl.enabled:
            self._wait_for_flight_controller(simulation, bind_host)
        host = playback_host(bind_host)
        interfaces = _interfaces() if host == "127.0.0.1" else []
        print(
            ready_banner(
                host,
                simulation.api_port,
                simulation.rtsp_port,
                [camera.id for camera in cameras if camera.enabled],
                interfaces,
                mavlink_port=14550 if simulation.sitl.enabled else None,
                flight_controller_port=simulation.sitl.flight_controller_port if simulation.sitl.enabled else None,
            ),
            flush=True,
        )

    def wait(self) -> None:
        while not self.stop.is_set():
            if self.gateway is not None and not self.gateway.running:
                raise ConfigurationError("The gateway exited. See data/logs/gateway.log.")
            self.stop.wait(0.5)

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.stop.set()
        if self.gateway is not None:
            self.gateway.stop()
        for process in reversed(self.processes):
            process.stop()
        if self._pid_path.is_file() and self._pid_path.read_text(encoding="utf-8").strip() == str(os.getpid()):
            self._pid_path.unlink(missing_ok=True)
        try:
            message = restore_saved_session(self.root)
        except ConfigurationError as exc:
            print(exc.message, file=sys.stderr)
            return
        if message:
            print(message, flush=True)

    def _require_ports(self, simulation: SimulationFile, bind_host: str, generated: list) -> None:
        api_host = "0.0.0.0" if bind_host in {"", "0.0.0.0", "::"} else bind_host
        _require_port_free(api_host, simulation.api_port, "API")
        _require_port_free(api_host, simulation.rtsp_port, "RTSP")
        _require_port_free("127.0.0.1", simulation.control_port, "MediaMTX control")
        if generated:
            _require_port_free("127.0.0.1", simulation.publisher_rtsp_port, "Virtual camera RTSP")
            _require_port_free("127.0.0.1", simulation.publisher_control_port, "Virtual camera control")
        if simulation.sitl.enabled:
            _require_port_free("127.0.0.1", simulation.sitl.flight_controller_port, "Flight controller UDP")

    def _start_publishers(self, simulation: SimulationFile, cameras: list, binary: Path, ffmpeg: str) -> None:
        selected = generated_cameras(simulation, cameras)
        if not selected:
            return
        by_input = {item.id: item for item in simulation.cameras}
        label_dir = self.root / "data" / "simulation" / "labels"
        config_path = self.root / "data" / "simulation" / "publisher.yml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            render_publisher_config([camera.id for camera in selected], simulation.publisher_rtsp_port, simulation.publisher_control_port),
            encoding="utf-8",
        )
        server = self._spawn(
            "simulation-mediamtx",
            [str(binary), str(config_path)],
            self.root / "data" / "logs" / "simulation-mediamtx.log",
            self.root / "data" / "run" / "simulation-mediamtx.pid",
        )
        _wait_until(
            self.stop,
            10,
            lambda: self._failure("The virtual camera RTSP port did not open.", "simulation-mediamtx.log"),
            lambda: _listening(simulation.publisher_rtsp_port),
        )
        if not server.running:
            raise ConfigurationError(self._failure("Virtual MediaMTX exited.", "simulation-mediamtx.log"))
        for index, camera in enumerate(selected):
            item = by_input[camera.id]
            publish = f"rtsp://127.0.0.1:{simulation.publisher_rtsp_port}/{camera.id}"
            accent = ACCENTS[index % len(ACCENTS)]
            if item.input == "file":
                label = label_dir / f"{camera.id}.ppm"
                write_label(label, camera.id, accent)
                command = virtual_camera_command(
                    publish,
                    width=simulation.width,
                    height=simulation.height,
                    fps=simulation.fps,
                    ffmpeg=ffmpeg,
                    media_file=str(resolve_media_file(self.root, item.file)),
                    label_image=str(label),
                )
            else:
                command = pattern_publisher_command(
                    sys.executable,
                    publish,
                    camera.id,
                    simulation.width,
                    simulation.height,
                    simulation.fps,
                    accent,
                )
            self._spawn(
                f"virtual-{camera.id}",
                command,
                self.root / "data" / "logs" / f"virtual-{camera.id}.log",
                self.root / "data" / "run" / f"virtual-{camera.id}.pid",
            )
        expected = {camera.id for camera in selected}
        _wait_until(
            self.stop,
            20,
            lambda: self._failure("Virtual cameras did not publish.", "simulation-mediamtx.log"),
            lambda: expected <= _online_paths(simulation.publisher_control_port),
        )

    def _start_gateway(self, simulation: SimulationFile, bind_host: str, advertised: str) -> None:
        env = gateway_environment(dict(os.environ), simulation, bind_host, advertised)
        self.gateway = ManagedProcess(
            name="gateway",
            args=[sys.executable, "-m", "uvicorn", "app.main:app", "--host", bind_host, "--port", str(simulation.api_port)],
            log_path=self.root / "data" / "logs" / "gateway.log",
            stop_timeout_seconds=8,
            pid_file=self.root / "data" / "gateway.pid",
            env=env,
            cwd=str(self.root),
        )
        self.gateway.start()
        api_host = "127.0.0.1" if bind_host in {"", "0.0.0.0", "::"} else bind_host

        def healthy() -> bool:
            if self.gateway is not None and not self.gateway.running:
                return False
            response = httpx.get(f"http://{api_host}:{simulation.api_port}/api/v1/health", timeout=1)
            return response.status_code == 200

        try:
            _wait_until(self.stop, 20, lambda: self._failure("The gateway did not become ready.", "gateway.log"), healthy)
        except ConfigurationError:
            if self.gateway is not None and not self.gateway.running:
                raise ConfigurationError(self._failure("The gateway exited during startup.", "gateway.log")) from None
            raise
        if self.gateway is not None and not self.gateway.running:
            raise ConfigurationError(self._failure("The gateway exited during startup.", "gateway.log"))

    def _wait_for_flight_controller(self, simulation: SimulationFile, bind_host: str) -> None:
        api_host = "127.0.0.1" if bind_host in {"", "0.0.0.0", "::"} else bind_host
        url = f"http://{api_host}:{simulation.api_port}/api/v1/system/status"

        def connected() -> bool:
            if self.gateway is not None and not self.gateway.running:
                return False
            try:
                response = httpx.get(url, timeout=1)
            except httpx.HTTPError:
                return False
            if response.status_code != 200:
                return False
            body = response.json()
            flight = body.get("mavlink", {}).get("flight_controller", {})
            mount = body.get("rcwm", {})
            return (
                flight.get("transport") == "udp"
                and flight.get("connected") is True
                and mount.get("enabled") is True
                and mount.get("transport") == "simulation"
            )

        _wait_until(
            self.stop,
            90,
            lambda: self._failure("Rover SITL did not reach the flight-controller port.", "gateway.log")
            + _tail(Path("/tmp/bhimrul-sitl/rover.log")),
            connected,
        )

    def _publish_gateway_streams(
        self,
        simulation: SimulationFile,
        cameras: list,
        bind_host: str,
        auth_mode: str,
        token: str | None,
    ) -> None:
        api_host = "127.0.0.1" if bind_host in {"", "0.0.0.0", "::"} else bind_host
        base = f"http://{api_host}:{simulation.api_port}/api/v1"
        headers = {"Authorization": f"Bearer {token}"} if auth_mode == "bearer" and token else {}
        enabled = [camera.id for camera in cameras if camera.enabled]
        for camera_id in enabled:
            self._check_stop()
            _post(f"{base}/streams/{camera_id}/start", headers, {"mode": "passthrough"})
        _post(f"{base}/mosaic/start", headers, None)
        expected = {f"camera/{camera_id}" for camera_id in enabled}
        _wait_until(
            self.stop,
            25,
            lambda: self._failure("Gateway camera streams did not come online.", "mediamtx.log"),
            lambda: expected <= _online_paths(simulation.control_port),
        )
        _wait_until(
            self.stop,
            60,
            lambda: self._failure("The mosaic stream did not come online.", "mosaic.log"),
            lambda: "mosaic" in _online_paths(simulation.control_port),
        )

    def _spawn(self, name: str, args: list[str], log_path: Path, pid_file: Path) -> ManagedProcess:
        process = ManagedProcess(
            name=name,
            args=args,
            log_path=log_path,
            restart_attempts=3,
            restart_backoff_seconds=1,
            pid_file=pid_file,
            cwd=str(self.root),
        )
        process.start()
        self.processes.append(process)
        return process

    def _check_stop(self) -> None:
        if self.stop.is_set():
            raise ConfigurationError("Simulation stopped while starting.")

    def _failure(self, message: str, *logs: str) -> str:
        parts = [message]
        for name in logs:
            parts.append(_tail(self.root / "data" / "logs" / name))
        for path in sorted((self.root / "data" / "logs").glob("virtual-*.log")):
            parts.append(f"{path.name}: {_tail(path)}")
        return "\n".join(part for part in parts if part)


def _simulation(root: Path, args: argparse.Namespace) -> SimulationFile:
    simulation = load_simulation(root / "config" / "simulation.json")
    updates = {}
    if args.bind_host:
        updates["bind_host"] = args.bind_host
    if args.bind_interface:
        updates["bind_interface"] = args.bind_interface
    if args.advertise_host:
        updates["advertise_host"] = args.advertise_host
    if not updates:
        return simulation
    try:
        return SimulationFile.model_validate({**simulation.model_dump(), **updates})
    except ValidationError as exc:
        raise ConfigurationError(f"Simulation options are invalid: {exc}") from exc


def _refuse_if_running(path: Path, label: str) -> None:
    if not path.is_file():
        return
    raw = path.read_text(encoding="utf-8").strip()
    if not raw.isdigit():
        return
    pid = int(raw)
    if pid == os.getpid():
        return
    try:
        os.kill(pid, 0)
    except OSError:
        return
    raise ConfigurationError(f"{label} is already running (pid {pid}). Stop it with bash scripts/stop-simulation.sh.")


def _require_port_free(host: str, port: int, label: str) -> None:
    deadline = time.monotonic() + 5
    while True:
        if not (host in {"0.0.0.0", "::"} and _listening(port)):
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                sock.bind((host, port))
                return
            except OSError:
                pass
            finally:
                sock.close()
        if time.monotonic() >= deadline:
            raise ConfigurationError(f"{label} {host}:{port} is already in use.")
        time.sleep(0.2)


def _listening(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _wait_until(stop: threading.Event, timeout: float, message: str, ready) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if stop.is_set():
            raise ConfigurationError("Simulation stopped while starting.")
        try:
            if ready():
                return
        except ConfigurationError:
            raise
        except Exception:
            pass
        if stop.wait(0.4):
            raise ConfigurationError("Simulation stopped while starting.")
    text = message() if callable(message) else message
    raise ConfigurationError(text)


def _online_paths(control_port: int) -> set[str]:
    response = httpx.get(f"http://127.0.0.1:{control_port}/v3/paths/list", timeout=1)
    response.raise_for_status()
    names = set()
    for item in response.json().get("items") or []:
        if item.get("online") or item.get("ready"):
            name = item.get("name")
            if name:
                names.add(name)
    return names


def _post(url: str, headers: dict[str, str], body: dict | None) -> None:
    try:
        response = httpx.post(url, headers=headers, json=body, timeout=15)
    except httpx.HTTPError as exc:
        raise ConfigurationError(f"Could not call {url}.") from exc
    if response.status_code >= 300:
        raise ConfigurationError(f"{url} returned {response.status_code}: {response.text[:400]}")


def _tail(path: Path, limit: int = 30) -> str:
    if not path.is_file():
        return ""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines:
        return ""
    return f"\n## {path.name}\n" + "\n".join(lines[-limit:])


def _interfaces() -> list[tuple[str, str]]:
    import re
    import subprocess

    if sys.platform == "darwin":
        completed = subprocess.run(["ifconfig"], capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            return []
        from app.media.simulation import parse_ifconfig

        return parse_ifconfig(completed.stdout)
    completed = subprocess.run(["ip", "-4", "-o", "addr", "show"], capture_output=True, text=True, check=False)
    found = []
    for line in completed.stdout.splitlines():
        match = re.search(r"^\d+:\s+(\S+)\s+inet (\d+\.\d+\.\d+\.\d+)/", line)
        if match and not match.group(1).startswith("lo"):
            found.append((match.group(1), match.group(2)))
    return found


if __name__ == "__main__":
    main()
