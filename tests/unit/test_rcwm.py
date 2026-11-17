"""RCWM codec, serial frames, ownership, and simulated motion."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import RcwmSettings
from app.rcwm import patrol
from app.rcwm.device import Esp32Device
from app.rcwm.models import MotorConfig
from app.rcwm.protocol import (
    APPLIED,
    CONFIG_READ,
    CONFIG_WRITE,
    HOME,
    MOTION,
    OUTPUTS,
    OWNERSHIP,
    PATROL,
    REJECTED,
    RELEASE,
    REQUEST,
    SAFETY,
    SELECT,
    STATUS,
    STOP,
    TIMEOUT,
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


def test_ownership_last_writer_wins_and_expires(tmp_path: Path) -> None:
    clock = Clock()
    item = service(tmp_path, clock)
    assert item.handle(255, 190, encode_header(OWNERSHIP, 1, 0, REQUEST))[0][7] == APPLIED
    # A second station takes control immediately; the previous owner loses it.
    assert item.handle(254, 190, encode_header(OWNERSHIP, 2, 0, REQUEST))[0][7] == APPLIED
    status = decode_status_body(item.handle(255, 190, encode_header(STATUS, 3, 0, REQUEST))[0][8:])
    assert status["owner_system_id"] == 254
    # The previous owner can no longer command motion.
    denied = item.handle(255, 190, motion_command(4, 5, 0, 0))[0]
    assert denied[7] == REJECTED
    item.handle(254, 190, write_config(1, 5, commissioned()))
    # Silence still releases the mount.
    clock.now += 2
    item.maintain()
    status = decode_status_body(item.handle(255, 190, encode_header(STATUS, 6, 0, REQUEST))[0][8:])
    assert status["owner_system_id"] == 0
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
    item.handle(255, 190, write_config(1, 2, commissioned()))
    assert item.handle(255, 190, encode_header(HOME, 3, 1, REQUEST))[0][7] == APPLIED
    item.handle(255, 190, motion_command(4, 36, 0, 0))
    moving = item.handle(255, 190, encode_header(HOME, 5, 1, REQUEST))[0]
    assert moving[7] == SAFETY
    rid = 100
    for _ in range(20):
        item.handle(255, 190, motion_command(rid, 36, 0, 0))
        rid += 1
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
    pan = status["axes"][1]
    # The controller persists the last halted position, so a reboot keeps the
    # reference and the angle instead of invalidating them.
    assert pan.referenced is True
    assert pan.estimated_deg is not None
    assert abs(pan.estimated_deg - 36) < 2
    assert item.snapshot()["reference_kept_across_restart"] is True
    assert item.snapshot()["positions"] == "estimates"


def test_timeout_stops_motion_and_duplicate_motion_is_rejected(tmp_path: Path) -> None:
    clock = Clock()
    item = service(tmp_path, clock)
    item.handle(255, 190, encode_header(OWNERSHIP, 1, 0, REQUEST))
    item.handle(255, 190, write_config(1, 2, commissioned()))
    item.handle(255, 190, motion_command(3, 10, 0, 0))
    assert item.snapshot()["esp32"]["energized"] is True
    repeated = item.handle(255, 190, motion_command(3, 10, 0, 0))[0]
    assert repeated[7] == REJECTED
    assert item._device.motion_frames == 1
    clock.now += 0.6
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


def test_a_late_stick_command_is_dropped_and_a_fresh_one_is_forwarded(tmp_path: Path) -> None:
    clock = Clock()
    item = service(tmp_path, clock)
    item.handle(255, 190, encode_header(OWNERSHIP, 1, 0, REQUEST))
    item.handle(255, 190, write_config(1, 2, commissioned()))
    now_ms = int(clock.now * 1000)

    def stamped(request_id: int, stamp: int) -> bytes:
        body = encode_header(MOTION, request_id, 0, REQUEST) + encode_motion(10, 0, 0)
        return body + (stamp & 0xFFFFFFFF).to_bytes(4, "little")

    late = item.handle(255, 190, stamped(3, now_ms - 5_000))[0]
    assert late[7] == TIMEOUT
    assert item._device.motion_frames == 0
    ahead = item.handle(255, 190, stamped(4, now_ms + 80))[0]
    assert ahead[7] == APPLIED
    fresh = item.handle(255, 190, stamped(5, now_ms - 40))[0]
    assert fresh[7] == APPLIED
    assert item._device.motion_frames == 2



def test_outputs_need_ownership_and_reach_the_controller(tmp_path: Path) -> None:
    item = service(tmp_path)
    denied = item.handle(255, 190, encode_header(OUTPUTS, 1, 0, REQUEST) + bytes([0b001]))[0]
    assert denied[7] == REJECTED
    item.handle(255, 190, encode_header(OWNERSHIP, 2, 0, REQUEST))
    reply = item.handle(255, 190, encode_header(OUTPUTS, 3, 0, REQUEST) + bytes([0b101]))[0]
    assert reply[3] == OUTPUTS and reply[7] == APPLIED and reply[8] == 0b101
    assert item.snapshot()["outputs"] == {"wpn_1": True, "wpn_2": False, "wpn_3": True}
    status = item.handle(255, 190, encode_header(STATUS, 4, 0, REQUEST))[0]
    assert len(status) == 8 + 48 + 4 + 1 + patrol.BLOCK
    assert status[8 + 48 + 4] == 0b101
    unknown = item.handle(255, 190, encode_header(OUTPUTS, 5, 0, REQUEST) + bytes([0b1000]))[0]
    assert unknown[7] == REJECTED


def test_stop_keeps_outputs_and_a_lost_owner_switches_them_off(tmp_path: Path) -> None:
    clock = Clock()
    item = service(tmp_path, clock)
    item.handle(255, 190, encode_header(OWNERSHIP, 1, 0, REQUEST))
    item.handle(255, 190, encode_header(OUTPUTS, 2, 0, REQUEST) + bytes([0b011]))
    item.handle(255, 190, encode_header(STOP, 3, 0, REQUEST))
    assert item.snapshot()["outputs"]["wpn_1"] is True
    clock.now += 2
    item.maintain()
    assert item.snapshot()["outputs"] == {"wpn_1": False, "wpn_2": False, "wpn_3": False}


def test_release_switches_outputs_off(tmp_path: Path) -> None:
    item = service(tmp_path)
    item.handle(255, 190, encode_header(OWNERSHIP, 1, 0, REQUEST))
    item.handle(255, 190, encode_header(OUTPUTS, 2, 0, REQUEST) + bytes([0b100]))
    item.handle(255, 190, encode_header(RELEASE, 3, 0, REQUEST))
    assert item.snapshot()["outputs"]["wpn_3"] is False


def test_serial_status_with_outputs_byte_updates_the_mount_view() -> None:
    from app.rcwm.mount import SerialMount

    device = Esp32Device()
    mount = SerialMount("", 115200)
    replies = device.handle(encode_frame(15, 1, bytes([0b010])))
    assert replies[0].payload == bytes([15, APPLIED, 0, 0b010])
    status = device.handle(encode_frame(3, 2, b""))[0]
    assert len(status.payload) == 49 + patrol.BLOCK
    mount._apply_status(status.payload)
    assert mount.view().outputs == 0b010
    assert mount.view().patrol == patrol.PatrolView()
    mount._apply_status(status.payload[:48])
    assert mount.view().outputs is None
    assert mount.view().patrol is None


def patrolling_service(tmp_path: Path, clock: Clock) -> RcwmService:
    item = service(tmp_path, clock)
    item.handle(255, 190, encode_header(OWNERSHIP, 1, 0, REQUEST))
    pan = commissioned(max_speed_dps=30, max_accel=20, max_decel=20, min_angle=-90, max_angle=180)
    assert item.handle(255, 190, write_config(1, 2, pan))[0][7] == APPLIED
    assert item.handle(255, 190, write_config(2, 3, commissioned()))[0][7] == APPLIED
    assert item.handle(255, 190, encode_header(HOME, 4, 1, REQUEST))[0][7] == APPLIED
    assert item.handle(255, 190, encode_header(SELECT, 5, 2, REQUEST))[0][7] == APPLIED
    return item


def patrol_request(request_id: int, payload: bytes) -> bytes:
    return encode_header(PATROL, request_id, 0, REQUEST) + payload


def test_patrol_refuses_a_range_outside_the_pan_limits(tmp_path: Path) -> None:
    clock = Clock()
    item = patrolling_service(tmp_path, clock)
    reply = item.handle(255, 190, patrol_request(10, patrol.start_payload(-100, 40, 20)))[0]
    assert reply[7] == REJECTED and reply[8] == patrol.REASON_OUTSIDE_LIMITS
    reply = item.handle(255, 190, patrol_request(11, patrol.start_payload(-20, 40, 31)))[0]
    assert reply[7] == REJECTED and reply[8] == patrol.REASON_SPEED
    denied = item.handle(254, 190, patrol_request(1, patrol.start_payload(-20, 40, 20)))[0]
    assert denied[7] == REJECTED


def test_patrol_owns_pan_and_leaves_tilt_to_the_stick(tmp_path: Path) -> None:
    clock = Clock()
    item = patrolling_service(tmp_path, clock)
    reply = item.handle(255, 190, patrol_request(10, patrol.start_payload(-20, 40, 25)))[0]
    assert reply[7] == APPLIED
    assert item.handle(255, 190, motion_command(11, 5, 0, 0))[0][7] == REJECTED
    assert item.handle(255, 190, motion_command(12, 0, 5, 0))[0][7] == APPLIED
    assert item._device.axes[2].commanded_dps == 5
    item.handle(255, 190, encode_header(STOP, 13, 0, REQUEST))
    low = high = 0.0
    for _ in range(3000):
        clock.now += 0.02
        item._device.advance(0.02)
        angle = item._device.view().axes[1].estimated_deg
        low, high = min(low, angle), max(high, angle)
    assert -20 <= low < -19
    assert 39 < high <= 40
    assert item.snapshot()["patrol"]["active"] is True


def test_patrol_survives_a_lost_owner_and_stops_on_request(tmp_path: Path) -> None:
    clock = Clock()
    item = patrolling_service(tmp_path, clock)
    item.handle(255, 190, patrol_request(10, patrol.start_payload(-20, 40, 25)))
    clock.now += 2
    item.maintain()
    assert item.snapshot()["owner_system_id"] == 0
    assert item.snapshot()["patrol"]["active"] is True
    item.handle(254, 190, encode_header(OWNERSHIP, 1, 0, REQUEST))
    reply = item.handle(254, 190, patrol_request(2, bytes([patrol.ACTION_STOP])))[0]
    assert reply[7] == APPLIED
    view = item.snapshot()["patrol"]
    assert view["active"] is False and view["reason"] == patrol.REASON_OPERATOR
    status = item.handle(254, 190, encode_header(STATUS, 3, 0, REQUEST))[0]
    assert patrol.decode_block(status[8 + 48 + 4 + 1:]).reason == patrol.REASON_OPERATOR
