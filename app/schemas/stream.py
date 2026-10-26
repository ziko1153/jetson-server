"""Stream API models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class StreamStartRequest(BaseModel):
    mode: Literal["passthrough", "transcode"] = "passthrough"
    stream: Literal["main", "sub"] = "main"


class StreamStopRequest(BaseModel):
    force: bool = False


class StreamView(BaseModel):
    camera_id: str
    name: str
    phase: str
    mode: Literal["passthrough", "transcode", "none"]
    gateway_stream_url: str
    direct_stream_url: str
    readers: int | None = None
    online: bool | None = None
    error: str | None = None


class StreamMetrics(BaseModel):
    camera_id: str
    phase: str
    connected: bool | None
    configured_fps: float | None
    measured_fps: float | None
    configured_bitrate_kbps: int | None
    measured_bitrate_kbps: float | None
    codec: str | None
    width: int | None
    height: int | None
    last_frame_at: str | None
    uptime_seconds: float | None
    reconnect_count: int = 0
    error: str | None = None
    measurement_notes: list[str] = Field(default_factory=list)
