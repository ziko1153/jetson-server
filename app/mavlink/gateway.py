"""UDP MAVLink gateway.

The socket listens on the configured address, so GR03, mesh, and VPN can all
reach it. This process does not pick a preferred path and it does not replace
the direct ground-station serial link to the Matek.

System ids 255 and 254, component 190, are an allowlist. They are not
authentication. A shared network can still spoof those ids.
"""

from __future__ import annotations

import logging
import select
import socket
import threading
import time
from collections import deque
from dataclasses import dataclass

from app.core.config import MavlinkSettings
from app.rcwm.protocol import PAYLOAD_TYPE

logger = logging.getLogger("app.mavlink")

try:
    from pymavlink.dialects.v20 import common as mavlink
except ImportError:  # pragma: no cover
    mavlink = None

HEARTBEAT = 0
TIMESYNC = 111
TUNNEL = 385
MAV_TYPE_ONBOARD_CONTROLLER = 18
MAV_AUTOPILOT_INVALID = 8
MAV_STATE_ACTIVE = 4
FORWARD_WITHOUT_TARGET = frozenset(
    {
        11,
        20,
        21,
        23,
        39,
        43,
        44,
        45,
        47,
        51,
        66,
        69,
        70,
        73,
        75,
        76,
        82,
        84,
        86,
    }
)


@dataclass
class _Peer:
    address: tuple[str, int]
    system_id: int
    component_id: int
    last_seen: float


