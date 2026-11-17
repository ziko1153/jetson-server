# Project state

The camera gateway and the phase-2 vehicle services run from the same Python tree. On this Mac the mount is simulated, MAVLink listens on UDP 14550 when the server is started, and the Matek serial port is not opened.

Authentication is implemented and left disabled. Camera health probes are implemented and left disabled, so an idle server does not contact `192.168.144.0/24`.

`rcwm.allow_hardware_motion` is false. The ESP32 pin map is unconfirmed, so the firmware will not pulse drivers until that file is edited and the flag is turned on.

Verified on this machine:

- unit and integration tests, including MAVLink routing, RCWM ownership, and system status
- the firmware host build of the serial codec and the step planner
- the earlier camera end-to-end test, which is unchanged apart from leaving the new services off
- `scripts/start-simulation.sh` on this Mac: six H.264 640x360 gateway streams and a 960x540 mosaic, confirmed with ffprobe. A live mosaic layout change to `three_focus` published again. The session was then stopped.

Not run on a Jetson, a Matek, a real ESP32, or the Skydroid G30. Rover SITL was connected through the simulation flight-controller UDP socket and checked with a local ground-station stand-in. The camera simulation was not opened from the G30.

Default camera records remain `CAM-001` through `CAM-006` at `192.168.144.101`–`106`, RTSP port `554`, path `/`. Simulation playback uses `config/cameras.simulation.json`. Production `config/config.json` leaves the flight-controller transport at `none`.

## RCWM water outputs (2026-11-06, Mac only)

The ESP32 firmware drives three SSR outputs, active high: MG FIRE on GPIO 14 (Tilt 1), RL-1 on GPIO 16 and RL-2 on GPIO 17 (Tilt 2). They are set with serial frame type 15 and MAVLink RC opcode 12, owner only. Outputs are off at boot, when the Jetson lease ends or control is released, and after 5 s with no valid serial frame. STATUS carries the mask after the 48-byte body. The stepper code was not changed. Verified with `pio run -e esp32dev`, the firmware host tests and the Python unit tests. Not flashed and not run on a real ESP32, SSR, or the Jetson.

## RCWM pan patrol (2026-11-06, Mac only)

Pan patrol runs on the ESP32 (`patrol.hpp`, serial type 16) and is requested with MAVLink RC opcode 13, owner only; the Jetson refuses a start with SAFETY while `allow_hardware_motion` is false on a serial transport. The range must sit inside the applied pan limits and the speed at or below the pan maximum, and the firmware rechecks both every loop. Joystick pan is refused while patrolling; tilt still works. Patrol survives link loss, STOP and lease expiry. STATUS carries an 8-byte patrol block after the outputs byte. The simulator implements the same rules. Verified with host tests, `pio run` and the Python tests. Not run on hardware.

## Camera control (2026-11-03, on the Jetson)

ONVIF Media2 encoders and PTZ are served under `/api/v1/cameras/{id}/encoders` and `/ptz`. Each stream start is remembered and restored after a restart. Camera health checks run every 10 s. Verified read-only on CAM-001, CAM-002 and CAM-004; encoder writes and PTZ moves have not been sent to a real camera by an agent.
