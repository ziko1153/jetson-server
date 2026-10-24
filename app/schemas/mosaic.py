"""Mosaic configuration models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.camera import ScalingMode, require_camera_id

LayoutName = Literal[
    "single",
    "side_by_side",
    "three_focus",
    "grid_2x2",
    "five_3_over_2",
    "grid_3x2",
    "custom",
]


class MosaicOutput(BaseModel):
    width: int = Field(gt=0, le=3840)
    height: int = Field(gt=0, le=2160)
    fps: int = Field(gt=0, le=60)
    bitrate_kbps: int = Field(gt=0)
    codec: str = "h264"
    stream_name: str = "mosaic"

    @field_validator("codec")
    @classmethod
    def codec_ok(cls, value: str) -> str:
        normalized = value.lower()
        if normalized not in {"h264"}:
            raise ValueError("the mosaic output codec currently supported is h264")
        return normalized

    @field_validator("stream_name")
    @classmethod
    def name_ok(cls, value: str) -> str:
        if value != "mosaic":
            raise ValueError("the shared mosaic stream name is mosaic")
        return value

    @field_validator("width", "height")
    @classmethod
    def even(cls, value: int) -> int:
        if value % 2:
            raise ValueError("dimensions must be even")
        return value


class MosaicTile(BaseModel):
    camera_id: str
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    z: int = 0
    visible: bool = True
    scaling: ScalingMode = "fit"
    source_profile: Literal["low", "medium", "high"] | None = None
    preferred_source_fps: int | None = Field(default=None, gt=0, le=60)

    @field_validator("camera_id")
    @classmethod
    def camera_ok(cls, value: str) -> str:
        return require_camera_id(value)

    @field_validator("width", "height", "x", "y")
    @classmethod
    def even(cls, value: int) -> int:
        if value % 2:
            raise ValueError("tile geometry must use even pixels")
        return value


class MosaicDocument(BaseModel):
    schema_version: int = 1
    revision: int = Field(ge=1)
    owner: str | None = None
    enabled: bool = True
    layout: LayoutName
    output: MosaicOutput
    camera_ids: list[str] = Field(default_factory=list)
    tiles: list[MosaicTile] | None = None

    @field_validator("owner")
    @classmethod
    def owner_ok(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned or len(cleaned) > 80:
            raise ValueError("owner must be 1 to 80 characters")
        return cleaned

    @field_validator("camera_ids")
    @classmethod
    def ids_ok(cls, value: list[str]) -> list[str]:
        return [require_camera_id(item) for item in value]


class MosaicUpdate(BaseModel):
    expected_revision: int | None = Field(default=None, ge=1)
    owner: str | None = None
    enabled: bool | None = None
    layout: LayoutName
    output: MosaicOutput
    camera_ids: list[str] | None = None
    tiles: list[MosaicTile] | None = None


class MosaicView(BaseModel):
    revision: int
    owner: str | None
    enabled: bool
    layout: str
    output: MosaicOutput
    camera_ids: list[str]
    tiles: list[MosaicTile]
    gateway_stream_url: str
    running: bool
    reconnect_required: bool
    effective_output: MosaicOutput
    adjustments: list[str] = Field(default_factory=list)


class MosaicStatus(BaseModel):
    running: bool
    reconnect_required: bool
    revision: int
    owner: str | None
    stream_url: str
    pid: int | None
    restarts: int
    error: str | None
    backend: str
    acceleration: str


class LayoutInfo(BaseModel):
    name: str
    camera_count: int
    description: str
