"""Live RCWM bench check: Jetson serial chain against the real ESP32.

Run with the ESP32 attached:
    .venv/bin/python scripts/rcwm-live-check.py

It takes ownership, writes a per-axis config to the ESP32 (persisted in NVS),
commands motion, and prints controller status frames. Motors must be free to
turn or the axis should be left unwired for this check.
"""

from __future__ import annotations

import sys
import time

sys.path.insert(0, ".")

from app.core.config import RcwmSettings
from app.rcwm.models import MotorConfig
from app.rcwm.protocol import (
    APPLIED,
    CONFIG_WRITE,
    HOME,
    MOTION,
    OWNERSHIP,
    STATUS,
    STOP,
    encode_config,
    encode_header,
    encode_motion,
)
from app.rcwm.service import RcwmService

PORT = "/dev/cu.usbserial-0001"
SYSTEM_ID = 255


def reply_result(body: bytes) -> tuple[int, int]:
    return body[3], body[7]


def main() -> int:
    settings = RcwmSettings(enabled=True, transport="serial", serial_port=PORT, allow_hardware_motion=True)
    service = RcwmService(settings, state_path="data/rcwm_live_check_state.json")
    service.start(background=False)
    seq = iter(range(1, 65_000))

    def request(opcode: int, payload: bytes = b"", axis: int = 0) -> list[bytes]:
        body = encode_header(opcode, next(seq), axis, 0) + payload
        return service.handle(SYSTEM_ID, 171, body)

    time.sleep(0.5)
    snap = service.snapshot()
    print("esp32:", snap["esp32"])
    print("active tilt:", snap["active_tilt"], "fault:", snap["fault_code"])

    print("ownership:", reply_result(request(OWNERSHIP)[0]))

    config = MotorConfig(
        enabled=True,
        steps_per_revolution=3200,
        gear_ratio=1.0,
        max_speed_dps=30.0,
        max_accel=100.0,
        max_decel=100.0,
        min_angle=None,
        max_angle=None,
        home_angle=0.0,
        deadband_percent=5,
    )
    for axis in (1, 2, 3):
        reply = request(CONFIG_WRITE, encode_config(config), axis=axis)[0]
        print(f"config write axis {axis}:", reply_result(reply))
        assert reply_result(reply)[1] == APPLIED, f"config write axis {axis} refused"

    print("set home pan:", reply_result(request(HOME, axis=1)[0]))

    for body in request(MOTION, encode_motion(20.0, 0.0, 0.0)):
        print("motion reply opcode", body[3], "result", body[7])

    for _ in range(12):
        service.maintain()
        time.sleep(0.1)
    snap = service.snapshot()
    pan = snap["axes"]["pan"]
    print("pan:", {k: pan[k] for k in ("enabled", "referenced", "reference_invalid", "direction", "estimated_deg", "estimated_steps")})
    print("active tilt:", snap["active_tilt"], "fault:", snap["fault_code"], "esp32:", snap["esp32"])

    print("stop:", reply_result(request(STOP)[0]))
    service.stop()
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())