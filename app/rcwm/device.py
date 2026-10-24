"""In-process ESP32 used on macOS and in tests.

It speaks the serial protocol and estimates position from commanded steps.
It does not pulse GPIO. A restarted device drops its reference.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from app.rcwm.models import AxisView, MotorConfig, MountView
from app.rcwm.protocol import (
    APPLIED,
    AXES,
    FAULT_NONE,
    FAULT_REFERENCE,
    FAULT_TIMEOUT,
    REJECTED,
    SAFETY,
    UNSUPPORTED,
    encode_config,
    encode_status_body,
    output_degrees,
)
from app.rcwm.serial_protocol import (
    ACK,
    CONFIG_GET,
    CONFIG_REPLY,
    CONFIG_SET,
    HELLO,
    HELLO_ACK,
    MOTION,
    PING,
    PONG,
    SELECT,
    SET_HOME,
    STATUS,
    STATUS_REQ,
    STOP,
    Frame,
    pop_frames,
)
from app.rcwm.validate import validate_motor

DEFAULT_LINK_TIMEOUT_S = 0.5


@dataclass
class _Axis:
    config: MotorConfig = field(default_factory=MotorConfig)
    referenced: bool = False
    reference_invalid: bool = True
    steps: int | None = None
    residual: float = 0.0
    commanded_dps: float = 0.0
    current_dps: float = 0.0


class Esp32Device:
    def __init__(self, clock=None) -> None:
        self._clock = clock or time.monotonic
        self.boot_id = 1
        self.axes = {axis_id: _Axis() for axis_id in AXES}
        self.active_tilt = 0
        self.energized = False
        self.fault_code = FAULT_NONE
        self.last_motion = self._clock()
        self._buffer = bytearray()
        self.motion_frames = 0

    def restart(self) -> None:
        self.boot_id = (self.boot_id + 1) & 0xFFFFFFFF
        self.active_tilt = 0
        self.energized = False
        self.fault_code = FAULT_NONE
        for axis in self.axes.values():
            axis.referenced = False
            axis.reference_invalid = True
            axis.steps = None
            axis.residual = 0.0
            axis.commanded_dps = 0.0
            axis.current_dps = 0.0

    def handle(self, frame: bytes) -> list[Frame]:
        self._buffer.extend(frame)
        replies: list[Frame] = []
        for parsed in pop_frames(self._buffer):
            replies.extend(self._dispatch(parsed))
        return replies

    def advance(self, dt: float) -> None:
        if dt < 0:
            return
        if self._moving() and self._clock() - self.last_motion > self._timeout():
            self._halt(immediate=True)
            self.energized = False
            self.fault_code = FAULT_TIMEOUT
            return
        for axis in self.axes.values():
            axis.current_dps = _ramp(axis, dt)
            self._integrate(axis, dt)

    def view(self) -> MountView:
        return MountView(
            connected=True,
            boot_id=self.boot_id,
            energized=self.energized,
            active_tilt=self.active_tilt,
            fault_code=self.fault_code,
            axes={axis_id: self._axis_view(axis_id) for axis_id in AXES},
        )

    def _dispatch(self, frame: Frame) -> list[Frame]:
        kind = frame.msg_type
        if kind == HELLO:
            return [self._hello_ack(frame.sequence)]
        if kind == PING:
            return [Frame(PONG, frame.sequence, b"")]
        if kind == STATUS_REQ:
            return [self._status(frame.sequence)]
        if kind == CONFIG_GET:
            return self._config_get(frame)
        if kind == CONFIG_SET:
            return self._config_set(frame)
        if kind == SELECT:
            return self._select(frame)
        if kind == MOTION:
            return self._motion(frame)
        if kind == STOP:
            return self._stop(frame)
        if kind == SET_HOME:
            return self._home(frame)
        return [self._ack(frame, UNSUPPORTED, FAULT_NONE)]

    def _config_get(self, frame: Frame) -> list[Frame]:
        if not frame.payload:
            return [self._ack(frame, REJECTED, FAULT_NONE)]
        axis = self.axes.get(frame.payload[0])
        if axis is None:
            return [self._ack(frame, REJECTED, FAULT_NONE)]
        payload = bytes([frame.payload[0], APPLIED]) + encode_config(axis.config, preserved=axis.referenced)
        return [Frame(CONFIG_REPLY, frame.sequence, payload)]

    def _config_set(self, frame: Frame) -> list[Frame]:
        from app.rcwm.protocol import decode_config

        if len(frame.payload) < 1 + 27:
            return [self._ack(frame, REJECTED, FAULT_NONE)]
        axis_id = frame.payload[0]
        axis = self.axes.get(axis_id)
        decoded = decode_config(frame.payload[1:])
        if axis is None or decoded is None:
            return [self._ack(frame, REJECTED, FAULT_NONE)]
        config, preserved = decoded
        issues = validate_motor(config)
        if issues:
            return [self._ack(frame, REJECTED, 5)]
        changed = _kinematics_changed(axis.config, config)
        axis.config = config
        if changed and not preserved:
            axis.referenced = False
            axis.reference_invalid = True
            axis.steps = None
            axis.residual = 0.0
        if not config.enabled:
            axis.commanded_dps = 0.0
            axis.current_dps = 0.0
        payload = bytes([axis_id, APPLIED]) + encode_config(config, preserved=axis.referenced and not changed)
        return [self._ack(frame, APPLIED, FAULT_NONE), Frame(CONFIG_REPLY, frame.sequence, payload)]

    def _select(self, frame: Frame) -> list[Frame]:
        if not frame.payload or frame.payload[0] not in (2, 3):
            return [self._ack(frame, REJECTED, FAULT_NONE)]
        chosen = frame.payload[0]
        if self.active_tilt not in (0, chosen):
            previous = self.axes[self.active_tilt]
            previous.commanded_dps = 0.0
            previous.current_dps = 0.0
        self.active_tilt = chosen
        return [self._ack(frame, APPLIED, FAULT_NONE), self._status(frame.sequence)]

    def _motion(self, frame: Frame) -> list[Frame]:
        from app.rcwm.protocol import decode_motion

        rates = decode_motion(frame.payload)
        if rates is None:
            return [self._ack(frame, REJECTED, FAULT_NONE)]
        pan, tilt1, tilt2 = rates
        if tilt1 != 0 and tilt2 != 0:
            return [self._ack(frame, SAFETY, FAULT_NONE)]
        if tilt1 != 0 and self.active_tilt != 2:
            return [self._ack(frame, SAFETY, FAULT_NONE)]
        if tilt2 != 0 and self.active_tilt != 3:
            return [self._ack(frame, SAFETY, FAULT_NONE)]
        commanded = {1: pan, 2: tilt1, 3: tilt2}
        for axis_id, rate in commanded.items():
            refusal = self._accept_rate(axis_id, rate)
            if refusal is not None:
                return [self._ack(frame, SAFETY, refusal)]
        for axis_id, rate in commanded.items():
            self.axes[axis_id].commanded_dps = _deadband(self.axes[axis_id], rate)
        self.last_motion = self._clock()
        self.fault_code = FAULT_NONE
        self.motion_frames += 1
        if any(axis.commanded_dps != 0 for axis in self.axes.values()):
            self.energized = True
        return [self._ack(frame, APPLIED, FAULT_NONE), self._status(frame.sequence)]

    def _accept_rate(self, axis_id: int, rate: float) -> int | None:
        if rate == 0:
            return None
        axis = self.axes[axis_id]
        config = axis.config
        if not config.enabled or config.max_speed_dps is None or config.max_accel is None or config.max_decel is None:
            return FAULT_NONE
        if abs(rate) > config.max_speed_dps:
            return FAULT_NONE
        if axis.reference_invalid and (config.min_angle is not None or config.max_angle is not None):
            return FAULT_REFERENCE
        return None

    def _stop(self, frame: Frame) -> list[Frame]:
        self._halt(immediate=False)
        return [self._ack(frame, APPLIED, FAULT_NONE), self._status(frame.sequence)]

    def _home(self, frame: Frame) -> list[Frame]:
        if not frame.payload:
            return [self._ack(frame, REJECTED, FAULT_NONE)]
        axis = self.axes.get(frame.payload[0])
        if axis is None:
            return [self._ack(frame, REJECTED, FAULT_NONE)]
        if abs(axis.commanded_dps) > 1e-6 or abs(axis.current_dps) > 1e-3:
            return [self._ack(frame, SAFETY, FAULT_NONE)]
        if axis.config.home_angle is None:
            return [self._ack(frame, REJECTED, FAULT_POSITION)]
        axis.steps = _steps_for(axis.config.home_angle, axis.config)
        axis.residual = 0.0
        axis.referenced = True
        axis.reference_invalid = False
        self.fault_code = FAULT_NONE
        return [self._ack(frame, APPLIED, FAULT_NONE), self._status(frame.sequence)]

    def _halt(self, immediate: bool) -> None:
        for axis in self.axes.values():
            axis.commanded_dps = 0.0
            if immediate:
                axis.current_dps = 0.0

    def _moving(self) -> bool:
        return any(abs(axis.commanded_dps) > 1e-6 or abs(axis.current_dps) > 1e-3 for axis in self.axes.values())

    def _timeout(self) -> float:
        configured = [
            axis.config.control_timeout_ms
            for axis in self.axes.values()
            if axis.config.control_timeout_ms is not None
        ]
        if not configured:
            return DEFAULT_LINK_TIMEOUT_S
        return min(configured) / 1000.0

    def _integrate(self, axis: _Axis, dt: float) -> None:
        if not axis.referenced or axis.steps is None or axis.current_dps == 0:
            return
        delta = axis.current_dps * dt
        angle = output_degrees(axis.steps, axis.config.steps_per_revolution, axis.config.gear_ratio)
        if axis.config.min_angle is not None and angle + delta < axis.config.min_angle and delta < 0:
            delta = 0.0
            axis.current_dps = 0.0
            axis.commanded_dps = 0.0
        if axis.config.max_angle is not None and angle + delta > axis.config.max_angle and delta > 0:
            delta = 0.0
            axis.current_dps = 0.0
            axis.commanded_dps = 0.0
        scale = axis.config.steps_per_revolution * axis.config.gear_ratio / 360.0
        axis.residual += delta * scale
        whole = int(axis.residual)
        if whole:
            axis.steps += whole
            axis.residual -= whole

    def _axis_view(self, axis_id: int) -> AxisView:
        axis = self.axes[axis_id]
        if axis.referenced and axis.steps is not None:
            degrees = output_degrees(axis.steps, axis.config.steps_per_revolution, axis.config.gear_ratio)
            steps = axis.steps
        else:
            degrees = None
            steps = None
        if axis.current_dps > 1e-3:
            direction = 1
        elif axis.current_dps < -1e-3:
            direction = -1
        else:
            direction = 0
        return AxisView(
            enabled=axis.config.enabled,
            referenced=axis.referenced,
            reference_invalid=axis.reference_invalid,
            direction=direction,
            fault=False,
            estimated_deg=degrees,
            estimated_steps=steps,
            speed_limit=axis.config.max_speed_dps,
            accel_limit=axis.config.max_accel,
            commanded_dps=axis.commanded_dps,
            current_dps=axis.current_dps,
        )

    def _status(self, sequence: int) -> Frame:
        view = self.view()
        moving = self._moving()
        body = encode_status_body(
            esp32_up=True,
            gateway_up=False,
            moving=moving,
            stopped=not moving,
            safety_clear=False,
            safety_fault=self.fault_code != FAULT_NONE,
            degraded=self.fault_code != FAULT_NONE,
            active_tilt=self.active_tilt,
            owner_system_id=0,
            fault_code=self.fault_code,
            axes=view.axes,
        )
        return Frame(STATUS, sequence, body)

    def _hello_ack(self, sequence: int) -> Frame:
        payload = self.boot_id.to_bytes(4, "little") + bytes([1 if self.energized else 0, 1])
        return Frame(HELLO_ACK, sequence, payload)

    def _ack(self, frame: Frame, result: int, fault: int) -> Frame:
        return Frame(ACK, frame.sequence, bytes([frame.msg_type, result, fault & 0xFF]))


def _ramp(axis: _Axis, dt: float) -> float:
    target = axis.commanded_dps
    current = axis.current_dps
    if target == current:
        return current
    speeding = abs(target) >= abs(current) and target * current >= 0
    limit = axis.config.max_accel if speeding else axis.config.max_decel
    if limit is None or limit <= 0:
        return current
    step = limit * dt
    if target > current:
        return min(target, current + step)
    return max(target, current - step)


def _deadband(axis: _Axis, rate: float) -> float:
    limit = axis.config.max_speed_dps
    if limit is None or axis.config.deadband_percent <= 0:
        return rate
    if abs(rate) < limit * axis.config.deadband_percent / 100.0:
        return 0.0
    return rate


def _kinematics_changed(current: MotorConfig, new: MotorConfig) -> bool:
    return (
        current.steps_per_revolution != new.steps_per_revolution
        or abs(current.gear_ratio - new.gear_ratio) > 1e-9
    )


def _steps_for(degrees: float, config: MotorConfig) -> int:
    return int(round(degrees / 360.0 * config.steps_per_revolution * config.gear_ratio))
