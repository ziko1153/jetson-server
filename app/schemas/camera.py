"""Camera registry and configuration models."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

CAMERA_ID = re.compile(r"^CAM-\d{3}$")
HOST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-]{0,252}$")
PATH = re.compile(r"^/[A-Za-z0-9._~!$&'()*+,;=:@%/-]*$")
DriverName = Literal["auto", "onvif", "vendor", "readonly_rtsp"]
ProfileName = Literal["low", "medium", "high", "custom"]
ScalingMode = Literal["fit", "fill", "stretch"]


def require_camera_id(value: str) -> str:
    if not CAMERA_ID.fullmatch(value):
        raise ValueError("camera id must look like CAM-001")
    return value


class ConnectionSettings(BaseModel):
    host: str
    port: int = Field(default=554, ge=1, le=65535)
    protocol: Literal["rtsp", "rtsps"] = "rtsp"
    path: str = "/"
    sub_path: str | None = None
    onvif_port: int = Field(default=80, ge=1, le=65535)
    onvif_path: str = "/onvif/device_service"

    @field_validator("host")
    @classmethod
    def host_ok(cls, value: str) -> str:
        if not HOST.fullmatch(value) or ".." in value:
            raise ValueError("host must be a hostname or IPv4 address")
        return value

    @field_validator("path", "onvif_path")
    @classmethod
    def path_ok(cls, value: str) -> str:
        if not PATH.fullmatch(value) or ".." in value:
            raise ValueError("path must start with / and cannot contain '..'")
        return value

    @field_validator("sub_path")
    @classmethod
    def sub_path_ok(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        if not PATH.fullmatch(value) or ".." in value:
            raise ValueError("sub_path must start with / and cannot contain '..'")
        return value


class GatewayOverrides(BaseModel):
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    fps: int | None = Field(default=None, gt=0, le=60)
    bitrate_kbps: int | None = Field(default=None, gt=0)
    codec: str | None = None


class CameraConfiguration(BaseModel):
    driver: DriverName = "auto"
    profile: ProfileName = "medium"
    gateway_overrides: GatewayOverrides | None = None


class CameraRecord(BaseModel):
    id: str
    name: str = Field(min_length=1, max_length=80)
    enabled: bool = True
    manufacturer: str | None = None
    model: str | None = None
    connection: ConnectionSettings
    configuration: CameraConfiguration = Field(default_factory=CameraConfiguration)
    credentials_ref: str | None = None

    @field_validator("id")
    @classmethod
    def id_ok(cls, value: str) -> str:
        return require_camera_id(value)

    @field_validator("name", "manufacturer", "model")
    @classmethod
    def text_ok(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned or any(ord(char) < 32 for char in cleaned):
            raise ValueError("text fields cannot be blank or contain control characters")
        return cleaned


class CameraFile(BaseModel):
    schema_version: int = 1
    cameras: list[CameraRecord]


class CameraPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    enabled: bool | None = None
    manufacturer: str | None = None
    model: str | None = None
    host: str | None = None
    port: int | None = Field(default=None, ge=1, le=65535)
    protocol: Literal["rtsp", "rtsps"] | None = None
    path: str | None = None
    sub_path: str | None = None
    onvif_port: int | None = Field(default=None, ge=1, le=65535)
    onvif_path: str | None = None
    driver: DriverName | None = None
    profile: ProfileName | None = None


class Resolution(BaseModel):
    width: int
    height: int


class CapabilityReport(BaseModel):
    camera_id: str
    source: Literal["unknown", "onvif", "rtsp_probe", "vendor"] = "unknown"
    probed_at: str | None = None
    codecs: list[str] | None = None
    resolutions: list[Resolution] | None = None
    frame_rates: list[float] | None = None
    bitrate_kbps_min: int | None = None
    bitrate_kbps_max: int | None = None
    encoder_profiles: list[str] | None = None
    configuration_supported: bool = False
    limitations: list[str] = Field(default_factory=list)
    detected_width: int | None = None
    detected_height: int | None = None
    detected_fps: float | None = None
    detected_bitrate_kbps: float | None = None
    detected_codec: str | None = None


class PhysicalSettings(BaseModel):
    supported: bool = False
    source: str = "unknown"
    codec: str | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    bitrate_kbps: int | None = None
    encoding_profile: str | None = None
    keyframe_interval: int | None = None
    stream_profile: str | None = None


class SettingsUpdate(BaseModel):
    target: Literal["physical", "gateway"] = "physical"
    codec: str | None = None
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    fps: int | None = Field(default=None, gt=0, le=60)
    bitrate_kbps: int | None = Field(default=None, gt=0)
    encoding_profile: str | None = None
    keyframe_interval: int | None = Field(default=None, gt=0, le=300)
    stream_profile: str | None = None
    allow_gateway_processing: bool = False


class SettingsResponse(BaseModel):
    camera_id: str
    physical: PhysicalSettings
    gateway_profile: str
    gateway_overrides: GatewayOverrides | None
    applied_to: str | None = None
    note: str


class CameraStatus(BaseModel):
    camera_id: str
    enabled: bool
    network_reachable: bool | None
    connection_status: Literal["unknown", "online", "offline"]
    last_success_at: str | None
    stream_phase: str
    last_error: str | None = None


class CameraView(BaseModel):
    id: str
    name: str
    enabled: bool
    manufacturer: str | None
    model: str | None
    connection: ConnectionSettings
    driver: str
    profile: str
    connection_status: str
    network_reachable: bool | None
    last_success_at: str | None
    stream_phase: str
    gateway_stream_url: str
    direct_stream_url: str
    capabilities_known: bool
    backup_stream_url: str
