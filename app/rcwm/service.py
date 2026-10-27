"""RCWM session: GCS ownership, validation, and the ESP32 link.

Movement is not replayed after the ESP32 restarts. Software stop does not
replace a hardware emergency stop. Reported angles are estimates.
"""

from __future__ import annotations

import logging
import math
import threading

from app.core.config import RcwmSettings
from app.rcwm.device import Esp32Device
from app.rcwm.models import MotorConfig
from app.rcwm.mount import SerialMount, SimulatedMount
from app.rcwm.protocol import (
    APPLIED,
    AXES,
    CONFIG_READ,
    CONFIG_WRITE,
    FAULT_CONTROLLER,
    FAULT_ESP32_SILENT,
    FAULT_OWNERSHIP,
    FAULT_REFERENCE,
    HOME,
    MOTION,
    OWNERSHIP,
    POSITIONS,
    REJECTED,
    RELEASE,
    REQUEST,
    SELECT,
    STATUS,
    STOP,
    TIMEOUT,
    UNAVAILABLE,
    FAULTS,
    AxisView,
    Request,
    MOTION_MAX_AGE_MS,
    REASON_BOTH,
    REASON_CONFIG,
    REASON_MOVING,
    REASON_REFERENCE,
    REASON_SPEED,
    REASON_TILT,
    SAFETY,
    decode_config,
    decode_motion,
    decode_motion_stamp,
    encode_ack,
    encode_config,
    encode_header,
    encode_motion,
    encode_status,
    encode_status_body,
    parse_request,
)
from app.rcwm.serial_protocol import ACK, CONFIG_GET, CONFIG_REPLY, CONFIG_SET, MOTION as SERIAL_MOTION
from app.rcwm.serial_protocol import SELECT as SERIAL_SELECT
from app.rcwm.serial_protocol import SET_HOME, STOP as SERIAL_STOP
from app.rcwm.validate import validate_motor

logger = logging.getLogger("app.rcwm")

_AXIS_NAMES = {1: "pan", 2: "tilt_1", 3: "tilt_2"}