class MavlinkGateway:
    def __init__(self, settings: MavlinkSettings, on_rcwm) -> None:
        self._settings = settings
        self._on_rcwm = on_rcwm
        self._peers: dict[tuple[str, int], _Peer] = {}
        self._seen: dict[tuple, float] = {}
        self._gcs_parsers: dict[tuple[str, int], object] = {}
        self._fc_parser = None
        self._companion = None
        self._mount_link = None
        self._sock: socket.socket | None = None
        self._fc_sock: socket.socket | None = None
        self._fc_serial = None
        self._fc_target: tuple[str, int] | None = None
        self._fc_out: deque[bytes] = deque(maxlen=100)
        self._gcs_out: deque[bytes] = deque(maxlen=100)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.running = False
        self.last_error = ""
        self.fc_error = ""
        self.fc_connected = False
        self.heartbeats_sent = 0
        self.forwarded_to_flight_controller = 0
        self.forwarded_to_gcs = 0
        self.rcwm_messages = 0
        self.rejected_sources = 0
        self.duplicates_dropped = 0
        self._last_fc_attempt = 0.0
        if mavlink is not None:
            self._fc_parser = _parser()
            self._companion = mavlink.MAVLink(None, srcSystem=settings.system_id, srcComponent=settings.companion_component_id)
            self._mount_link = mavlink.MAVLink(None, srcSystem=settings.system_id, srcComponent=settings.rcwm_component_id)

    def start(self) -> None:
        if not self._settings.enabled or self.running:
            return
        if mavlink is None:
            self.last_error = "pymavlink is not installed"
            logger.error(self.last_error)
            return
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((self._settings.bind_host, self._settings.bind_port))
            sock.setblocking(False)
        except OSError as exc:
            self.last_error = f"MAVLink UDP bind failed: {exc}"
            logger.error(self.last_error)
            return
        self._sock = sock
        self._open_flight_controller()
        self.running = True
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="mavlink", daemon=True)
        self._thread.start()
        logger.info("MAVLink listening on %s", self.bind_label)

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2)
        self._thread = None
        self._close_socket(self._sock)
        self._sock = None
        self._close_socket(self._fc_sock)
        self._fc_sock = None
        self._close_serial()
        self.running = False
        self.fc_connected = False

    def ingest_gcs(self, data: bytes, address: tuple[str, int]) -> None:
        if mavlink is None or not data:
            return
        parser = self._gcs_parsers.get(address)
        if parser is None:
            parser = _parser()
            self._gcs_parsers[address] = parser
        for message in parser.parse_buffer(data) or []:
            self._from_gcs(message, address)

    def ingest_fc(self, data: bytes) -> None:
        if mavlink is None or not data or self._fc_parser is None:
            return
        for message in self._fc_parser.parse_buffer(data) or []:
            self._from_fc(message)

    def flight_output(self) -> list[bytes]:
        with self._lock:
            return list(self._fc_out)

    def gcs_output(self) -> list[bytes]:
        with self._lock:
            return list(self._gcs_out)

    def snapshot(self) -> dict:
        now = time.monotonic()
        with self._lock:
            peers = [
                {
                    "address": f"{peer.address[0]}:{peer.address[1]}",
                    "system_id": peer.system_id,
                    "component_id": peer.component_id,
                    "age_seconds": round(now - peer.last_seen, 3),
                }
                for peer in self._peers.values()
                if now - peer.last_seen <= self._settings.peer_timeout_seconds
            ]
        flight = self._settings.flight_controller
        return {
            "enabled": self._settings.enabled,
            "running": self.running,
            "bind": self.bind_label,
            "system_id": self._settings.system_id,
            "companion_component_id": self._settings.companion_component_id,
            "rcwm_component_id": self._settings.rcwm_component_id,
            "gcs_peers": peers,
            "heartbeats_sent": self.heartbeats_sent,
            "forwarded_to_flight_controller": self.forwarded_to_flight_controller,
            "forwarded_to_gcs": self.forwarded_to_gcs,
            "rcwm_messages": self.rcwm_messages,
            "rejected_sources": self.rejected_sources,
            "duplicates_dropped": self.duplicates_dropped,
            "last_error": self.last_error,
            "flight_controller": {
                "transport": flight.transport,
                "connected": self.fc_connected,
                "serial_port": flight.serial_port,
                "udp_bind": self._fc_bind_label(),
                "error": self.fc_error,
            },
            "note": "GCS system ids are an allowlist, not authentication. This gateway does not choose a radio path.",
        }

    @property
    def bind_label(self) -> str:
        if self._sock is None:
            return f"{self._settings.bind_host}:{self._settings.bind_port}"
        host, port = self._sock.getsockname()[:2]
        return f"{host}:{port}"

    def _loop(self) -> None:
        next_heartbeat = 0.0
        while not self._stop.is_set():
            self._pump(0.2)
            now = time.monotonic()
            if now >= next_heartbeat:
                self._send_heartbeats()
                next_heartbeat = now + self._settings.heartbeat_interval_seconds
            self._reconnect_flight_controller()

    def _pump(self, timeout: float) -> None:
        sockets = [item for item in (self._sock, self._fc_sock) if item is not None]
        if not sockets:
            self._stop.wait(timeout)
            return
        readable, _, _ = select.select(sockets, [], [], timeout)
        for item in readable:
            try:
                data, address = item.recvfrom(4096)
            except OSError:
                continue
            if item is self._sock:
                self.ingest_gcs(data, address)
            else:
                if not self._settings.flight_controller.udp_remote_host:
                    self._fc_target = address
                self.fc_connected = True
                self.ingest_fc(data)
        if self._fc_serial is not None:
            self._read_serial()

    def _from_gcs(self, message, address: tuple[str, int]) -> None:
        if self._duplicate(message):
            self.duplicates_dropped += 1
            return
        source_system = message.get_srcSystem()
        source_component = message.get_srcComponent()
        local = (self._settings.companion_component_id, self._settings.rcwm_component_id, self._settings.autopilot_component_id)
        if source_system == self._settings.system_id and source_component in local:
            return
        if source_system not in self._settings.allowed_gcs_system_ids or source_component != self._settings.gcs_component_id:
            self.rejected_sources += 1
            logger.info("Dropped MAVLink from system %s component %s", source_system, source_component)
            return
        with self._lock:
            self._peers[address] = _Peer(address, source_system, source_component, time.monotonic())
        msgid = message.get_msgId()
        if msgid == HEARTBEAT:
            return
        if msgid == TIMESYNC and int(getattr(message, "tc1", 1)) == 0:
            self._reply_timesync(message, address)
            return
        if msgid == TUNNEL and int(getattr(message, "payload_type", 0)) == PAYLOAD_TYPE:
            target = int(getattr(message, "target_component", 0))
            if target in (0, self._settings.rcwm_component_id):
                length = int(message.payload_length)
                body = bytes(message.payload[:length])
                self.rcwm_messages += 1
                try:
                    replies = self._on_rcwm(source_system, source_component, body) or []
                except Exception:
                    logger.exception("RCWM handler failed")
                    return
                for reply in replies:
                    self._send_rcwm(reply)
                return
        target_component = getattr(message, "target_component", None)
        if target_component in (self._settings.rcwm_component_id, self._settings.companion_component_id):
            return
        if self._for_autopilot(message):
            self._send_fc(bytes(message.get_msgbuf()))

    def _from_fc(self, message) -> None:
        if self._duplicate(message):
            self.duplicates_dropped += 1
            return
        source_component = message.get_srcComponent()
        if message.get_srcSystem() == self._settings.system_id and source_component in (
            self._settings.companion_component_id,
            self._settings.rcwm_component_id,
        ):
            return
        self._send_gcs(bytes(message.get_msgbuf()))

    def _for_autopilot(self, message) -> bool:
        msgid = message.get_msgId()
        if msgid in (HEARTBEAT, TIMESYNC, TUNNEL):
            return False
        system = getattr(message, "target_system", None)
        component = getattr(message, "target_component", None)
        if component in (self._settings.rcwm_component_id, self._settings.companion_component_id):
            return False
        if system not in (None, 0, self._settings.system_id):
            return False
        if component not in (None, 0, self._settings.autopilot_component_id):
            return False
        if system is None and component is None:
            return msgid in FORWARD_WITHOUT_TARGET
        return True

    def _duplicate(self, message) -> bool:
        key = (message.get_srcSystem(), message.get_srcComponent(), message.get_msgId(), message.get_seq())
        now = time.monotonic()
        previous = self._seen.get(key)
        self._seen[key] = now
        if len(self._seen) > 2000:
            cutoff = now - 1
            self._seen = {item: stamp for item, stamp in self._seen.items() if stamp >= cutoff}
        return previous is not None and now - previous < 1

    def _reply_timesync(self, message, address: tuple[str, int]) -> None:
        if self._companion is None or mavlink is None:
            return
        reply = mavlink.MAVLink_timesync_message(time.time_ns(), int(message.ts1))
        self._transmit_gcs(address, self._pack(reply, self._companion))

    def _send_heartbeats(self) -> None:
        peers = self._live_peers()
        if not peers or self._companion is None or self._mount_link is None or mavlink is None:
            return
        companion = self._pack(
            mavlink.MAVLink_heartbeat_message(
                MAV_TYPE_ONBOARD_CONTROLLER, MAV_AUTOPILOT_INVALID, 0, 0, MAV_STATE_ACTIVE, 3
            ),
            self._companion,
        )
        mount = self._pack(
            mavlink.MAVLink_heartbeat_message(
                MAV_TYPE_ONBOARD_CONTROLLER, MAV_AUTOPILOT_INVALID, 0, 0, MAV_STATE_ACTIVE, 3
            ),
            self._mount_link,
        )
        for peer in peers:
            self._transmit_gcs(peer.address, companion)
            self._transmit_gcs(peer.address, mount)
            self.heartbeats_sent += 2

    def _send_rcwm(self, body: bytes) -> None:
        if self._mount_link is None or mavlink is None:
            return
        payload = [0] * 128
        data = body[:128]
        for index, value in enumerate(data):
            payload[index] = value
        for peer in self._live_peers():
            message = mavlink.MAVLink_tunnel_message(
                peer.system_id,
                self._settings.gcs_component_id,
                PAYLOAD_TYPE,
                len(data),
                payload,
            )
            self._transmit_gcs(peer.address, self._pack(message, self._mount_link))

    def _send_fc(self, payload: bytes) -> None:
        with self._lock:
            self._fc_out.append(payload)
        self.forwarded_to_flight_controller += 1
        if self._fc_serial is not None:
            try:
                self._fc_serial.write(payload)
            except Exception as exc:
                self.fc_error = str(exc)
                self._close_serial()
            return
        if self._fc_sock is not None and self._fc_target is not None:
            try:
                self._fc_sock.sendto(payload, self._fc_target)
            except OSError as exc:
                self.fc_error = str(exc)

    def _send_gcs(self, payload: bytes) -> None:
        with self._lock:
            self._gcs_out.append(payload)
        self.forwarded_to_gcs += 1
        for peer in self._live_peers():
            self._transmit_gcs(peer.address, payload, record=False)

    def _transmit_gcs(self, address: tuple[str, int], payload: bytes, record: bool = True) -> None:
        if record:
            with self._lock:
                self._gcs_out.append(payload)
        sock = self._sock
        if sock is None:
            return
        try:
            sock.sendto(payload, address)
        except OSError as exc:
            self.last_error = str(exc)

    def _pack(self, message, link) -> bytes:
        frame = bytes(message.pack(link))
        link.seq = (link.seq + 1) % 256
        return frame

    def _live_peers(self) -> list[_Peer]:
        now = time.monotonic()
        limit = self._settings.peer_timeout_seconds
        with self._lock:
            return [peer for peer in self._peers.values() if now - peer.last_seen <= limit]

    def _open_flight_controller(self) -> None:
        flight = self._settings.flight_controller
        self._last_fc_attempt = time.monotonic()
        if flight.transport == "udp":
            self._open_fc_udp()
        elif flight.transport == "serial":
            self._open_fc_serial()
        else:
            self.fc_connected = False

    def _open_fc_udp(self) -> None:
        flight = self._settings.flight_controller
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((flight.udp_bind_host, flight.udp_bind_port))
            sock.setblocking(False)
        except OSError as exc:
            self.fc_error = str(exc)
            self.fc_connected = False
            return
        self._fc_sock = sock
        if flight.udp_remote_host:
            self._fc_target = (flight.udp_remote_host, flight.udp_remote_port)
            self.fc_connected = True
        else:
            self.fc_connected = False

    def _open_fc_serial(self) -> None:
        flight = self._settings.flight_controller
        if not flight.serial_port:
            self.fc_error = "Flight controller serial port is not configured"
            self.fc_connected = False
            return
        try:
            import serial
        except ImportError:
            self.fc_error = "pyserial is not installed"
            self.fc_connected = False
            return
        try:
            self._fc_serial = serial.Serial(flight.serial_port, flight.baud, timeout=0)
            self.fc_connected = True
            self.fc_error = ""
        except Exception as exc:
            self.fc_error = str(exc)
            self.fc_connected = False

    def _read_serial(self) -> None:
        port = self._fc_serial
        if port is None:
            return
        try:
            waiting = port.in_waiting
            if not waiting:
                return
            data = port.read(waiting)
        except Exception as exc:
            self.fc_error = str(exc)
            self._close_serial()
            return
        if data:
            self.fc_connected = True
            self.ingest_fc(data)

    def _reconnect_flight_controller(self) -> None:
        flight = self._settings.flight_controller
        if flight.transport == "none" or self.fc_connected:
            return
        if time.monotonic() - self._last_fc_attempt < 2:
            return
        self._open_flight_controller()

    def _close_serial(self) -> None:
        port = self._fc_serial
        self._fc_serial = None
        self.fc_connected = False
        if port is not None:
            try:
                port.close()
            except Exception:
                logger.warning("Flight controller serial port did not close cleanly")

    def _fc_bind_label(self) -> str:
        if self._fc_sock is None:
            flight = self._settings.flight_controller
            if flight.transport != "udp":
                return ""
            return f"{flight.udp_bind_host}:{flight.udp_bind_port}"
        host, port = self._fc_sock.getsockname()[:2]
        return f"{host}:{port}"

    @staticmethod
    def _close_socket(sock: socket.socket | None) -> None:
        if sock is None:
            return
        try:
            sock.close()
        except OSError:
            return


def _parser():
    parser = mavlink.MAVLink(None)
    parser.robust_parsing = True
    return parser
