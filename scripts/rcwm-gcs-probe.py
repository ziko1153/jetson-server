"""Act like the GCS over MAVLink: verify the fault-clears-on-stop recovery.

Sequence: ownership -> one motion frame -> link timeout (fault 7) -> STOP -> fault 0.
    .venv/bin/python scripts/rcwm-gcs-probe.py
"""

from __future__ import annotations

import sys
import time

sys.path.insert(0, ".")

from pymavlink import mavutil
from pymavlink.dialects.v20 import common as mavlink

from app.rcwm.protocol import HOME, MOTION, OWNERSHIP, STATUS, STOP, encode_header, encode_motion

TARGET = "udpout:127.0.0.1:14550"


def tunnel_payload(body: bytes) -> list:
    payload = [0] * 128
    for index, value in enumerate(body[:128]):
        payload[index] = value
    return payload


def main() -> int:
    mav = mavutil.mavlink_connection(TARGET, source_system=255, source_component=190)
    seq = iter(range(1, 65000))

    def send(opcode: int, payload: bytes = b"", axis: int = 0) -> None:
        mav.mav.send(
            mavlink.MAVLink_tunnel_message(
                1, 171, 31000, len(body := encode_header(opcode, next(seq), axis, 0) + payload),
                tunnel_payload(body),
            )
        )

    def drain(seconds: float) -> list:
        seen = []
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            msg = mav.recv_match(type="TUNNEL", blocking=True, timeout=0.5)
            if msg is None:
                continue
            data = bytes(msg.payload)
            if data[:2] != b"RC":
                continue
            seen.append((data[3], data[7], int.from_bytes(data[8:10], "little"), data[11], data[13]))
        return seen

    def latest_fault(events: list) -> int:
        return events[-1][4] if events else -1

    print("-- baseline status poll")
    send(STATUS)
    events = drain(1.5)
    for opcode, result, flags, owner, fault in events:
        print("  opcode=%d result=%d flags=0x%04x owner=%d fault=%d" % (opcode, result, flags, owner, fault))
    baseline_fault = latest_fault(events)
    assert baseline_fault == 0, f"fresh boot should report fault 0, got {baseline_fault}"

    print("-- take ownership")
    send(OWNERSHIP)
    drain(1.0)
    send(STATUS)
    events = drain(1.5)
    print("  owner now:", events[-1][3] if events else "?")
    assert events and events[-1][3] == 255, "ownership not confirmed"

    print("-- set home pan")
    send(HOME, axis=1)
    drain(0.8)

    print("-- one motion frame at 20 deg/s, then silence (link timeout expected)")
    send(MOTION, encode_motion(8.0, 0.0, 0.0))
    drain(0.2)
    for _ in range(3):
        send(STATUS)
        events = drain(1.0)
    timeout_fault = latest_fault(events)
    print("  fault after timeout window:", timeout_fault)
    assert timeout_fault == 7, f"expected latched FAULT_TIMEOUT (7), got {timeout_fault}"

    print("-- software STOP (what the GCS stop button sends)")
    send(STOP)
    drain(0.3)
    send(STATUS)
    events = drain(1.5)
    cleared = latest_fault(events)
    for opcode, result, flags, owner, fault in events:
        print("  opcode=%d result=%d flags=0x%04x owner=%d fault=%d" % (opcode, result, flags, owner, fault))
    assert cleared == 0, f"STOP should clear the fault, got {cleared}"

    print("-- sustained stick-like motion stream at 10 Hz for 2.5 s")
    for _ in range(25):
        send(MOTION, encode_motion(8.0, 0.0, 0.0))
        time.sleep(0.1)
    send(STATUS)
    events = drain(1.2)
    time.sleep(1.0)
    send(STATUS)
    events += drain(1.2)

    print("  replies:", len(events), "latest fault:", latest_fault(events))
    # Ask the controller directly through a fresh status read for the step count.
    send(STATUS)
    raw = None
    end = time.monotonic() + 1.5
    while time.monotonic() < end:
        msg = mav.recv_match(type="TUNNEL", blocking=True, timeout=0.5)
        if msg is None:
            continue
        data = bytes(msg.payload)
        if data[:2] != b"RC" or data[3] != 1:
            continue
        raw = data
    assert raw is not None, "no status reply"
    # RCWM header is 8 bytes, then flags u16, tilt, owner, version, fault,
    # then the pan axis block: flags, reserved, degrees x100, steps.
    axis_flags = raw[14]
    degrees = int.from_bytes(raw[16:20], "little", signed=True) / 100.0
    steps = int.from_bytes(raw[20:24], "little", signed=True)
    print("  pan after stream: steps=%d (~%.2f deg) axisflags=0x%02x" % (steps, degrees, axis_flags))
    assert abs(steps) > 100, f"pan did not accumulate steps during the stream (got {steps})"

    send(STOP)
    drain(0.3)
    print("PASS: fault latch clears on stop and sustained motion drives real steps.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())