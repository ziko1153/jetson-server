"""Verify the ESP32 keeps the last halted position across a reboot.

    .venv/bin/python scripts/rcwm-persist-check.py move    # set home, move, stop, print angle
    .venv/bin/python scripts/rcwm-persist-check.py check   # after a reboot: angle must match
"""

from __future__ import annotations

import json
import sys
import time

sys.path.insert(0, ".")

from pymavlink import mavutil
from pymavlink.dialects.v20 import common as mavlink

from app.rcwm.protocol import HOME, MOTION, OWNERSHIP, STATUS, STOP, encode_header, encode_motion

TARGET = "udpout:127.0.0.1:14550"
STATE = "data/rcwm_persist_angle.json"


def tunnel(body: bytes) -> list:
    payload = [0] * 128
    for index, value in enumerate(body[:128]):
        payload[index] = value
    return payload


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "move"
    mav = mavutil.mavlink_connection(TARGET, source_system=255, source_component=190)
    rid = [100]

    def send(opcode: int, payload: bytes = b"", axis: int = 0) -> None:
        body = encode_header(opcode, rid[0], axis, 0) + payload
        rid[0] += 1
        mav.mav.send(mavlink.MAVLink_tunnel_message(1, 171, 31000, len(body), tunnel(body)))

    def read_status(seconds: float = 1.5) -> bytes | None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            msg = mav.recv_match(type="TUNNEL", blocking=True, timeout=0.5)
            if msg is None:
                continue
            data = bytes(msg.payload)
            if data[:2] == b"RC" and data[3] == 1:
                return data
        return None

    send(OWNERSHIP)
    time.sleep(0.3)
    if mode == "move":
        send(HOME, axis=1)
        time.sleep(0.5)
        for _ in range(20):
            send(MOTION, encode_motion(8.0, 0.0, 0.0))
            time.sleep(0.1)
        send(STOP)
        time.sleep(0.8)
        send(STATUS)
        raw = read_status()
        assert raw is not None, "no status reply"
        steps = int.from_bytes(raw[20:24], "little", signed=True)
        degrees = int.from_bytes(raw[16:20], "little", signed=True) / 100.0
        print(json.dumps({"steps": steps, "degrees": degrees}))
        with open(STATE, "w") as handle:
            json.dump({"steps": steps, "degrees": degrees}, handle)
        print("moved: steps=%d angle=%.2f" % (steps, degrees))
        return 0

    send(STATUS)
    raw = read_status()
    assert raw is not None, "no status reply"
    axis_flags = raw[14]
    steps = int.from_bytes(raw[20:24], "little", signed=True)
    degrees = int.from_bytes(raw[16:20], "little", signed=True) / 100.0
    with open(STATE) as handle:
        saved = json.load(handle)
    print("after reboot: steps=%d angle=%.2f axisflags=0x%02x" % (steps, degrees, axis_flags))
    assert axis_flags & 0x02, "reference not restored after reboot"
    assert steps == saved["steps"], f"steps changed after reboot: {steps} vs {saved['steps']}"
    print("PASS: position and reference survived the reboot.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())