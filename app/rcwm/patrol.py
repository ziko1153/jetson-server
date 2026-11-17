"""Pan patrol: wire format and the simulated ESP32 patrol.

The ESP32 runs patrol itself, so it continues when the ground station link
drops. While it runs, joystick pan is refused and joystick tilt still works.
The range must sit inside the configured pan soft limits.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass

BLOCK = 8
ACTION_STOP = 0
ACTION_START = 1

REASON_NONE = 0
REASON_OPERATOR = 1
REASON_RANGE = 2
REASON_NO_LIMITS = 3
REASON_OUTSIDE_LIMITS = 4
REASON_SPEED = 5
REASON_NOT_READY = 6
REASON_NO_REFERENCE = 7
REASON_DISABLED = 8

MIN_SPAN_DEG = 1.0
EDGE_MARGIN_DEG = 0.1
TURN_DEG = 0.2


@dataclass(frozen=True)
class PatrolView:
    active: bool = False
    reason: int = REASON_NONE
    min_deg: float = 0.0
    max_deg: float = 0.0
    speed_dps: float = 0.0

    def to_dict(self) -> dict:
        return {
            "active": self.active,
            "reason": self.reason,
            "min_deg": self.min_deg,
            "max_deg": self.max_deg,
            "speed_dps": self.speed_dps,
        }


def encode_block(view: PatrolView) -> bytes:
    return struct.pack(
        "<BBhhH",
        1 if view.active else 0,
        view.reason & 0xFF,
        _centi(view.min_deg),
        _centi(view.max_deg),
        max(0, min(65534, round(view.speed_dps * 100))),
    )


def decode_block(raw: bytes) -> PatrolView | None:
    if len(raw) < BLOCK:
        return None
    active, reason, low, high, speed = struct.unpack_from("<BBhhH", raw)
    return PatrolView(bool(active), reason, low / 100.0, high / 100.0, speed / 100.0)


def valid_request(payload: bytes) -> bool:
    if not payload:
        return False
    if payload[0] == ACTION_STOP:
        return True
    return payload[0] == ACTION_START and len(payload) >= 7


def start_payload(min_deg: float, max_deg: float, speed_dps: float) -> bytes:
    return struct.pack("<BhhH", ACTION_START, _centi(min_deg), _centi(max_deg), round(speed_dps * 100))


def parse_start(payload: bytes) -> tuple[float, float, float]:
    _action, low, high, speed = struct.unpack_from("<BhhH", payload)
    return low / 100.0, high / 100.0, speed / 100.0


class SimulatedPatrol:
    """Mirror of firmware/esp32/include/patrol.hpp for the in-process ESP32."""

    def __init__(self) -> None:
        self.view = PatrolView()
        self._direction = 1

    @property
    def active(self) -> bool:
        return self.view.active

    def start(self, pan, min_deg: float, max_deg: float, speed_dps: float, position: float | None) -> int:
        reason = check(pan, min_deg, max_deg, speed_dps)
        if reason != REASON_NONE:
            return reason
        pos = position or 0.0
        self._direction = 1 if (max_deg - pos) >= (pos - min_deg) else -1
        self.view = PatrolView(True, REASON_NONE, min_deg, max_deg, speed_dps)
        return REASON_NONE

    def stop(self, pan, reason: int) -> None:
        if not self.view.active:
            return
        self.view = PatrolView(False, reason, self.view.min_deg, self.view.max_deg, self.view.speed_dps)
        pan.commanded_dps = 0.0

    def rate(self, pan, position: float | None) -> float | None:
        """Pan rate for this tick, or None when patrol stopped itself."""
        view = self.view
        reason = check(pan, view.min_deg, view.max_deg, view.speed_dps)
        if reason != REASON_NONE or position is None:
            self.stop(pan, reason or REASON_NO_REFERENCE)
            return None
        low = view.min_deg + EDGE_MARGIN_DEG
        high = view.max_deg - EDGE_MARGIN_DEG
        room = high - position if self._direction > 0 else position - low
        if room <= TURN_DEG:
            self._direction = -self._direction
            room = high - position if self._direction > 0 else position - low
        if room <= 0:
            return 0.0
        allow = math.sqrt(pan.config.max_decel * room)
        return self._direction * min(view.speed_dps, allow)


def check(pan, min_deg: float, max_deg: float, speed_dps: float) -> int:
    config = pan.config
    if not config.enabled or not config.max_speed_dps or not config.max_accel or not config.max_decel:
        return REASON_NOT_READY
    if not pan.referenced or pan.reference_invalid:
        return REASON_NO_REFERENCE
    if config.min_angle is None or config.max_angle is None:
        return REASON_NO_LIMITS
    if not (math.isfinite(min_deg) and math.isfinite(max_deg)) or max_deg - min_deg < MIN_SPAN_DEG:
        return REASON_RANGE
    if min_deg < config.min_angle or max_deg > config.max_angle:
        return REASON_OUTSIDE_LIMITS
    if not math.isfinite(speed_dps) or speed_dps <= 0 or speed_dps > config.max_speed_dps:
        return REASON_SPEED
    return REASON_NONE


def _centi(degrees: float) -> int:
    return max(-32767, min(32767, round(degrees * 100)))
