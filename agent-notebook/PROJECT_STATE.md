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
