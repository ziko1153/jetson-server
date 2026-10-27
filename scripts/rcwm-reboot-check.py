"""Drive motion like the stick and report whether the ESP32 rebooted.

    .venv/bin/python scripts/rcwm-reboot-check.py
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request

sys.path.insert(0, ".")

from pymavlink import mavutil
from pymavlink.dialects.v20 import common as mavlink

from app.rcwm.protocol import MOTION, OWNERSHIP, SELECT, STOP, encode_header, encode_motion

TARGET = "udpout:127.0.0.1:14550"


def api_token() -> str:
    found: list[str] = []

    def walk(item) -> None:
        if isinstance(item, dict):
            for key, value in item.items():
                if isinstance(value, str) and ("token" in key.lower() or "key" in key.lower()):
                    found.append(value)
                walk(value)
        elif isinstance(item, list):
            for value in item:
                walk(value)

    walk(json.load(open("config/secrets.json")))
    return found[0] if found else ""


def boot_id(token: str) -> int | None:
    request = urllib.request.Request(
        "http://127.0.0.1:8080/api/v1/system/status", headers={"Authorization": f"Bearer {token}"}
    )
    data = json.load(urllib.request.urlopen(request, timeout=3))
    return data["rcwm"]["esp32"]["boot_id"]


def main() -> int:
    token = api_token()
    mav = mavutil.mavlink_connection(TARGET, source_system=255, source_component=190)
    rid = [5000]

    def send(opcode: int, payload: bytes = b"", axis: int = 0) -> None:
        body = encode_header(opcode, rid[0], axis, 0) + payload
        rid[0] += 1
        raw = [0] * 128
        for index, value in enumerate(body):
            raw[index] = value
        mav.mav.send(mavlink.MAVLink_tunnel_message(1, 171, 31000, len(body), raw))

    def stream(pan: float, tilt1: float, tilt2: float, seconds: float) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            send(MOTION, encode_motion(pan, tilt1, tilt2))
            time.sleep(0.1)

    send(OWNERSHIP)
    time.sleep(0.5)
    start = boot_id(token)
    print("boot id before:", start)

    for cycle in range(3):
        print(f"cycle {cycle + 1}: pan only, then stop")
        stream(5.0, 0.0, 0.0, 1.5)
        send(STOP)
        time.sleep(1.5)
        print("   boot id:", boot_id(token))

    send(SELECT, axis=3)
    time.sleep(0.5)
    print("pan + tilt2 together, then pan stops while tilt2 keeps running")
    stream(5.0, 0.0, 5.0, 1.0)
    stream(0.0, 0.0, 5.0, 1.0)
    send(STOP)
    time.sleep(1.5)
    end = boot_id(token)
    print("boot id after:", end)
    print("REBOOTED" if end != start else "NO REBOOT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
