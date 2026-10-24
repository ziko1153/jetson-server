# Test results

Run on this Mac, 24 October 2026.

## Unit and integration

Command: `.venv/bin/python -m pytest -m "not e2e"`

Result: 31 passed.

Covered: registry, rename persistence, validation, unknown capabilities, read-only encoder refusal, gateway settings, disabled and bearer authentication, mosaic revision conflicts, layout geometry, Jetson-versus-software command selection, MediaMTX config, stream phase changes, and reconnect accounting.

These tests do not open connections to `192.168.144.0/24`.

## End to end

Command: `.venv/bin/python -m pytest tests/e2e/test_virtual_streams.py`

Result: 1 passed in about 52 seconds.

Local FFmpeg test patterns were published into a local MediaMTX. The gateway then:

- published `CAM-001` and `CAM-002` as H.264 640x360, confirmed with ffprobe
- published a three-camera mosaic at 640x360, confirmed with ffprobe
- published a six-camera mosaic at 960x540, confirmed with ffprobe

## Live API smoke

`bash scripts/start.sh --detach` then:

- `GET /api/v1/health` returned `status: ok`, hardware `macos`, media server `running`
- `GET /api/v1/cameras` returned six cameras
- `/openapi.json` and `/docs` returned HTTP 200

`bash scripts/stop.sh` then left ports 8080 and 8554 closed.

## Phase 2

Command: `.venv/bin/python -m pytest -m "not e2e"`

Result: 44 passed.

Added coverage: RCWM codec and serial frames, three motor configs, ownership for systems 255 and 254, tilt switching, set-home estimates, restart clearing the reference, command timeout, duplicate motion, hardware-motion lock, MAVLink routing, component 191 and 171 heartbeats, a local UDP stand-in for SITL telemetry, and system status on macOS.

Command: `bash scripts/test-firmware-host.sh`

Result: passed. The host binary compiled the frame codec and the step planner. It did not flash an ESP32 and did not enable GPIO.

## macOS simulation

Command: `bash scripts/start-simulation.sh --detach`

Result on this Mac: ffprobe over RTSP TCP saw `CAM-001` through `CAM-006` as H.264 Constrained Baseline, 640x360, `yuv420p`, and `/mosaic` as H.264, 960x540, `yuv420p`. `PUT /api/v1/mosaic` to `three_focus`, followed by `POST /api/v1/mosaic/start`, published that mosaic. `bash scripts/stop-simulation.sh` then left ports 8080, 8554, and 8555 closed.

`config/cameras.json` still points at `192.168.144.101`–`106`. `config/config.json` still has `mavlink.flight_controller.transport` set to `none`.

## Rover SITL through the simulation

Command: `bash scripts/start-simulation.sh --detach`

Result on this Mac: one `rover-skid` SITL process, system 1, sending to UDP `127.0.0.1:14551`. The gateway status showed that socket connected and the RCWM transport as `simulation`. A local UDP peer at system 255 component 190 received a rover heartbeat from system 1 component 1 and read `MAV_SYSID` back as 1. `ffprobe` saw `CAM-002` as H.264 640x360. `mavp2p` was not forwarding to 14550 during the run. The Skydroid G30 was not used.

## Not run

- Jetson Orin NX
- Real IP cameras
- ONVIF against a camera
- A disconnect and reconnect of a live camera
- Matek H743 UART
- Skydroid G30 playback or MAVLink
- ESP32 flash or a USB motor test
- Physical emergency-stop check
