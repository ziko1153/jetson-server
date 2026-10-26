"""RCWM version 1 body carried inside MAVLink TUNNEL payload type 31000.

The layout matches the Kotlin ground station. Little-endian. Magic bytes are
``R`` ``C``. Changing this layout breaks the existing GCS decoder.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass

from app.rcwm.models import AxisView, MotorConfig

VERSION = 1
PAYLOAD_TYPE = 31000
HEADER = 8
CONFIG_BODY = 27
AXIS_BLOCK = 14
STATUS_HEAD = 6
STATUS_BODY = STATUS_HEAD + AXIS_BLOCK * 3

MAGIC = b"RC"
AXIS_PAN = 1
AXIS_TILT_1 = 2
AXIS_TILT_2 = 3
AXES = (AXIS_PAN, AXIS_TILT_1, AXIS_TILT_2)

STATUS = 1
CONFIG_READ = 2
CONFIG_WRITE = 3
SELECT = 4
MOTION = 5
STOP = 6
HOME = 7
POSITIONS = 8
FAULTS = 9
OWNERSHIP = 10
RELEASE = 11

REQUEST = 0
ACCEPTED = 1
APPLIED = 2
REJECTED = 3
TIMEOUT = 4
UNSUPPORTED = 5
UNAVAILABLE = 6
SAFETY = 7

FAULT_NONE = 0
FAULT_CONTROLLER = 1
FAULT_ESP32_SILENT = 2
FAULT_DRIVER = 3
FAULT_REFERENCE = 4
FAULT_CONFIG = 5
FAULT_OWNERSHIP = 6
FAULT_TIMEOUT = 7
FAULT_POSITION = 8

U16_NONE = 0xFFFF
UNKNOWN_I32 = 0x7FFFFFFF
ANGLE_UNSET = -32768
CENTI = 100.0
GEAR_SCALE = 1000.0

FLAG_ESP32 = 1
FLAG_GATEWAY = 2
FLAG_STOPPED = 4
FLAG_MOVING = 8
FLAG_CLEAR = 16
FLAG_FAULT = 32
FLAG_DEGRADED = 64

AXIS_ENABLED = 1
AXIS_REFERENCED = 2
AXIS_REFERENCING = 4
AXIS_INVALID = 8
AXIS_POS = 16
AXIS_NEG = 32
AXIS_FAULT = 64

CFG_ENABLED = 1
CFG_REVERSED = 2
CFG_PRESERVED = 4


@dataclass(frozen=True)
class Request:
    opcode: int
    request_id: int
    axis: int
    result: int
    payload: bytes


def parse_request(body: bytes) -> Request | None:
    if len(body) < HEADER or body[0:2] != MAGIC or body[2] != VERSION:
        return None
    if body[7] > SAFETY:
        return None
    return Request(
        opcode=body[3],
        request_id=int.from_bytes(body[4:6], "little"),
        axis=body[6],
        result=body[7],
        payload=body[HEADER:],
    )


def encode_header(opcode: int, request_id: int, axis: int, result: int) -> bytes:
    raw = bytearray(HEADER)
    raw[0:2] = MAGIC
    raw[2] = VERSION
    raw[3] = opcode
    raw[4:6] = (request_id & 0xFFFF).to_bytes(2, "little")
    raw[6] = axis & 0xFF
    raw[7] = result & 0xFF
    return bytes(raw)


def encode_ack(opcode: int, request_id: int, axis: int, result: int) -> bytes:
    return encode_header(opcode, request_id, axis, result)


def encode_motion(pan: float, tilt1: float, tilt2: float) -> bytes:
    return struct.pack("<fff", float(pan), float(tilt1), float(tilt2))


def decode_motion(payload: bytes) -> tuple[float, float, float] | None:
    if len(payload) < 12:
        return None
    return struct.unpack("<fff", payload[:12])


def encode_config(config: MotorConfig, preserved: bool = False) -> bytes:
    raw = bytearray(CONFIG_BODY)
    flags = 0
    if config.enabled:
        flags |= CFG_ENABLED
    if config.reversed:
        flags |= CFG_REVERSED
    if preserved:
        flags |= CFG_PRESERVED
    raw[0] = flags
    # byte[1] was polarity; reserved (0). Hardware enable polarity is set on the controller.
    _put_u16(raw, 2, config.steps_per_revolution)
    gear = int(round(config.gear_ratio * GEAR_SCALE))
    _put_u32(raw, 4, gear)
    _put_u16(raw, 8, _speed16(config.max_speed_dps))
    _put_u16(raw, 10, _speed16(config.max_accel))
    _put_u16(raw, 12, _speed16(config.max_decel))
    _put_i16(raw, 14, _angle16(config.min_angle))
    _put_i16(raw, 16, _angle16(config.max_angle))
    _put_i16(raw, 18, _angle16(config.home_angle))
    raw[20] = config.deadband_percent & 0xFF
    # bytes 21..26 were control timeout, STEP pulse, DIR setup. Reserved (0).
    # Hardware timing stays on the controller.
    return bytes(raw)


def decode_config(payload: bytes) -> tuple[MotorConfig, bool] | None:
    if len(payload) < CONFIG_BODY:
        return None
    flags = payload[0]
    config = MotorConfig(
        enabled=bool(flags & CFG_ENABLED),
        reversed=bool(flags & CFG_REVERSED),
        steps_per_revolution=_u16(payload, 2),
        gear_ratio=_u32(payload, 4) / GEAR_SCALE,
        max_speed_dps=_from_speed(_u16(payload, 8)),
        max_accel=_from_speed(_u16(payload, 10)),
        max_decel=_from_speed(_u16(payload, 12)),
        min_angle=_from_angle(_i16(payload, 14)),
        max_angle=_from_angle(_i16(payload, 16)),
        home_angle=_from_angle(_i16(payload, 18)),
        deadband_percent=payload[20],
    )
    return config, bool(flags & CFG_PRESERVED)


def encode_status_body(
    *,
    esp32_up: bool,
    gateway_up: bool,
    moving: bool,
    stopped: bool,
    safety_clear: bool,
    safety_fault: bool,
    degraded: bool,
    active_tilt: int,
    owner_system_id: int,
    fault_code: int,
    axes: dict[int, AxisView],
) -> bytes:
    raw = bytearray(STATUS_BODY)
    flags = 0
    if esp32_up:
        flags |= FLAG_ESP32
    if gateway_up:
        flags |= FLAG_GATEWAY
    if stopped:
        flags |= FLAG_STOPPED
    if moving:
        flags |= FLAG_MOVING
    if safety_clear:
        flags |= FLAG_CLEAR
    if safety_fault:
        flags |= FLAG_FAULT
    if degraded:
        flags |= FLAG_DEGRADED
    _put_u16(raw, 0, flags)
    raw[2] = active_tilt & 0xFF
    raw[3] = owner_system_id & 0xFF
    raw[4] = VERSION
    raw[5] = fault_code & 0xFF
    for index, axis_id in enumerate(AXES):
        _put_axis(raw, STATUS_HEAD + index * AXIS_BLOCK, axes[axis_id])
    return bytes(raw)


def encode_status(request_id: int, opcode: int, body: bytes) -> bytes:
    return encode_header(opcode, request_id, 0, APPLIED) + body


def decode_status_body(payload: bytes) -> dict | None:
    if len(payload) < STATUS_BODY:
        return None
    flags = _u16(payload, 0)
    axes = {}
    for index, axis_id in enumerate(AXES):
        axes[axis_id] = _read_axis(payload, STATUS_HEAD + index * AXIS_BLOCK)
    return {
        "esp32_up": bool(flags & FLAG_ESP32),
        "gateway_up": bool(flags & FLAG_GATEWAY),
        "stopped": bool(flags & FLAG_STOPPED),
        "moving": bool(flags & FLAG_MOVING),
        "safety_clear": bool(flags & FLAG_CLEAR),
        "safety_fault": bool(flags & FLAG_FAULT),
        "degraded": bool(flags & FLAG_DEGRADED),
        "active_tilt": payload[2],
        "owner_system_id": payload[3],
        "protocol_version": payload[4],
        "fault_code": payload[5],
        "axes": axes,
    }


def output_degrees(steps: int, steps_per_revolution: int, gear_ratio: float) -> float:
    return steps / (steps_per_revolution * gear_ratio) * 360.0


def _put_axis(raw: bytearray, at: int, axis: AxisView) -> None:
    flags = 0
    if axis.enabled:
        flags |= AXIS_ENABLED
    if axis.reference_invalid:
        flags |= AXIS_INVALID
    elif axis.referenced:
        flags |= AXIS_REFERENCED
    if axis.direction > 0:
        flags |= AXIS_POS
    elif axis.direction < 0:
        flags |= AXIS_NEG
    if axis.fault:
        flags |= AXIS_FAULT
    raw[at] = flags
    raw[at + 1] = 0
    degrees = UNKNOWN_I32 if axis.estimated_deg is None else _round_half_away(axis.estimated_deg * CENTI)
    steps = UNKNOWN_I32 if axis.estimated_steps is None else int(axis.estimated_steps)
    _put_i32(raw, at + 2, degrees)
    _put_i32(raw, at + 6, steps)
    _put_u16(raw, at + 10, _speed16(axis.speed_limit))
    _put_u16(raw, at + 12, _speed16(axis.accel_limit))


def _read_axis(payload: bytes, at: int) -> AxisView:
    flags = payload[at]
    if flags & AXIS_POS and not flags & AXIS_NEG:
        direction = 1
    elif flags & AXIS_NEG and not flags & AXIS_POS:
        direction = -1
    else:
        direction = 0
    degrees = _i32(payload, at + 2)
    steps = _i32(payload, at + 6)
    return AxisView(
        enabled=bool(flags & AXIS_ENABLED),
        referenced=bool(flags & AXIS_REFERENCED) and not bool(flags & AXIS_INVALID),
        reference_invalid=bool(flags & AXIS_INVALID),
        direction=direction,
        fault=bool(flags & AXIS_FAULT),
        estimated_deg=None if degrees == UNKNOWN_I32 else degrees / CENTI,
        estimated_steps=None if steps == UNKNOWN_I32 else steps,
        speed_limit=_from_speed(_u16(payload, at + 10)),
        accel_limit=_from_speed(_u16(payload, at + 12)),
    )


def _speed16(value: float | None) -> int:
    if value is None or not math.isfinite(value):
        return U16_NONE
    return max(0, min(U16_NONE - 1, _round_half_away(value * CENTI)))


def _from_speed(raw: int) -> float | None:
    if raw == U16_NONE:
        return None
    return raw / CENTI


def _angle16(value: float | None) -> int:
    if value is None or not math.isfinite(value):
        return ANGLE_UNSET
    return max(-32767, min(32767, _round_half_away(value * CENTI)))


def _from_angle(raw: int) -> float | None:
    if raw == ANGLE_UNSET:
        return None
    return raw / CENTI


def _round_half_away(value: float) -> int:
    if value >= 0:
        return int(math.floor(value + 0.5))
    return int(math.ceil(value - 0.5))


def _u16(payload: bytes, at: int) -> int:
    return payload[at] | (payload[at + 1] << 8)


def _i16(payload: bytes, at: int) -> int:
    value = _u16(payload, at)
    return value - 0x10000 if value & 0x8000 else value


def _u32(payload: bytes, at: int) -> int:
    return int.from_bytes(payload[at : at + 4], "little")


def _i32(payload: bytes, at: int) -> int:
    return int.from_bytes(payload[at : at + 4], "little", signed=True)


def _put_u16(raw: bytearray, at: int, value: int) -> None:
    raw[at : at + 2] = (value & 0xFFFF).to_bytes(2, "little")


def _put_i16(raw: bytearray, at: int, value: int) -> None:
    _put_u16(raw, at, value)


def _put_u32(raw: bytearray, at: int, value: int) -> None:
    raw[at : at + 4] = (value & 0xFFFFFFFF).to_bytes(4, "little")


def _put_i32(raw: bytearray, at: int, value: int) -> None:
    raw[at : at + 4] = (value & 0xFFFFFFFF).to_bytes(4, "little", signed=False)
