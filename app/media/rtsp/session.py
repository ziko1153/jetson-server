"""Per-camera stream session state."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class StreamSession:
    camera_id: str
    phase: str = "idle"
    mode: str = "none"
    stream: str = "main"
    error: str | None = None
    reconnect_count: int = 0
    started_monotonic: float | None = None
    last_online: bool | None = None
    last_bytes: int | None = None
    last_sample_at: float | None = None
