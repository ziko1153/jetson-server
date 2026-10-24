# Agent guide

Read these before changing the gateway:

1. `README.md`
2. `docs/ARCHITECTURE.md`
3. `agent-notebook/PROJECT_STATE.md`
4. `agent-notebook/DECISIONS.md`
5. `agent-notebook/KNOWN_ISSUES.md`
6. `agent-notebook/PENDING_WORK.md`

## Rules

- Understand the current architecture before editing.
- Keep the API contracts stable unless the change is documented in `docs/API.md`.
- Keep macOS and Jetson on the same Python source. Put hardware differences in `app/media/backends/` and the setup scripts.
- Do not treat ARM64 as a Jetson. Use `/etc/nv_tegra_release` or the device-tree model.
- Do not install CUDA, JetPack, TensorRT, or NVIDIA drivers from the setup scripts.
- Do not change Linux network interfaces from the application or the setup scripts.
- Do not scan the network for cameras. The registry is explicit.
- Do not put camera passwords or API tokens in committed JSON, logs, or API responses.
- Do not transcode an individual camera stream unless the client asks for `mode: transcode`.
- Do not pretend a gateway setting changed the physical camera.
- Do not claim a Jetson or real-camera test passed unless it was run on that hardware.
- Update tests when behavior changes.
- After a substantial session, update `agent-notebook/PROJECT_STATE.md`, `COMPLETED_WORK.md`, `PENDING_WORK.md`, and `SESSION_LOG.md`.
- `scripts/start-simulation.sh` is the macOS session. It uses `config/cameras.simulation.json`, `config/mosaic.simulation.json`, and `config/config.simulation.json`. Do not point it at `config/cameras.json` or change `config/config.json`. It must not change network interfaces. Production startup remains `scripts/start.sh`. The direct SITL router is paused while this session runs and restored by `scripts/stop-simulation.sh`.

## Authentication

The default is `auth.mode: disabled`. Bearer authentication already exists. Enable it in `config/config.json` and supply `UGV_API_TOKEN`. Add a new mode in `app/core/security.py` only if bearer is not enough.

## Vehicle services

MAVLink and the water-mount controller are `app/mavlink` and `app/rcwm`. Host metrics extend `GET /api/v1/system/status`. Do not put flight or mount commands on the camera routes, and do not gate UDP MAVLink with the HTTP bearer token.

The ESP32 protocol is `docs/RCWM_SERIAL_PROTOCOL.md`. GPIO and step timing stay in `firmware/esp32`. Do not hardcode a serial device path. Do not invent speed, acceleration, or travel limits. `rcwm.allow_hardware_motion` stays false until an operator confirms the emergency stop and the pin map.

System ids 255 and 254 with component 190 are an allowlist, not authentication. Do not add a second radio-failover policy. The direct ground-station link to the Matek stays independent.

Read `docs/MAVLINK_GATEWAY.md` and `docs/RCWM_INTEGRATION.md` before changing those paths. The Kotlin project is the message reference. Do not modify it from this repository.
