"""Development-camera configuration. Production startup does not load this."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from app.core.exceptions import ConfigurationError
from app.core.paths import resolve_under_root
from app.media.virtual import PATTERNS
from app.schemas.camera import CameraFile, CameraRecord, require_camera_id
from app.services.secrets import SecretStore

PUBLISHER_HOST = "127.0.0.1"
_INTERFACE = re.compile(r"^[A-Za-z][A-Za-z0-9:._-]{0,31}$")
_HOST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-]{0,252}$")
ACCENTS = (
    (220, 40, 40),
    (40, 180, 60),
    (40, 90, 220),
    (220, 180, 30),
    (180, 40, 180),
    (30, 180, 190),
)


class SimulationCamera(BaseModel):
    id: str
    input: str = "pattern"
    pattern: str = "testsrc"
    hue_speed: int = Field(default=0, ge=0, le=360)
    file: str = ""

    @field_validator("id")
    @classmethod
    def id_ok(cls, value: str) -> str:
        return require_camera_id(value)

    @field_validator("input")
    @classmethod
    def input_ok(cls, value: str) -> str:
        if value not in {"pattern", "file", "rtsp"}:
            raise ValueError("input must be pattern, file, or rtsp")
        return value

    @field_validator("pattern")
    @classmethod
    def pattern_ok(cls, value: str) -> str:
        if value not in PATTERNS:
            raise ValueError(f"pattern must be one of {sorted(PATTERNS)}")
        return value

    @model_validator(mode="after")
    def file_present(self) -> "SimulationCamera":
        if self.input == "file" and not self.file.strip():
            raise ValueError("file input requires a file path")
        return self


class SitlSettings(BaseModel):
    enabled: bool = True
    directory: str = "../sitl"
    flight_controller_port: int = Field(default=14551, ge=1, le=65535)

    @field_validator("directory")
    @classmethod
    def directory_ok(cls, value: str) -> str:
        if not value.strip() or "\n" in value or "\x00" in value:
            raise ValueError("sitl.directory must be a path")
        return value.strip()


class SimulationFile(BaseModel):
    schema_version: int = 1
    bind_host: str = "0.0.0.0"
    bind_interface: str = ""
    advertise_host: str = ""
    api_port: int = Field(default=8080, ge=1, le=65535)
    rtsp_port: int = Field(default=8554, ge=1, le=65535)
    control_port: int = Field(default=9997, ge=1, le=65535)
    publisher_rtsp_port: int = Field(default=8555, ge=1, le=65535)
    publisher_control_port: int = Field(default=9998, ge=1, le=65535)
    width: int = Field(default=640, gt=0, le=1920)
    height: int = Field(default=360, gt=0, le=1080)
    fps: int = Field(default=10, ge=1, le=30)
    gateway_config: str = "config/config.simulation.json"
    sitl: SitlSettings = Field(default_factory=SitlSettings)
    cameras: list[SimulationCamera] = Field(min_length=1, max_length=6)

    @field_validator("schema_version")
    @classmethod
    def schema_ok(cls, value: int) -> int:
        if value != 1:
            raise ValueError("schema_version must be 1")
        return value

    @field_validator("bind_host", "advertise_host")
    @classmethod
    def host_ok(cls, value: str) -> str:
        if value == "":
            return value
        if not _HOST.fullmatch(value) or ".." in value:
            raise ValueError("host must be empty or an IPv4 address")
        return value

    @field_validator("bind_interface")
    @classmethod
    def interface_ok(cls, value: str) -> str:
        if value and not _INTERFACE.fullmatch(value):
            raise ValueError("bind_interface is not a valid interface name")
        return value

    @field_validator("width", "height")
    @classmethod
    def even(cls, value: int) -> int:
        if value % 2:
            raise ValueError("dimensions must be even")
        return value

    @model_validator(mode="after")
    def ports_and_ids(self) -> "SimulationFile":
        ports = [
            self.api_port,
            self.rtsp_port,
            self.control_port,
            self.publisher_rtsp_port,
            self.publisher_control_port,
            self.sitl.flight_controller_port,
        ]
        if len(set(ports)) != len(ports):
            raise ValueError("api, rtsp, control, publisher, and flight-controller ports must be different")
        ids = [camera.id for camera in self.cameras]
        if len(set(ids)) != len(ids):
            raise ValueError("simulation camera ids must be unique")
        return self


def load_simulation(path: Path) -> SimulationFile:
    if not path.is_file():
        raise ConfigurationError(f"Simulation config is missing: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return SimulationFile.model_validate(payload)
    except (json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise ConfigurationError(f"simulation.json is invalid: {exc}") from exc


def load_camera_file(path: Path) -> list[CameraRecord]:
    if not path.is_file():
        raise ConfigurationError(f"Simulation camera registry is missing: {path}")
    try:
        document = CameraFile.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise ConfigurationError(f"cameras.simulation.json is invalid: {exc}") from exc
    if document.schema_version != 1:
        raise ConfigurationError("cameras.simulation.json schema_version must be 1")
    return document.cameras


def validate_sources(root: Path, simulation: SimulationFile, cameras: list[CameraRecord], secrets: SecretStore) -> None:
    by_id = {camera.id: camera for camera in cameras}
    if len(by_id) != len(cameras):
        raise ConfigurationError("cameras.simulation.json contains a duplicate camera id")
    configured = {camera.id for camera in simulation.cameras}
    if configured != set(by_id):
        raise ConfigurationError("simulation.json and cameras.simulation.json must list the same camera ids")
    for item in simulation.cameras:
        camera = by_id[item.id]
        if item.input == "rtsp":
            _reject_publisher_alias(camera, simulation.publisher_rtsp_port)
            continue
        _require_local_publisher(camera, simulation.publisher_rtsp_port)
        if secrets.camera(camera.credentials_ref).username:
            raise ConfigurationError(
                f"{camera.id} is generated locally and cannot use RTSP credentials. "
                "Leave credentials_ref empty, or set input to rtsp for a real camera."
            )
        if item.input == "file":
            resolve_media_file(root, item.file)


def resolve_media_file(root: Path, value: str) -> Path:
    raw = Path(value).expanduser()
    path = raw.resolve() if raw.is_absolute() else resolve_under_root(root, value)
    if not path.is_file():
        raise ConfigurationError(f"Video file is missing: {path}")
    return path


def resolve_bind_host(simulation: SimulationFile, lookup=None) -> str:
    if simulation.bind_interface:
        finder = lookup or lookup_interface_ipv4
        return finder(simulation.bind_interface)
    return simulation.bind_host or "0.0.0.0"


def lookup_interface_ipv4(name: str) -> str:
    if not _INTERFACE.fullmatch(name):
        raise ConfigurationError("bind_interface is not a valid interface name")
    import subprocess

    if sys.platform == "darwin":
        completed = subprocess.run(["ipconfig", "getifaddr", name], capture_output=True, text=True, check=False)
        address = completed.stdout.strip()
    else:
        completed = subprocess.run(
            ["ip", "-4", "-o", "addr", "show", "dev", name],
            capture_output=True,
            text=True,
            check=False,
        )
        match = re.search(r"\binet (\d+\.\d+\.\d+\.\d+)/", completed.stdout)
        address = match.group(1) if match else ""
    if completed.returncode != 0 or not _HOST.fullmatch(address):
        raise ConfigurationError(
            f"Interface {name} has no IPv4 address. The simulation does not change network interfaces."
        )
    return address


def advertise_host_for(simulation: SimulationFile, bind_host: str) -> str:
    if simulation.advertise_host:
        return simulation.advertise_host
    if bind_host not in {"", "0.0.0.0", "::"}:
        return bind_host
    return ""


def generated_cameras(simulation: SimulationFile, cameras: list[CameraRecord]) -> list[CameraRecord]:
    by_id = {camera.id: camera for camera in cameras}
    selected = []
    for item in simulation.cameras:
        camera = by_id[item.id]
        if camera.enabled and item.input in {"pattern", "file"}:
            selected.append(camera)
    return selected


def render_publisher_config(camera_ids: list[str], rtsp_port: int, control_port: int) -> str:
    lines = [
        "logLevel: info",
        "logDestinations: [stdout]",
        "api: yes",
        f"apiAddress: 127.0.0.1:{control_port}",
        "rtsp: yes",
        f"rtspAddress: 127.0.0.1:{rtsp_port}",
        "rtspTransports: [tcp]",
        "rtmp: no",
        "hls: no",
        "webrtc: no",
        "srt: no",
        "moq: no",
        "playback: no",
        "paths:",
    ]
    for camera_id in camera_ids:
        lines.extend([f"  {camera_id}:", "    source: publisher", "    overridePublisher: yes"])
    return "\n".join(lines) + "\n"


def playback_host(bind_host: str) -> str:
    if bind_host in {"", "0.0.0.0", "::"}:
        return "127.0.0.1"
    return bind_host


def gateway_environment(
    base: dict[str, str],
    simulation: SimulationFile,
    bind_host: str,
    advertised: str,
) -> dict[str, str]:
    env = dict(base)
    env["UGV_CAMERAS_FILE"] = "config/cameras.simulation.json"
    env["UGV_MOSAIC_FILE"] = "config/mosaic.simulation.json"
    env["UGV_BIND_HOST"] = bind_host
    env["UGV_API_PORT"] = str(simulation.api_port)
    env["UGV_RTSP_PORT"] = str(simulation.rtsp_port)
    env["UGV_CONTROL_PORT"] = str(simulation.control_port)
    if simulation.gateway_config.strip():
        env["UGV_CONFIG_FILE"] = simulation.gateway_config.strip()
    else:
        env.pop("UGV_CONFIG_FILE", None)
    if bind_host in {"", "0.0.0.0", "::"}:
        env.pop("UGV_RTSP_BIND_HOST", None)
    else:
        env["UGV_RTSP_BIND_HOST"] = bind_host
    if advertised:
        env["UGV_ADVERTISE_HOST"] = advertised
    else:
        env.pop("UGV_ADVERTISE_HOST", None)
    return env


def ready_banner(
    host: str,
    api_port: int,
    rtsp_port: int,
    camera_ids: list[str],
    interfaces: list[tuple[str, str]] | None = None,
    *,
    mavlink_port: int | None = None,
    flight_controller_port: int | None = None,
) -> str:
    urls = playback_urls(host, rtsp_port, camera_ids)
    lines = ["Simulation ready.", f"API: http://{host}:{api_port}/docs", "", *urls, ""]
    for url in urls:
        lines.extend(player_commands(url))
        lines.append("")
    if host == "127.0.0.1":
        if interfaces:
            lines.append("From the G30, replace 127.0.0.1 with the Ethernet address on GR03 LAN0:")
            for name, address in interfaces:
                lines.append(f"  {name} {address}")
        else:
            lines.append("From the G30, replace 127.0.0.1 with this Mac's Ethernet address on GR03 LAN0.")
    else:
        lines.append(f"API and RTSP are bound to {host}. Use that address from the G30.")
    if mavlink_port is not None:
        lines.append(f"G30 MAVLink UDP: {host}:{mavlink_port} as system 255 or 254, component 190.")
    if flight_controller_port is not None:
        lines.append(f"Rover SITL reaches the gateway on UDP 127.0.0.1:{flight_controller_port} as system 1.")
    lines.append("Change the mosaic with PUT /api/v1/mosaic, then POST /api/v1/mosaic/start.")
    lines.append("This process does not change network interfaces.")
    return "\n".join(lines) + "\n"


def playback_urls(host: str, rtsp_port: int, camera_ids: list[str]) -> list[str]:
    urls = [f"rtsp://{host}:{rtsp_port}/camera/{camera_id}" for camera_id in camera_ids]
    urls.append(f"rtsp://{host}:{rtsp_port}/mosaic")
    return urls


def player_commands(url: str) -> list[str]:
    return [
        f"ffplay -rtsp_transport tcp {url}",
        f"vlc --rtsp-tcp {url}",
    ]


def parse_ifconfig(text: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    current = ""
    for line in text.splitlines():
        if line and not line[:1].isspace():
            current = line.split(":", 1)[0]
        stripped = line.strip()
        if not stripped.startswith("inet ") or not current or current.startswith("lo"):
            continue
        address = stripped.split()[1]
        if address != "127.0.0.1":
            found.append((current, address))
    return found


def _require_local_publisher(camera: CameraRecord, port: int) -> None:
    connection = camera.connection
    expected = f"/{camera.id}"
    if (
        connection.protocol != "rtsp"
        or connection.host != PUBLISHER_HOST
        or connection.port != port
        or connection.path != expected
    ):
        raise ConfigurationError(
            f"{camera.id} uses a generated input, so cameras.simulation.json must use "
            f"rtsp://{PUBLISHER_HOST}:{port}{expected}"
        )


def _reject_publisher_alias(camera: CameraRecord, port: int) -> None:
    connection = camera.connection
    if connection.host == PUBLISHER_HOST and connection.port == port:
        raise ConfigurationError(
            f"{camera.id} is set to a real RTSP input, but its address is the local pattern publisher."
        )
