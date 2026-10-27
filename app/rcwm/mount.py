"""Mount transports. Simulation stays in-process. Serial is a configured port."""

from __future__ import annotations

import logging
import threading
import time

from app.rcwm.device import Esp32Device
from app.rcwm.models import MountView
from app.rcwm.protocol import AXES, FAULT_ESP32_SILENT, AxisView
from app.rcwm.serial_protocol import HELLO, HELLO_ACK, STATUS, STATUS_REQ, Frame, encode_frame, pop_frames

logger = logging.getLogger("app.rcwm")

# The ESP32 pushes STATUS continuously. The Jetson still asks occasionally as a
# liveness check and for exchanges that need a reply.
STATUS_POLL_SECONDS = 2.0


class SimulatedMount:
    def __init__(self, device: Esp32Device) -> None:
        self.device = device
        self.connected = True
        self.last_error = ""
        self.motion_frames = 0
        self._sequence = 1
        self._boot_id: int | None = None

    @property
    def boot_id(self) -> int | None:
        return self.device.boot_id

    def start(self) -> None:
        self.connected = True
        self.exchange(HELLO, b"")

    def close(self) -> None:
        self.connected = False

    def advance(self, dt: float) -> None:
        self.device.advance(dt)

    def poll(self) -> None:
        return None

    def exchange(self, msg_type: int, payload: bytes = b"") -> list[Frame]:
        if msg_type == 9:
            self.motion_frames += 1
        frame = encode_frame(msg_type, self._sequence, payload)
        self._sequence = (self._sequence + 1) & 0xFFFF
        replies = self.device.handle(frame)
        for reply in replies:
            if reply.msg_type == HELLO_ACK and len(reply.payload) >= 4:
                self._boot_id = int.from_bytes(reply.payload[:4], "little")
        return replies

    def view(self) -> MountView:
        view = self.device.view()
        view.connected = self.connected
        return view


class SerialMount:
    """USB serial client. It never chooses a device path on its own."""

    def __init__(self, port: str, baud: int) -> None:
        self._port = port
        self._baud = baud
        self._serial = None
        self._buffer = bytearray()
        self._lock = threading.RLock()
        self._sequence = 1
        self.connected = False
        self.last_error = ""
        self.motion_frames = 0
        self.boot_id: int | None = None
        self._view = _empty_view()
        self._pending: list[Frame] = []
        self._last_open = 0.0
        self._last_status = 0.0

    def start(self) -> None:
        self._open(send_hello=True)

    def close(self) -> None:
        with self._lock:
            self._close_locked()

    def advance(self, dt: float) -> None:
        return None

    def poll(self) -> None:
        if self.connected:
            self._read()
            self._take_frames()
            now = time.monotonic()
            # Keep the mount view fresh so the GCS sees real controller state.
            if now - self._last_status >= STATUS_POLL_SECONDS:
                self._last_status = now
                self.exchange(STATUS_REQ, b"")
            return
        now = time.monotonic()
        if now - self._last_open < 2:
            return
        self._last_open = now
        self._open(send_hello=True)

    def exchange(self, msg_type: int, payload: bytes = b"") -> list[Frame]:
        # One owner of the port at a time. The command path and the status
        # poll used to read it together, and the replies were lost.
        with self._lock:
            if not self.connected or self._serial is None:
                return []
            if msg_type == 9:
                self.motion_frames += 1
            sequence = self._sequence
            self._sequence = (self._sequence + 1) & 0xFFFF
            frame = encode_frame(msg_type, sequence, payload)
            try:
                self._serial.write(frame)
            except Exception as exc:
                self.last_error = str(exc)
                # A full buffer must not hang the link, and one slow write
                # must not drop the port. A real IO error still closes it.
                if exc.__class__.__name__ != "SerialTimeoutException":
                    self._close_locked()
                return []
            deadline = time.monotonic() + 0.2
            found: list[Frame] = []
            while time.monotonic() < deadline:
                self._read()
                for parsed in self._take_frames():
                    found.append(parsed)
                    if _completes(msg_type, parsed):
                        return found
                time.sleep(0.005)
            return found

    def view(self) -> MountView:
        current = self._view
        current.connected = self.connected
        current.boot_id = self.boot_id
        return current

    def _open(self, send_hello: bool) -> None:
        if not self._port:
            self.last_error = "RCWM serial port is not configured"
            self.connected = False
            return
        try:
            import serial
        except ImportError:
            self.last_error = "pyserial is not installed"
            self.connected = False
            return
        try:
            port = serial.Serial(self._port, self._baud, timeout=0.05, write_timeout=0.05)
        except Exception as exc:
            self.last_error = str(exc)
            self.connected = False
            return
        with self._lock:
            self._serial = port
            self.connected = True
            self.last_error = ""
        if send_hello:
            self.exchange(HELLO, b"")

    def _read(self) -> None:
        with self._lock:
            port = self._serial
            if port is None:
                return
            try:
                waiting = port.in_waiting
                if not waiting:
                    return
                chunk = port.read(waiting)
            except Exception as exc:
                self.last_error = str(exc)
                self._close_locked()
                return
            if not chunk:
                return
            self._buffer.extend(chunk)
            for frame in pop_frames(self._buffer):
                self._observe(frame)

    def _take_frames(self) -> list[Frame]:
        with self._lock:
            found = self._pending
            self._pending = []
            return found

    def _observe(self, frame: Frame) -> None:
        if frame.msg_type == HELLO_ACK and len(frame.payload) >= 4:
            self.boot_id = int.from_bytes(frame.payload[:4], "little")
            self._view.energized = bool(frame.payload[4]) if len(frame.payload) > 4 else False
        if frame.msg_type == STATUS:
            self._apply_status(frame.payload)
        self._pending.append(frame)

    def _apply_status(self, payload: bytes) -> None:
        from app.rcwm.protocol import decode_status_body

        decoded = decode_status_body(payload)
        if decoded is None:
            return
        self._view = MountView(
            connected=self.connected,
            boot_id=self.boot_id,
            energized=self._view.energized,
            active_tilt=decoded["active_tilt"],
            fault_code=decoded["fault_code"],
            axes=decoded["axes"],
        )

    def _drop(self) -> None:
        with self._lock:
            self._close_locked()

    def _close_locked(self) -> None:
        port = self._serial
        self._serial = None
        self.connected = False
        if port is not None:
            try:
                port.close()
            except Exception:
                logger.warning("RCWM serial port did not close cleanly")


def _completes(request: int, frame: Frame) -> bool:
    if request == HELLO and frame.msg_type == HELLO_ACK:
        return True
    if request == 13 and frame.msg_type == 14:
        return True
    if request == STATUS_REQ and frame.msg_type == STATUS:
        return True
    return frame.msg_type == 12 and bool(frame.payload) and frame.payload[0] == request


def _empty_view() -> MountView:
    return MountView(
        connected=False,
        boot_id=None,
        energized=False,
        active_tilt=0,
        fault_code=FAULT_ESP32_SILENT,
        axes={axis_id: AxisView() for axis_id in AXES},
    )