class RcwmService:
    def __init__(
        self,
        settings: RcwmSettings,
        state_path: Path,
        allowed_system_ids: tuple[int, ...] = (255, 254),
        clock=None,
    ) -> None:
        self._settings = settings
        self._state_path = state_path
        self._allowed = set(allowed_system_ids)
        self._clock = clock or __import__("time").monotonic
        self._device = Esp32Device(clock=self._clock)
        if settings.transport == "serial":
            self._mount = SerialMount(settings.serial_port, settings.baud)
        else:
            self._mount = SimulatedMount(self._device)
        self._configs = {axis_id: MotorConfig() for axis_id in AXES}
        self._owner = 0
        self._owner_seen = 0.0
        self._requests: dict[int, int] = {}
        self._boot: int | None = None
        self._config_sent = False
        self._started = False
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last = self._clock()

    def start(self, background: bool = True) -> None:
        if not self._settings.enabled or self._started:
            return
        self._mount.start()
        self._boot = self._mount.boot_id
        self._pull_config()
        self._started = True
        self._last = self._clock()
        if background:
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="rcwm", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2)
        self._thread = None
        self._mount.close()
        self._started = False

    def maintain(self) -> None:
        with self._lock:
            self._maintain()

    def handle(self, system_id: int, component_id: int, body: bytes) -> list[bytes]:
        del component_id
        with self._lock:
            request = parse_request(body)
            if request is None or request.result != REQUEST:
                return []
            if not self._settings.enabled or not self._started:
                return [encode_ack(request.opcode, request.request_id, request.axis, UNAVAILABLE)]
            if system_id not in self._allowed:
                return [encode_ack(request.opcode, request.request_id, request.axis, REJECTED)]
            if not self._fresh(system_id, request.request_id):
                return [encode_ack(request.opcode, request.request_id, request.axis, REJECTED)]
            self._maintain()
            reply = self._dispatch(system_id, request)
            if self._owner == system_id:
                self._owner_seen = self._clock()
            return reply

    def snapshot(self) -> dict:
        with self._lock:
            view = self._mount.view() if self._started else None
            connected = bool(view and view.connected)
            return {
                "enabled": self._settings.enabled,
                "running": self._started,
                "transport": self._settings.transport,
                "owner_system_id": self._owner,
                "positions": "estimates",
                "software_stop_is_hardware_estop": False,
                "reference_kept_across_restart": True,
                "esp32": {
                    "connected": connected,
                    "boot_id": None if view is None else view.boot_id,
                    "energized": bool(view and view.energized),
                    "last_error": self._mount.last_error,
                },
                "active_tilt": _AXIS_NAMES.get(view.active_tilt, "none") if view else "none",
                "fault_code": view.fault_code if view else FAULT_ESP32_SILENT,
                "axes": view.to_public()["axes"] if view else {},
            }

    def _loop(self) -> None:
        while not self._stop.wait(0.05):
            try:
                self.maintain()
            except Exception:
                logger.exception("RCWM maintenance failed")

    def _maintain(self) -> None:
        now = self._clock()
        dt = now - self._last
        self._last = now
        if dt > 0:
            self._mount.advance(dt)
        self._mount.poll()
        boot = self._mount.boot_id
        if boot != self._boot:
            self._boot = boot
            self._config_sent = False
        if self._mount.connected and not self._config_sent:
            self._pull_config()
            self._config_sent = True
        if self._owner and now - self._owner_seen > self._settings.owner_timeout_seconds:
            self._owner = 0
            self._exchange(SERIAL_STOP, b"")

    def _dispatch(self, system_id: int, request: Request) -> list[bytes]:
        opcode = request.opcode
        if opcode in (STATUS, POSITIONS, FAULTS):
            self._touch(system_id)
            return [self._status_packet(request)]
        if opcode == CONFIG_READ:
            return [self._read_config(request)]
        if opcode == CONFIG_WRITE:
            return [self._write_config(system_id, request)]
        if opcode == SELECT:
            return [self._select(system_id, request)]
        if opcode == MOTION:
            return [self._motion(system_id, request)]
        if opcode == STOP:
            return [self._stop_motion(request)]
        if opcode == HOME:
            return [self._home(system_id, request)]
        if opcode == OWNERSHIP:
            return [self._take_ownership(system_id, request)]
        if opcode == RELEASE:
            return [self._release(system_id, request)]
        return [encode_ack(opcode, request.request_id, request.axis, 5)]

    def _status_packet(self, request: Request) -> bytes:
        view = self._mount.view()
        moving = any(abs(axis.current_dps) > 1e-3 or abs(axis.commanded_dps) > 1e-6 for axis in view.axes.values())
        fault = view.fault_code if view.connected else FAULT_ESP32_SILENT
        if not view.connected:
            moving = False
        body = encode_status_body(
            esp32_up=view.connected,
            gateway_up=True,
            moving=moving,
            stopped=not moving,
            safety_clear=False,
            safety_fault=fault != 0,
            degraded=not view.connected or fault != 0,
            active_tilt=view.active_tilt if view.connected else 0,
            owner_system_id=self._owner,
            fault_code=fault,
            axes=view.axes if view.connected else {axis_id: AxisView() for axis_id in AXES},
        )
        # The GCS stamps stick commands with this clock so a late packet can be dropped.
        clock_ms = int(self._clock() * 1000) & 0xFFFFFFFF
        body += clock_ms.to_bytes(4, "little")
        return encode_status(request.request_id, request.opcode, body)

    def _read_config(self, request: Request) -> bytes:
        replies = self._exchange(CONFIG_GET, bytes([request.axis]))
        decoded = _config_frame(replies)
        if decoded is None:
            return encode_ack(request.opcode, request.request_id, request.axis, UNAVAILABLE)
        config, preserved = decoded
        return encode_header(CONFIG_READ, request.request_id, request.axis, APPLIED) + encode_config(config, preserved)

    def _write_config(self, system_id: int, request: Request) -> bytes:
        if not self._owns(system_id):
            return self._denied(request)
        decoded = decode_config(request.payload)
        if decoded is None:
            return encode_ack(request.opcode, request.request_id, request.axis, REJECTED)
        config, _preserved = decoded
        issues = validate_motor(config)
        if issues or request.axis not in AXES:
            logger.info("Rejected RCWM config for axis %s: %s", request.axis, "; ".join(issues))
            return encode_ack(request.opcode, request.request_id, request.axis, REJECTED)
        replies = self._exchange(CONFIG_SET, bytes([request.axis]) + encode_config(config))
        result = _ack_result(replies, CONFIG_SET)
        if result != APPLIED:
            return encode_ack(request.opcode, request.request_id, request.axis, result or UNAVAILABLE)
        self._configs[request.axis] = config
        applied = _config_frame(replies)
        preserved = applied[1] if applied else False
        return encode_header(CONFIG_WRITE, request.request_id, request.axis, APPLIED) + encode_config(config, preserved)

    def _select(self, system_id: int, request: Request) -> bytes:
        if not self._owns(system_id):
            return self._denied(request)
        if request.axis not in (2, 3):
            return encode_ack(request.opcode, request.request_id, request.axis, REJECTED)
        result = _ack_result(self._exchange(SERIAL_SELECT, bytes([request.axis])), SERIAL_SELECT)
        return encode_ack(request.opcode, request.request_id, request.axis, result or UNAVAILABLE)

    def _motion(self, system_id: int, request: Request) -> bytes:
        if not self._owns(system_id):
            return self._denied(request)
        rates = decode_motion(request.payload)
        if rates is None:
            return encode_ack(request.opcode, request.request_id, 0, REJECTED)
        if self._settings.transport == "serial" and not self._settings.allow_hardware_motion:
            # Stop is still forwarded. Only motion frames are held back.
            return encode_ack(request.opcode, request.request_id, 0, SAFETY)
        stamp = decode_motion_stamp(request.payload)
        if stamp is not None and self._motion_is_stale(stamp):
            # The hand has moved on. Do not start the motor from an old rate.
            return encode_ack(request.opcode, request.request_id, 0, TIMEOUT)
        pan = self._clamp_rate(1, rates[0])
        tilt1 = self._clamp_rate(2, rates[1])
        tilt2 = self._clamp_rate(3, rates[2])
        result, fault = _ack_frame(self._exchange(SERIAL_MOTION, encode_motion(pan, tilt1, tilt2)), SERIAL_MOTION)
        if result is None:
            return encode_ack(request.opcode, request.request_id, 0, UNAVAILABLE)
        if result == SAFETY:
            reason = self._motion_reason(pan, tilt1, tilt2, fault)
            return encode_ack(request.opcode, request.request_id, 0, SAFETY) + bytes([reason])
        return encode_ack(request.opcode, request.request_id, 0, result)

    def _stop_motion(self, request: Request) -> bytes:
        result = _ack_result(self._exchange(SERIAL_STOP, b""), SERIAL_STOP)
        return encode_ack(STOP, request.request_id, 0, result or UNAVAILABLE)

    def _home(self, system_id: int, request: Request) -> bytes:
        if not self._owns(system_id):
            return self._denied(request)
        if request.axis not in AXES:
            return encode_ack(request.opcode, request.request_id, request.axis, REJECTED)
        result, _fault = _ack_frame(self._exchange(SET_HOME, bytes([request.axis])), SET_HOME)
        if result is None:
            return encode_ack(HOME, request.request_id, request.axis, UNAVAILABLE)
        if result == SAFETY:
            return encode_ack(HOME, request.request_id, request.axis, SAFETY) + bytes([REASON_MOVING])
        return encode_ack(HOME, request.request_id, request.axis, result)

    def _take_ownership(self, system_id: int, request: Request) -> bytes:
        # Last writer wins. A new GCS request takes control; the previous
        # owner loses it on the next status.
        self._owner = system_id
        self._owner_seen = self._clock()
        return encode_ack(OWNERSHIP, request.request_id, 0, APPLIED)

    def _release(self, system_id: int, request: Request) -> bytes:
        if self._owner != system_id:
            return encode_ack(RELEASE, request.request_id, 0, REJECTED)
        self._owner = 0
        self._exchange(SERIAL_STOP, b"")
        return encode_ack(RELEASE, request.request_id, 0, APPLIED)

    def _owns(self, system_id: int) -> bool:
        return self._owner == system_id and not self._owner_expired()

    def _owner_expired(self) -> bool:
        return self._clock() - self._owner_seen > self._settings.owner_timeout_seconds

    def _touch(self, system_id: int) -> None:
        if self._owner == system_id:
            self._owner_seen = self._clock()

    def _denied(self, request: Request) -> bytes:
        return encode_ack(request.opcode, request.request_id, request.axis, REJECTED)

    def _fresh(self, system_id: int, request_id: int) -> bool:
        last = self._requests.get(system_id)
        if last is None:
            self._requests[system_id] = request_id
            return True
        if request_id == last:
            return False
        forward = (request_id - last) & 0xFFFF
        if 0 < forward <= 32768:
            self._requests[system_id] = request_id
            return True
        backward = (last - request_id) & 0xFFFF
        if backward <= 32:
            return False
        self._requests[system_id] = request_id
        return True

    def _exchange(self, msg_type: int, payload: bytes):
        if not self._mount.connected:
            return []
        return self._mount.exchange(msg_type, payload)

    def _motion_is_stale(self, stamp_ms: int) -> bool:
        now_ms = int(self._clock() * 1000) & 0xFFFFFFFF
        age = (now_ms - (stamp_ms & 0xFFFFFFFF)) & 0xFFFFFFFF
        # A stamp slightly ahead of us is clock error, not a packet from the future.
        if age > 0x80000000:
            return False
        return age > MOTION_MAX_AGE_MS

    def _clamp_rate(self, axis_id: int, rate: float) -> float:
        # A full stick can land a hair over the stored maximum after rounding.
        limit = self._configs[axis_id].max_speed_dps
        if limit is None or limit <= 0 or abs(rate) <= limit:
            return rate
        if abs(rate) - limit <= 0.05:
            return math.copysign(limit, rate)
        return rate

    def _motion_reason(self, pan: float, tilt1: float, tilt2: float, fault: int) -> int:
        if fault == FAULT_REFERENCE:
            return REASON_REFERENCE
        if fault == FAULT_CONTROLLER:
            return REASON_CONFIG
        if tilt1 != 0 and tilt2 != 0:
            return REASON_BOTH
        view = self._mount.view()
        if tilt1 != 0 and view.active_tilt != 2:
            return REASON_TILT
        if tilt2 != 0 and view.active_tilt != 3:
            return REASON_TILT
        for axis_id, rate in ((1, pan), (2, tilt1), (3, tilt2)):
            if rate == 0:
                continue
            config = self._configs[axis_id]
            limit = config.max_speed_dps
            if not config.enabled or limit is None or config.max_accel is None or config.max_decel is None:
                return REASON_CONFIG
            if abs(rate) > limit + 0.05:
                return REASON_SPEED
            axis = view.axes.get(axis_id)
            if axis is not None and axis.reference_invalid and (config.min_angle is not None or config.max_angle is not None):
                return REASON_REFERENCE
        return 0

    def _pull_config(self) -> None:
        if not self._mount.connected:
            return
        for axis_id in AXES:
            replies = self._exchange(CONFIG_GET, bytes([axis_id]))
            decoded = _config_frame(replies)
            if decoded is not None:
                self._configs[axis_id] = decoded[0]


def _ack_result(replies, msg_type: int) -> int | None:
    result, _fault = _ack_frame(replies, msg_type)
    return result


def _ack_frame(replies, msg_type: int) -> tuple[int | None, int]:
    if not replies:
        return None, 0
    for frame in replies:
        if frame.msg_type == ACK and len(frame.payload) >= 2 and frame.payload[0] == msg_type:
            fault = frame.payload[2] if len(frame.payload) > 2 else 0
            if fault == FAULT_OWNERSHIP:
                return REJECTED, fault
            return frame.payload[1], fault
    return TIMEOUT, 0


def _config_frame(replies) -> tuple[MotorConfig, bool] | None:
    for frame in replies:
        if frame.msg_type == CONFIG_REPLY and len(frame.payload) >= 2 + 27:
            return decode_config(frame.payload[2:])
    return None


def motion_command(request_id: int, pan: float, tilt1: float, tilt2: float) -> bytes:
    return encode_header(MOTION, request_id, 0, REQUEST) + encode_motion(pan, tilt1, tilt2)
