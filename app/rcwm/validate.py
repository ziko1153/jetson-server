"""Reject motor settings the RCWM protocol cannot represent.

Missing speed, acceleration, or deceleration stays missing. A motor cannot be
enabled until an operator sets those limits. Nothing here invents a safe speed.
"""

from __future__ import annotations

import math

from app.rcwm.models import MotorConfig

MAX_STEPS = 65535
MIN_GEAR = 0.001
MAX_GEAR = 1000.0
MAX_CENTI = 655.34
MAX_ANGLE = 327.66
MAX_DEADBAND = 50


def validate_motor(config: MotorConfig) -> list[str]:
    issues: list[str] = []
    if config.steps_per_revolution <= 0 or config.steps_per_revolution > MAX_STEPS:
        issues.append("Steps per revolution must be from 1 to 65535.")
    if not math.isfinite(config.gear_ratio) or config.gear_ratio < MIN_GEAR or config.gear_ratio > MAX_GEAR:
        issues.append("Gear ratio must be from 0.001 to 1000.")
    _speed(config.max_speed_dps, "Maximum speed", issues)
    _speed(config.max_accel, "Acceleration", issues)
    _speed(config.max_decel, "Deceleration", issues)
    _angle(config.min_angle, "Minimum angle", issues)
    _angle(config.max_angle, "Maximum angle", issues)
    _angle(config.home_angle, "Home angle", issues)
    if (
        config.min_angle is not None
        and config.max_angle is not None
        and math.isfinite(config.min_angle)
        and math.isfinite(config.max_angle)
        and config.min_angle >= config.max_angle
    ):
        issues.append("Minimum angle must be below the maximum angle.")
    if config.deadband_percent < 0 or config.deadband_percent > MAX_DEADBAND:
        issues.append("Deadband must be from 0 to 50 percent.")
    if config.enabled and (
        config.max_speed_dps is None or config.max_accel is None or config.max_decel is None
    ):
        issues.append("Enable the motor only after speed, acceleration, and deceleration are set.")
    return issues


def _speed(value: float | None, label: str, issues: list[str]) -> None:
    if value is None:
        return
    if not math.isfinite(value) or value <= 0 or value > MAX_CENTI:
        issues.append(f"{label} must be greater than zero and at most 655.34.")


def _angle(value: float | None, label: str, issues: list[str]) -> None:
    if value is None:
        return
    if not math.isfinite(value) or abs(value) > MAX_ANGLE:
        issues.append(f"{label} is outside the protocol range.")
