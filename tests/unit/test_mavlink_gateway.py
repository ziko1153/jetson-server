"""MAVLink routing, heartbeats, and RCWM tunnel replies."""

from __future__ import annotations

import socket
import time

from pymavlink.dialects.v20 import common as mavlink

from app.core.config import FlightControllerSettings, MavlinkSettings, RcwmSettings
from app.mavlink.gateway import MavlinkGateway
from app.rcwm.protocol import PAYLOAD_TYPE, STATUS, REQUEST, encode_header
from app.rcwm.service import RcwmService


def _link(system: int, component: int) -> mavlink.MAVLink:
    return mavlink.MAVLink(None, srcSystem=system, srcComponent=component)


def _pack(link: mavlink.MAVLink, message) -> bytes:
    frame = bytes(message.pack(link))
    link.seq = (link.seq + 1) % 256
    return frame


def _gateway(tmp_path, **overrides) -> tuple[MavlinkGateway, RcwmService]:
    service = RcwmService(RcwmSettings(enabled=True, transport="simulation"), tmp_path / "rcwm.json")
    service.start(background=False)
    settings = MavlinkSettings(
        enabled=True,
        bind_host="127.0.0.1",
        bind_port=0,
        heartbeat_interval_seconds=0.3,
        flight_controller=FlightControllerSettings(transport="none"),
        **overrides,
    )
    return MavlinkGateway(settings, service.handle), service


def _parse_all(payloads: list[bytes]) -> list:
    parser = mavlink.MAVLink(None)
    parser.robust_parsing = True
    found = []
    for payload in payloads:
        found.extend(parser.parse_buffer(payload) or [])
    return found


def test_flight_commands_are_forwarded_once_and_rcwm_is_not(tmp_path) -> None:
    gateway, service = _gateway(tmp_path)
    station = _link(255, 190)
    other = _link(254, 190)
    stranger = _link(42, 190)
    gateway.ingest_gcs(_pack(station, mavlink.MAVLink_heartbeat_message(6, 8, 0, 0, 4, 3)), ("127.0.0.1", 41000))
    gateway.ingest_gcs(_pack(other, mavlink.MAVLink_heartbeat_message(6, 8, 0, 0, 4, 3)), ("127.0.0.1", 41001))
    assert {peer["system_id"] for peer in gateway.snapshot()["gcs_peers"]} == {255, 254}

    command = _pack(station, mavlink.MAVLink_command_long_message(1, 1, 400, 0, 0, 0, 0, 0, 0, 0, 0))
    gateway.ingest_gcs(command, ("127.0.0.1", 41000))
    gateway.ingest_gcs(command, ("10.8.0.8", 41000))
    assert len(gateway.flight_output()) == 1
    assert gateway.duplicates_dropped == 1

    mount = _pack(station, mavlink.MAVLink_command_long_message(1, 171, 400, 0, 0, 0, 0, 0, 0, 0, 0))
    gateway.ingest_gcs(mount, ("127.0.0.1", 41000))
    assert len(gateway.flight_output()) == 1

    gateway.ingest_gcs(_pack(stranger, mavlink.MAVLink_command_long_message(1, 1, 400, 0, 0, 0, 0, 0, 0, 0, 0)), ("127.0.0.1", 9))
    assert gateway.rejected_sources == 1
    assert len(gateway.flight_output()) == 1

    body = encode_header(STATUS, 1, 0, REQUEST)
    payload = [0] * 128
    for index, value in enumerate(body):
        payload[index] = value
    tunnel = _pack(station, mavlink.MAVLink_tunnel_message(1, 171, PAYLOAD_TYPE, len(body), payload))
    gateway.ingest_gcs(tunnel, ("127.0.0.1", 41000))
    assert len(gateway.flight_output()) == 1
    assert gateway.rcwm_messages == 1
    replies = _parse_all(gateway.gcs_output())
    rcwm = [item for item in replies if item.get_type() == "TUNNEL"]
    assert rcwm
    assert rcwm[-1].get_srcSystem() == 1
    assert rcwm[-1].get_srcComponent() == 171
    assert rcwm[-1].payload_type == PAYLOAD_TYPE
    assert bytes(rcwm[-1].payload[:2]) == b"RC"

    autopilot = _link(1, 1)
    telemetry = _pack(autopilot, mavlink.MAVLink_heartbeat_message(10, 3, 0, 0, 4, 3))
    gateway.ingest_fc(telemetry)
    assert len(gateway.flight_output()) == 1
    assert gateway.forwarded_to_gcs == 1
    gateway.ingest_gcs(telemetry, ("127.0.0.1", 41000))
    assert gateway.duplicates_dropped == 2
    assert len(gateway.flight_output()) == 1

    gateway._send_heartbeats()
    beats = [item for item in _parse_all(gateway.gcs_output()) if item.get_type() == "HEARTBEAT" and item.get_srcSystem() == 1]
    assert {item.get_srcComponent() for item in beats} >= {191, 171}

    sync = _pack(station, mavlink.MAVLink_timesync_message(0, 123456))
    gateway.ingest_gcs(sync, ("127.0.0.1", 41000))
    times = [item for item in _parse_all(gateway.gcs_output()) if item.get_type() == "TIMESYNC" and int(item.ts1) == 123456 and int(item.tc1) != 0]
    assert times
    service.stop()


def test_udp_carries_the_companion_heartbeat_and_sitl_telemetry(tmp_path) -> None:
    service = RcwmService(RcwmSettings(enabled=True, transport="simulation"), tmp_path / "rcwm.json")
    service.start(background=False)
    gateway = MavlinkGateway(
        MavlinkSettings(
            enabled=True,
            bind_host="127.0.0.1",
            bind_port=0,
            heartbeat_interval_seconds=0.3,
            flight_controller=FlightControllerSettings(transport="udp", udp_bind_host="127.0.0.1", udp_bind_port=0),
        ),
        service.handle,
    )
    gateway.start()
    gcs = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sitl = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        assert gateway.running
        gcs.bind(("127.0.0.1", 0))
        gcs.settimeout(2)
        host, port = gateway._sock.getsockname()[:2]
        gcs.sendto(_pack(_link(255, 190), mavlink.MAVLink_heartbeat_message(6, 8, 0, 0, 4, 3)), (host, port))
        found = set()
        deadline = time.monotonic() + 2
        parser = mavlink.MAVLink(None)
        parser.robust_parsing = True
        while time.monotonic() < deadline and not {191, 171} <= found:
            data, _addr = gcs.recvfrom(2048)
            for message in parser.parse_buffer(data) or []:
                if message.get_type() == "HEARTBEAT" and message.get_srcSystem() == 1:
                    found.add(message.get_srcComponent())
        assert {191, 171} <= found

        fc_host, fc_port = gateway._fc_sock.getsockname()[:2]
        sitl.sendto(_pack(_link(1, 1), mavlink.MAVLink_heartbeat_message(10, 3, 0, 0, 4, 3)), (fc_host, fc_port))
        saw_autopilot = False
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and not saw_autopilot:
            data, _addr = gcs.recvfrom(2048)
            for message in parser.parse_buffer(data) or []:
                if message.get_type() == "HEARTBEAT" and message.get_srcComponent() == 1 and message.get_srcSystem() == 1:
                    saw_autopilot = True
        assert saw_autopilot
    finally:
        gcs.close()
        sitl.close()
        gateway.stop()
        service.stop()
