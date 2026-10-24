"""Rover SITL lifecycle for the macOS simulation.

The vehicle profile, home, and frame come from the existing SITL tree.
This module only selects system 1 and the gateway's flight-controller UDP
port, and it puts the previous rover and mavp2p router back on shutdown.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from app.core.exceptions import ConfigurationError
from app.media.simulation import SimulationFile

SESSION_NAME = "data/simulation/sitl-session.json"
_PROFILE_SCRIPT = """
set -euo pipefail
source "$SITL_DIR/sitl-env.sh"
load_profile rover
printf '%s\\n' "$VEHICLE" "$FRAME" "$INSTANCE" "$LOCATION" "$STATE_DIR" "$ARDUPILOT_DIR" "$VENV_DIR" "$SITL_DIR" "$STATE_ROOT" "$SITL_PORT"
"""
_LAUNCH_SCRIPT = """
set -euo pipefail
source "$SITL_DIR/sitl-env.sh"
load_profile rover
if [[ "$VEHICLE" != "Rover" || "$FRAME" != "rover-skid" ]]; then
  echo "Rover profile is $VEHICLE $FRAME; expected Rover rover-skid." >&2
  exit 1
fi
mkdir -p "$STATE_ROOT" "$STATE_DIR"
pidfile="$(pidfile_for rover)"
logfile="$(logfile_for rover)"
if is_running "$pidfile"; then
  echo "rover already running" >&2
  exit 1
