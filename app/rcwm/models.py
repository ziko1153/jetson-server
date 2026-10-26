"""RCWM settings and estimated axis state.

Angles are output-shaft degrees. Steps are an estimate from commanded pulses.
They are not encoder readings.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MotorConfig:
    enabled: bool = False
    reversed: bool = False
    steps_per_revolution: int = 1600
    gear_ratio: float = 1.0
    max_speed_dps: float | None = None
    max_accel: float | None = None
    max_decel: float | None = None
    min_angle: float | None = None
    max_angle: float | None = None
    home_angle: float | None = 0.0
    deadband_percent: int = 0

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "reversed": self.reversed,
            "steps_per_revolution": self.steps_per_revolution,
            "gear_ratio": self.gear_ratio,
            "max_speed_dps": self.max_speed_dps,
            "max_accel": self.max_accel,
            "max_decel": self.max_decel,
            "min_angle": self.min_angle,
            "max_angle": self.max_angle,
            "home_angle": self.home_angle,
            "deadband_percent": self.deadband_percent,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> MotorConfig:
        known = cls()
        values = known.to_dict()
        for key in values:
            if key in raw:
                values[key] = raw[key]
        return cls(**values)


@dataclass
class AxisView:
    enabled: bool = False
    referenced: bool = False
    reference_invalid: bool = True
    direction: int = 0
    fault: bool = False
    estimated_deg: float | None = None
    estimated_steps: int | None = None
    speed_limit: float | None = None
    accel_limit: float | None = None
    commanded_dps: float = 0.0
    current_dps: float = 0.0

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "referenced": self.referenced,
            "reference_invalid": self.reference_invalid,
            "direction": self.direction,
            "fault": self.fault,
            "estimated_deg": self.estimated_deg,
            "estimated_steps": self.estimated_steps,
            "speed_limit_dps": self.speed_limit,
            "accel_limit": self.accel_limit,
            "commanded_dps": self.commanded_dps,
            "current_dps": self.current_dps,
            "position": "estimate" if self.referenced else "unknown",
        }


@dataclass
class MountView:
    connected: bool
    boot_id: int | None
    energized: bool
    active_tilt: int
    fault_code: int
    axes: dict[int, AxisView]

    def to_public(self) -> dict:
        names = {1: "pan", 2: "tilt_1", 3: "tilt_2"}
        return {
            "connected": self.connected,
            "boot_id": self.boot_id,
            "energized": self.energized,
            "active_tilt": names.get(self.active_tilt, "none"),
            "fault_code": self.fault_code,
            "axes": {names[key]: value.to_dict() for key, value in self.axes.items()},
        }
