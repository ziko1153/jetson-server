# Pending work

- Replace the placeholder RTSP path `/` with the real path for each camera, and put credentials in `config/secrets.json`.
- Run `scripts/setup-jetson.sh` on the Orin NX. Read `GET /api/v1/system/capabilities` and the temperature and GPU fields in `GET /api/v1/system/status`.
- Play one camera, two cameras, a three-camera mosaic, and a six-camera mosaic from the Jetson over the GR03 network.
- Open the macOS simulation from the Skydroid G30 on GR03 LAN0.
- Confirm or fall back the NVIDIA GStreamer mosaic on that JetPack install.
- Enable `health.enabled` only after the Jetson can reach the cameras.
- Turn on `auth.mode: bearer` when the Kotlin application is ready to send the token.
- Implement the controller fallback described in `docs/GCS_INTEGRATION.md`. That code is not in this repository.
- Exercise stream recovery with a camera that actually disconnects.
- Set the Matek UART and confirm telemetry with a real flight controller. Rover SITL through the simulation flight-controller socket was checked on this Mac with a stand-in ground station, not from the Skydroid G30.
- Flash the ESP32 only after the emergency stop and `board.hpp` pin map are confirmed, then set `rcwm.serial_port` and, separately, `rcwm.allow_hardware_motion`.
- Decide whether MAVLink 2 signing should be added on both the Jetson and the Kotlin ground station. It is not implemented on either side.

## From 2026-11-03

- Per-camera `transcode` runs `ffmpeg` with `libx264` on the CPU. A hardware path (`nvv4l2decoder` and `nvv4l2h264enc`, as the mosaic does) belongs in `app/media/backends/jetson.py`.
- Consider swapping `path` and `sub_path` in `config/cameras.json` so `main` means the camera's MainStream. Check the mosaic and transcode load first.
- Encoder `PUT` and PTZ moves have only been exercised with unit tests. An operator should try them on one camera.

## From 2026-11-06

- Flash the ESP32 with the output and patrol firmware and check each SSR with a meter. GPIO 14 pulses during boot; confirm the SSR load tolerates it or move MG FIRE. GPIO 16 and 17 are free only on a WROOM module, not WROVER.
- Pull the updated code onto the Jetson and restart the gateway. Until then the GCS reports that the controller has not sent its fire outputs.
- Check on hardware that fire outputs drop on lease loss, on release, and after the 5 s ESP32 watchdog.
- Try pan patrol on the real mount with a narrow range first. It needs pan limits, speed, acceleration, deceleration and home set, and `allow_hardware_motion` true.
