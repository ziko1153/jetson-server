"""Camera encoder and PTZ requests sent to the camera over ONVIF."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Resolution(BaseModel):
    width: int
    height: int


class EncoderOptionsView(BaseModel):
    codec: str
    resolutions: list[Resolution]
    frame_rates: list[int]
    bitrate_kbps_min: int | None = None
    bitrate_kbps_max: int | None = None
    gov_length_min: int | None = None
    gov_length_max: int | None = None
    profiles: list[str] = []


class StreamEncoderView(BaseModel):
    profile_token: str
    profile_name: str
    encoder_token: str
    role: Literal["main", "sub", "other"]
    path: str | None = None
    gateway_stream: Literal["main", "sub"] | None = None
    codec: str
    width: int
    height: int
    fps: int
    bitrate_kbps: int
    gov_length: int | None = None
    encoding_profile: str | None = None
    constant_bitrate: bool = False
    options: list[EncoderOptionsView] = []


class CameraEncodersView(BaseModel):
    camera_id: str
    source: Literal["onvif"] = "onvif"
    streams: list[StreamEncoderView]
    note: str = "These settings are stored in the camera. Every viewer of this camera sees the change."


class EncoderUpdate(BaseModel):
    codec: Literal["H264", "H265"] | None = None
    width: int | None = Field(default=None, gt=0, le=8192)
    height: int | None = Field(default=None, gt=0, le=8192)
    fps: int | None = Field(default=None, gt=0, le=120)
    bitrate_kbps: int | None = Field(default=None, gt=0, le=100_000)
    gov_length: int | None = Field(default=None, gt=0, le=1000)


class PtzView(BaseModel):
    camera_id: str
    supported: bool
    pan_tilt: bool = False
    zoom: bool = False
    home: bool = False
    note: str | None = None


class PtzMove(BaseModel):
    pan: float = Field(default=0, ge=-1, le=1)
    tilt: float = Field(default=0, ge=-1, le=1)
    zoom: float = Field(default=0, ge=-1, le=1)
    timeout_seconds: float = Field(default=1.0, ge=0.2, le=5)
