"""RCWM codec, serial frames, ownership, and simulated motion."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import RcwmSettings
from app.rcwm.device import Esp32Device
from app.rcwm.models import MotorConfig
from app.rcwm.protocol import (
    APPLIED,
    CONFIG_READ,
    CONFIG_WRITE,
    HOME,
    MOTION,
    OWNERSHIP,
    REJECTED,
    RELEASE,
    REQUEST,
    SAFETY,
    SELECT,
    STATUS,
    STOP,
    decode_config,
    decode_status_body,
    encode_config,
    encode_header,
    encode_motion,
)
from app.rcwm.serial_protocol import crc16_ccitt_false, encode_frame, pop_frames
from app.rcwm.service import RcwmService, motion_command


class Clock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


def service(tmp_path: Path, clock: Clock | None = None) -> RcwmService:
    clock = clock or Clock()
    item = RcwmService(
        RcwmSettings(enabled=True, transport="simulation", allow_hardware_motion=False),
        tmp_path / "rcwm.json",
        clock=clock,
    )
    item.start(background=False)
    return item


def commissioned(**overrides) -> MotorConfig:
    config = MotorConfig(
        enabled=True,
        steps_per_revolution=1600,
        gear_ratio=1.0,
        max_speed_dps=90,
        max_accel=100_000,
        max_decel=100_000,
        control_timeout_ms=500,
        deadband_percent=0,
        home_angle=0,
    )
    for key, value in overrides.items():
        setattr(config, key, value)
    return config


def write_config(axis: int, request_id: int, config: MotorConfig) -> bytes:
    return encode_header(CONFIG_WRITE, request_id, axis, REQUEST) + encode_config(config)


def test_protocol_matches_the_ground_station_layout() -> None:
    config = commissioned(steps_per_revolution=1600, gear_ratio=1.5, max_speed_dps=12.5, min_angle=-10, max_angle=20)
    raw = encode_config(config)
    assert len(raw) == 27
    assert raw[2] == 0x40 and raw[3] == 0x06
    assert int.from_bytes(raw[4:8], "little") == 1500
    decoded, preserved = decode_config(raw)
    assert preserved is False
    assert decoded.steps_per_revolution == 1600
    assert decoded.gear_ratio == 1.5
    assert decoded.max_speed_dps == pytest.approx(12.5)
    assert decoded.min_angle == pytest.approx(-10)
    header = encode_header(STATUS, 4, 0, REQUEST)
    assert header[:4] == b"RC\x01\x01"
    assert int.from_bytes(header[4:6], "little") == 4


def test_serial_crc_and_frame_roundtrip() -> None:
    assert crc16_ccitt_false(b"123456789") == 0x29B1
    frame = encode_frame(1, 1, b"")
    assert frame[:2] == b"\xA5\x5A"
    buffer = bytearray(b"\x00\x00" + frame + b"\xff")
    parsed = pop_frames(buffer)
    assert len(parsed) == 1
    assert parsed[0].msg_type == 1
    assert parsed[0].sequence == 1
    assert parsed[0].payload == b""
    broken = bytearray(frame)
    broken[-1] ^= 0xFF
    assert pop_frames(broken) == []


def test_three_motors_keep_independent_settings(tmp_path: Path) -> None:
    item = service(tmp_path)
    item.handle(255, 190, encode_header(OWNERSHIP, 1, 0, REQUEST))
    configs = {
        1: commissioned(steps_per_revolution=1600, gear_ratio=1.0),
        2: commissioned(steps_per_revolution=3200, gear_ratio=2.0),
        3: commissioned(steps_per_revolution=6400, gear_ratio=3.5),
    }
    request_id = 2
    for axis, config in configs.items():
        reply = item.handle(255, 190, write_config(axis, request_id, config))[0]
        request_id += 1
        assert reply[7] == APPLIED
        read = item.handle(255, 190, encode_header(CONFIG_READ, request_id, axis, REQUEST))[0]
        request_id += 1
        decoded, _preserved = decode_config(read[8:])
        assert decoded.steps_per_revolution == config.steps_per_revolution
        assert decoded.gear_ratio == pytest.approx(config.gear_ratio)


def test_ownership_blocks_the_second_station_until_the_lease_expires(tmp_path: Path) -> None:
    clock = Clock()
    item = service(tmp_path, clock)
    assert item.handle(255, 190, encode_header(OWNERSHIP, 1, 0, REQUEST))[0][7] == APPLIED
    assert item.handle(254, 190, encode_header(OWNERSHIP, 1, 0, REQUEST))[0][7] == REJECTED
    item.handle(255, 190, write_config(1, 2, commissioned()))
    denied = item.handle(254, 190, motion_command(2, 5, 0, 0))[0]
    assert denied[7] == REJECTED
    status = decode_status_body(item.handle(255, 190, encode_header(STATUS, 3, 0, REQUEST))[0][8:])
    assert status["owner_system_id"] == 255
    clock.now += 2
    item.maintain()
    status = decode_status_body(item.handle(255, 190, encode_header(STATUS, 4, 0, REQUEST))[0][8:])
    assert status["owner_system_id"] == 0
    item.handle(254, 190, encode_header(OWNERSHIP, 3, 0, REQUEST))
    status = decode_status_body(item.handle(254, 190, encode_header(STATUS, 4, 0, REQUEST))[0][8:])
    assert status["owner_system_id"] == 254
    item.handle(254, 190, encode_header(RELEASE, 5, 0, REQUEST))
    assert item.snapshot()["owner_system_id"] == 0


def test_tilt_switch_stops_the_previous_axis_and_rejects_both_tilts(tmp_path: Path) -> None:
    item = service(tmp_path)
    item.handle(255, 190, encode_header(OWNERSHIP, 1, 0, REQUEST))
    for axis in (1, 2, 3):
        item.handle(255, 190, write_config(axis, 1 + axis, commissioned()))
    assert item.handle(255, 190, encode_header(SELECT, 5, 3, REQUEST))[0][7] == APPLIED
    item.handle(255, 190, motion_command(6, 0, 0, 15))
    assert item.snapshot()["axes"]["tilt_2"]["commanded_dps"] == pytest.approx(15)
    assert item.handle(255, 190, encode_header(SELECT, 7, 2, REQUEST))[0][7] == APPLIED
    assert item.snapshot()["active_tilt"] == "tilt_1"
    assert item.snapshot()["axes"]["tilt_2"]["commanded_dps"] == 0
    assert item.snapshot()["axes"]["tilt_2"]["current_dps"] == 0
    refused = item.handle(255, 190, motion_command(8, 0, 5, 5))[0]
    assert refused[7] == SAFETY
    assert item.snapshot()["axes"]["tilt_1"]["commanded_dps"] == 0
    assert item.snapshot()["axes"]["tilt_2"]["commanded_dps"] == 0


def test_home_sets_an_estimate_and_restart_clears_it(tmp_path: Path) -> None:
    clock = Clock()
    item = service(tmp_path, clock)
    item.handle(255, 190, encode_header(OWNERSHIP, 1, 0, REQUEST))
    item.handle(255, 190, write_config(1, 2, commissioned(control_timeout_ms=10_000)))
    assert item.handle(255, 190, encode_header(HOME, 3, 1, REQUEST))[0][7] == APPLIED
    item.handle(255, 190, motion_command(4, 36, 0, 0))
    moving = item.handle(255, 190, encode_header(HOME, 5, 1, REQUEST))[0]
    assert moving[7] == SAFETY
    for _ in range(20):
        clock.now += 0.05
        item.maintain()
    status = decode_status_body(item.handle(255, 190, encode_header(STATUS, 6, 0, REQUEST))[0][8:])
    pan = status["axes"][1]
    assert pan.referenced is True
    assert pan.estimated_deg == pytest.approx(36, abs=1)
    assert pan.estimated_steps == pytest.approx(160, abs=8)
    item.handle(255, 190, encode_header(STOP, 7, 0, REQUEST))
    clock.now += 1
    item.maintain()
    sent = item._mount.motion_frames
    item._device.restart()
    item.maintain()
    assert item._mount.motion_frames == sent
    status = decode_status_body(item.handle(255, 190, encode_header(STATUS, 8, 0, REQUEST))[0][8:])
    assert status["axes"][1].reference_invalid is True
    assert status["axes"][1].estimated_deg is None
    assert status["axes"][1].estimated_steps is None
    assert item.snapshot()["reference_kept_across_restart"] is False
    assert item.snapshot()["positions"] == "estimates"


def test_timeout_stops_motion_and_duplicate_motion_is_rejected(tmp_path: Path) -> None:
    clock = Clock()
    item = service(tmp_path, clock)
    item.handle(255, 190, encode_header(OWNERSHIP, 1, 0, REQUEST))
    item.handle(255, 190, write_config(1, 2, commissioned(control_timeout_ms=200)))
    item.handle(255, 190, motion_command(3, 10, 0, 0))
    assert item.snapshot()["esp32"]["energized"] is True
    repeated = item.handle(255, 190, motion_command(3, 10, 0, 0))[0]
    assert repeated[7] == REJECTED
    assert item._device.motion_frames == 1
    clock.now += 0.3
    item.maintain()
    assert item.snapshot()["esp32"]["energized"] is False
    assert item.snapshot()["axes"]["pan"]["current_dps"] == 0
    assert item.snapshot()["fault_code"] == 7


def test_serial_motion_frame_reaches_the_simulated_controller() -> None:
    device = Esp32Device()
    config = encode_frame(5, 1, bytes([2]) + encode_config(commissioned()))
    assert device.handle(config)[0].payload[1] == APPLIED
    both = encode_frame(9, 2, encode_motion(0, 4, 4))
    assert device.handle(both)[0].payload[1] == SAFETY
    assert device.motion_frames == 0
    device.handle(encode_frame(8, 3, bytes([2])))
    moved = device.handle(encode_frame(9, 4, encode_motion(0, 4, 0)))
    assert moved[0].payload[1] == APPLIED
    assert device.motion_frames == 1
    device.restart()
    assert device.view().axes[2].referenced is False
    assert device.energized is False


def test_hardware_motion_stays_blocked_on_the_serial_transport(tmp_path: Path) -> None:
    item = RcwmService(
        RcwmSettings(enabled=True, transport="serial", serial_port="", allow_hardware_motion=False),
        tmp_path / "rcwm.json",
    )
    item.start(background=False)
    item.handle(255, 190, encode_header(OWNERSHIP, 1, 0, REQUEST))
    reply = item.handle(255, 190, motion_command(2, 5, 0, 0))[0]
    assert reply[7] == SAFETY
    assert item.snapshot()["esp32"]["connected"] is False
    item.stop()
