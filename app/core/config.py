"""Load and validate the human-edited JSON configuration."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from app.core.exceptions import ConfigurationError
from app.core.paths import project_root, resolve_under_root


class ServerSettings(BaseModel):
    host: str = "0.0.0.0"
    port: int = Field(default=8080, ge=1, le=65535)


class EnvironmentSettings(BaseModel):
    mode: str = "auto"
    hardware: str = "auto"
    media_backend: str = "auto"

    @field_validator("mode")
    @classmethod
    def mode_known(cls, value: str) -> str:
        if value != "auto":
            raise ValueError("environment.mode currently supports only auto")
        return value

    @field_validator("hardware", "media_backend")
    @classmethod
    def selection_known(cls, value: str) -> str:
        allowed = {"auto", "macos", "linux", "jetson"}
        if value not in allowed:
            raise ValueError(f"expected one of {sorted(allowed)}")
        return value


class AuthConfig(BaseModel):
    mode: str = "disabled"
    exempt_paths: list[str] = Field(default_factory=list)

    @field_validator("mode")
    @classmethod
    def mode_known(cls, value: str) -> str:
        if value not in {"disabled", "bearer"}:
            raise ValueError("auth.mode must be disabled or bearer")
        return value


_BIND_HOST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-]{0,252}$")


class StreamingSettings(BaseModel):
    rtsp_port: int = Field(default=8554, ge=1, le=65535)
    rtsp_bind_host: str = ""
    control_port: int = Field(default=9997, ge=1, le=65535)
    advertise_host: str = ""
    transport: str = "tcp"
    default_codec: str = "h264"
    manage_media_server: bool = True
    media_server_binary: str = ""
    media_server_version: str = "v1.21.2"
    playback_authentication: str = "disabled"

    @field_validator("rtsp_bind_host")
    @classmethod
    def bind_host_ok(cls, value: str) -> str:
        if value in {"", "0.0.0.0"}:
            return value
        if not _BIND_HOST.fullmatch(value) or ".." in value:
            raise ValueError("streaming.rtsp_bind_host must be empty or an IPv4 address")
        return value

    @field_validator("transport")
    @classmethod
    def transport_known(cls, value: str) -> str:
        if value != "tcp":
            raise ValueError("streaming.transport currently supports only tcp")
        return value

    @field_validator("default_codec", "playback_authentication")
    @classmethod
    def lower(cls, value: str) -> str:
        return value.lower()

    @field_validator("playback_authentication")
    @classmethod
    def playback_known(cls, value: str) -> str:
        if value not in {"disabled", "bearer"}:
            raise ValueError("playback_authentication must be disabled or bearer")
        return value


class HealthSettings(BaseModel):
    enabled: bool = False
    interval_seconds: float = Field(default=10, gt=0, le=3600)
    probe_timeout_seconds: float = Field(default=2, gt=0, le=30)


class LimitSettings(BaseModel):
    max_mosaic_pixels: int = Field(default=1920 * 1080, gt=0)
    max_mosaic_fps: int = Field(default=30, gt=0, le=60)
    max_mosaic_bitrate_kbps: int = Field(default=8000, gt=0)
    max_camera_streams: int = Field(default=6, gt=0, le=6)
    max_transcode_streams: int = Field(default=2, ge=0, le=6)
    mosaic_restart_attempts: int = Field(default=5, ge=0, le=20)
    mosaic_restart_backoff_seconds: float = Field(default=2, ge=0, le=60)
    subprocess_stop_timeout_seconds: float = Field(default=5, gt=0, le=30)


class LoggingSettings(BaseModel):
    level: str = "INFO"
    directory: str = "data/logs"


class StorageSettings(BaseModel):
    secrets_file: str = "config/secrets.json"
    audit_db: str = "data/audit.db"
    camera_state: str = "data/camera_state.json"
    backup_directory: str = "data/backups"


class FlightControllerSettings(BaseModel):
    transport: str = "none"
    serial_port: str = ""
    baud: int = Field(default=115200, ge=1200, le=4_000_000)
    udp_remote_host: str = ""
    udp_remote_port: int = Field(default=14550, ge=1, le=65535)
    udp_bind_host: str = "0.0.0.0"
    udp_bind_port: int = Field(default=14551, ge=0, le=65535)

    @field_validator("transport")
    @classmethod
    def transport_known(cls, value: str) -> str:
        if value not in {"none", "serial", "udp"}:
            raise ValueError("flight_controller.transport must be none, serial, or udp")
        return value


class MavlinkSettings(BaseModel):
    enabled: bool = True
    bind_host: str = "0.0.0.0"
    bind_port: int = Field(default=14550, ge=0, le=65535)
    system_id: int = Field(default=1, ge=1, le=255)
    companion_component_id: int = Field(default=191, ge=1, le=255)
    rcwm_component_id: int = Field(default=171, ge=1, le=255)
    autopilot_component_id: int = Field(default=1, ge=1, le=255)
    gcs_component_id: int = Field(default=190, ge=1, le=255)
    allowed_gcs_system_ids: list[int] = Field(default_factory=lambda: [255, 254])
    heartbeat_interval_seconds: float = Field(default=1.0, gt=0.2, le=10)
    peer_timeout_seconds: float = Field(default=10.0, gt=1, le=120)
    flight_controller: FlightControllerSettings = Field(default_factory=FlightControllerSettings)

    @field_validator("allowed_gcs_system_ids")
    @classmethod
    def gcs_ids(cls, value: list[int]) -> list[int]:
        if not value or any(item < 1 or item > 255 for item in value):
            raise ValueError("allowed_gcs_system_ids must be system ids from 1 to 255")
        return value


class RcwmSettings(BaseModel):
    enabled: bool = True
    transport: str = "simulation"
    serial_port: str = ""
    baud: int = Field(default=115200, ge=1200, le=4_000_000)
    allow_hardware_motion: bool = False
    owner_timeout_seconds: float = Field(default=1.5, gt=0.2, le=30)
    state_file: str = "data/rcwm_state.json"

    @field_validator("transport")
    @classmethod
    def transport_known(cls, value: str) -> str:
        if value not in {"simulation", "serial"}:
            raise ValueError("rcwm.transport must be simulation or serial")
        return value


class VideoProfile(BaseModel):
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps: int = Field(gt=0, le=60)
    bitrate_kbps: int = Field(gt=0)


class ProfileFile(BaseModel):
    schema_version: int = 1
    profiles: dict[str, VideoProfile]


class Settings(BaseModel):
    schema_version: int = 1
    server: ServerSettings = Field(default_factory=ServerSettings)
    environment: EnvironmentSettings = Field(default_factory=EnvironmentSettings)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    streaming: StreamingSettings = Field(default_factory=StreamingSettings)
    health: HealthSettings = Field(default_factory=HealthSettings)
    limits: LimitSettings = Field(default_factory=LimitSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    mavlink: MavlinkSettings = Field(default_factory=MavlinkSettings)
    rcwm: RcwmSettings = Field(default_factory=RcwmSettings)
    root: Path
    config_dir: Path
    profiles: dict[str, VideoProfile]

    model_config = {"arbitrary_types_allowed": True}

    @property
    def log_directory(self) -> Path:
        return resolve_under_root(self.root, self.logging.directory)

    @property
    def secrets_path(self) -> Path:
        return resolve_under_root(self.root, self.storage.secrets_file)

    @property
    def audit_path(self) -> Path:
        return resolve_under_root(self.root, self.storage.audit_db)

    @property
    def camera_state_path(self) -> Path:
        return resolve_under_root(self.root, self.storage.camera_state)

    @property
    def backup_directory(self) -> Path:
        return resolve_under_root(self.root, self.storage.backup_directory)

    @property
    def cameras_path(self) -> Path:
        return _configured_path(self.root, "UGV_CAMERAS_FILE", self.config_dir / "cameras.json")

    @property
    def mosaic_path(self) -> Path:
        return _configured_path(self.root, "UGV_MOSAIC_FILE", self.config_dir / "mosaic.json")

    @property
    def media_server_config_path(self) -> Path:
        return self.root / "data" / "mediamtx.yml"

    @property
    def rcwm_state_path(self) -> Path:
        return resolve_under_root(self.root, self.rcwm.state_file)


def load_settings(root: Path | None = None) -> Settings:
    root = (root or project_root()).resolve()
    config_dir = root / "config"
    raw = _read_json(_configured_path(root, "UGV_CONFIG_FILE", config_dir / "config.json"))
    profiles = ProfileFile.model_validate(_read_json(config_dir / "profiles.json"))
    _require_profiles(profiles)
    try:
        settings = Settings.model_validate(
            {**raw, "root": root, "config_dir": config_dir, "profiles": profiles.profiles}
        )
    except Exception as exc:
        raise ConfigurationError(f"config.json or profiles.json is invalid: {exc}") from exc
    return _apply_process_overrides(settings)


def _require_profiles(profiles: ProfileFile) -> None:
    missing = {"low", "medium", "high", "custom"} - set(profiles.profiles)
    if missing:
        raise ConfigurationError(f"profiles.json is missing {sorted(missing)}")
    if profiles.schema_version != 1:
        raise ConfigurationError("profiles.json schema_version must be 1")


def _apply_process_overrides(settings: Settings) -> Settings:
    server_updates = {}
    streaming_updates = {}
    if value := os.environ.get("UGV_BIND_HOST", "").strip():
        server_updates["host"] = _require_bind_host(value, "UGV_BIND_HOST")
    if value := os.environ.get("UGV_API_PORT", "").strip():
        server_updates["port"] = _require_port(value, "UGV_API_PORT")
    if value := os.environ.get("UGV_RTSP_PORT", "").strip():
        streaming_updates["rtsp_port"] = _require_port(value, "UGV_RTSP_PORT")
    if value := os.environ.get("UGV_CONTROL_PORT", "").strip():
        streaming_updates["control_port"] = _require_port(value, "UGV_CONTROL_PORT")
    if value := os.environ.get("UGV_RTSP_BIND_HOST", "").strip():
        streaming_updates["rtsp_bind_host"] = _require_bind_host(value, "UGV_RTSP_BIND_HOST")
    if value := os.environ.get("UGV_ADVERTISE_HOST", "").strip():
        streaming_updates["advertise_host"] = _require_bind_host(value, "UGV_ADVERTISE_HOST")
    if not server_updates and not streaming_updates:
        return settings
    update = {}
    if server_updates:
        update["server"] = settings.server.model_copy(update=server_updates)
    if streaming_updates:
        update["streaming"] = settings.streaming.model_copy(update=streaming_updates)
    return settings.model_copy(update=update)


def _configured_path(root: Path, env_name: str, default: Path) -> Path:
    raw = os.environ.get(env_name, "").strip()
    if not raw:
        return default
    path = resolve_under_root(root, raw)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ConfigurationError(f"{env_name} must stay inside the project directory") from exc
    return path


def _require_port(value: str, name: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer port") from exc
    if port < 1 or port > 65535:
        raise ConfigurationError(f"{name} must be a port from 1 to 65535")
    return port


def _require_bind_host(value: str, name: str) -> str:
    if value in {"0.0.0.0", "::"}:
        return value
    if not _BIND_HOST.fullmatch(value) or ".." in value:
        raise ConfigurationError(f"{name} must be an IPv4 address or 0.0.0.0")
    return value


def _read_json(path: Path) -> dict:
    if not path.is_file():
        raise ConfigurationError(f"Required configuration file is missing: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"{path.name} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigurationError(f"{path.name} must contain a JSON object")
    return data
