# Vehicle services

MAVLink, the water mount, and host metrics are implemented beside the camera gateway.

Do not import `app.mavlink` or `app.rcwm` from camera, stream, or mosaic modules.
Do not add mount or flight commands to the camera HTTP routes.

- `app/mavlink/gateway.py` listens on UDP and forwards the Matek link
- `app/rcwm/` is the RCWM session, the serial protocol, and the macOS simulator
- `app/health/metrics.py` fills the existing system status route
- `firmware/esp32/` is the ESP32 firmware

Radio path priority stays in the ground station. See `docs/MAVLINK_GATEWAY.md`.