fi
rm -f "$pidfile"
cmd=(
  "$VENV_DIR/bin/python"
  "$ARDUPILOT_DIR/Tools/autotest/sim_vehicle.py"
  -v "$VEHICLE"
  -f "$FRAME"
  -I "$INSTANCE"
  --sysid "$GATEWAY_SYSID"
  --no-rebuild
  --no-mavproxy
  --use-dir "$STATE_DIR"
  --custom-location="$LOCATION"
  -A "$SERIAL_ARG"
)
spawn_group "$pidfile" "$logfile" "${cmd[@]}"
"""


@dataclass(frozen=True)
class Process:
    pid: int
    pgid: int
    command: str


@dataclass(frozen=True)
class RoverProfile:
    vehicle: str
    frame: str
    instance: str
    location: str
    state_dir: Path
    ardupilot_dir: Path
    venv_dir: Path
    sitl_dir: Path
    state_root: Path
    tcp_port: int


def session_path(root: Path) -> Path:
    return root / SESSION_NAME


def restore_saved_session(root: Path) -> str:
    blank = SimulationFile.model_validate({"cameras": [{"id": "CAM-001"}]})
    return RoverSession(root, blank).restore()


def command_is_gateway_rover(command: str, port: int) -> bool:
    serial = f"--serial0=udpclient:127.0.0.1:{port}"
    sysid = re.search(r"(?:^|\s)--sysid(?:=|\s+)1(?:\s|$)", command) is not None
    return "sim_vehicle.py" in command and "rover-skid" in command and sysid and "--no-mavproxy" in command and serial in command


def list_processes() -> list[Process]:
    output = subprocess.check_output(["ps", "-ax", "-o", "pid=,pgid=,command="], text=True)
    found: list[Process] = []
    for line in output.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) != 3:
            continue
        found.append(Process(int(parts[0]), int(parts[1]), parts[2]))
    return found


def sitl_directory(root: Path, simulation: SimulationFile) -> Path:
    path = Path(simulation.sitl.directory)
    if not path.is_absolute():
        path = (root / path).resolve()
    else:
        path = path.resolve()
    if not (path / "sitl-env.sh").is_file() or not (path / "start-sitl.sh").is_file():
        raise ConfigurationError(f"Rover SITL tree is missing sitl-env.sh: {path}")
    return path


def load_profile(directory: Path) -> RoverProfile:
    completed = subprocess.run(
        ["bash", "-c", _PROFILE_SCRIPT],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "SITL_DIR": str(directory)},
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise ConfigurationError(f"Could not read the Rover SITL profile. {detail}")
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if len(lines) != 10:
        raise ConfigurationError("Rover SITL profile did not return the expected fields.")
    vehicle, frame, instance, location, state_dir, ardupilot, venv, sitl_dir, state_root, tcp_port = lines
    if vehicle != "Rover" or frame != "rover-skid":
        raise ConfigurationError(f"Rover profile is {vehicle} {frame}; expected Rover rover-skid.")
    return RoverProfile(
        vehicle,
        frame,
        instance,
        location,
        Path(state_dir),
        Path(ardupilot),
        Path(venv),
        Path(sitl_dir),
        Path(state_root),
        int(tcp_port),
    )


def rover_simulators(processes: list[Process], state_dir: Path) -> list[Process]:
    marker = f"--use-dir {state_dir}"
    return [item for item in processes if "sim_vehicle.py" in item.command and marker in item.command and "Rover" in item.command]


def router_processes(processes: list[Process], directory: Path) -> list[Process]:
    binary = str(directory / "bin" / "mavp2p")
    return [item for item in processes if binary in item.command or item.command.split()[0:1] == ["mavp2p"]]


def needs_restart(processes: list[Process], state_dir: Path, port: int) -> bool:
    rovers = rover_simulators(processes, state_dir)
    if not rovers:
        return True
    return any(not command_is_gateway_rover(item.command, port) for item in rovers)


class RoverSession:
    def __init__(self, root: Path, simulation: SimulationFile) -> None:
        self.root = root
        self.simulation = simulation
        self.path = session_path(root)

    def prepare(self) -> str:
        if not self.simulation.sitl.enabled:
            return "Rover SITL is disabled."
        directory = sitl_directory(self.root, self.simulation)
        profile = load_profile(directory)
        port = self.simulation.sitl.flight_controller_port
        processes = list_processes()
        rovers = rover_simulators(processes, profile.state_dir)
        routers = router_processes(processes, directory)
        self._write_session(
            {
                "sitl_directory": str(directory),
                "router_was_running": bool(routers),
                "rover_was_running": bool(rovers),
                "replaced_rover": False,
            }
        )
        self._stop_groups({item.pgid for item in routers})
        self._remove_pid(profile.state_root / "router.pid")
        if rovers and not needs_restart(processes, profile.state_dir, port):
            return f"Reusing Rover SITL on UDP 127.0.0.1:{port} as system 1."
        self._stop_rover(directory, profile)
        self._launch(directory, port)
        self._write_session(
            {
                "sitl_directory": str(directory),
                "router_was_running": bool(routers),
                "rover_was_running": bool(rovers),
                "replaced_rover": True,
            }
        )
        return f"Rover SITL restarted on UDP 127.0.0.1:{port} as system 1."

    def restore(self) -> str:
        if not self.path.is_file():
            return ""
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ConfigurationError(f"SITL session file is invalid: {exc}") from exc
        recorded = int(payload.get("owner_pid") or 0)
        if recorded and _pid_alive(recorded) and recorded != os.getpid():
            return ""
        directory = Path(str(payload.get("sitl_directory", "")))
        if not (directory / "stop-sitl.sh").is_file():
            self.path.unlink(missing_ok=True)
            return ""
        if payload.get("replaced_rover"):
            self._run(directory / "stop-sitl.sh", "rover")
            if payload.get("rover_was_running"):
                self._run(directory / "start-sitl.sh", "rover")
                message = "Restored the direct Rover SITL profile and its router."
            elif payload.get("router_was_running"):
                self._run(directory / "start-router.sh")
                message = "Restored the SITL router."
            else:
                message = "Stopped the simulation Rover SITL."
        elif payload.get("router_was_running") and not router_processes(list_processes(), directory):
            self._run(directory / "start-router.sh")
            message = "Restored the SITL router."
        else:
            message = ""
        self.path.unlink(missing_ok=True)
        return message

    def _stop_rover(self, directory: Path, profile: RoverProfile) -> None:
        self._run(directory / "stop-sitl.sh", "rover")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            processes = list_processes()
            leftover = rover_simulators(processes, profile.state_dir)
            binaries = [item for item in processes if "/ardurover" in item.command and "rover-skid" in item.command]
            if not leftover and not binaries and not _listening(profile.tcp_port):
                self._remove_pid(profile.state_root / "rover.pid")
                return
            self._stop_groups({item.pgid for item in leftover + binaries})
            time.sleep(0.3)
        raise ConfigurationError("The previous Rover SITL did not release its port.")

    def _launch(self, directory: Path, port: int) -> None:
        completed = subprocess.run(
            ["bash", "-c", _LAUNCH_SCRIPT],
            check=False,
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "SITL_DIR": str(directory),
                "GATEWAY_SYSID": "1",
                "SERIAL_ARG": f"--serial0=udpclient:127.0.0.1:{port}",
            },
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise ConfigurationError(f"Rover SITL did not start. {detail}")

    def _write_session(self, payload: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        body = {**payload, "owner_pid": os.getpid()}
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)

    def _run(self, script: Path, *args: str) -> None:
        completed = subprocess.run([str(script), *args], check=False, capture_output=True, text=True)
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise ConfigurationError(f"{script.name} failed. {detail}")

    @staticmethod
    def _stop_groups(groups: set[int]) -> None:
        own = os.getpgrp()
        for group in groups:
            if group <= 1 or group == own:
                continue
            _signal_group(group, signal.SIGTERM)
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            if all(not _group_alive(group) for group in groups if group > 1 and group != own):
                return
            time.sleep(0.3)
        for group in groups:
            if group > 1 and group != own:
                _signal_group(group, signal.SIGKILL)

    @staticmethod
    def _remove_pid(path: Path) -> None:
        path.unlink(missing_ok=True)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _signal_group(group: int, sig: int) -> None:
    try:
        os.killpg(group, sig)
    except (ProcessLookupError, PermissionError):
        return


def _group_alive(group: int) -> bool:
    try:
        os.killpg(group, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _listening(port: int) -> bool:
    completed = subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"], check=False, capture_output=True, text=True)
    return completed.returncode == 0 and bool(completed.stdout.strip())
