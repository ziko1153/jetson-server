# UGV Jetson Camera Gateway

The gateway is the camera and video service for the UGV. The ground control station asks this service for the camera list, camera settings, individual RTSP streams, and one shared mosaic. The same Python application runs on macOS for development and on a Jetson Orin NX for the vehicle. Platform differences stay in setup scripts and the media backend.

Camera health checks are off until `health.enabled` is set to `true`. An idle server does not connect to the cameras. Streams are pulled only after a client starts them or plays the RTSP URL.

## Platforms

- macOS, for development, with software FFmpeg
- Generic Linux, with software FFmpeg
- NVIDIA Jetson, with NVIDIA GStreamer elements only when those elements are installed

ARM64 by itself is not treated as a Jetson.

## Requirements

- Python 3.10 or newer
- FFmpeg and ffprobe
- MediaMTX v1.21.2, installed by the setup script into `vendor/mediamtx/`
- On the Jetson, the JetPack GStreamer plugins that are already installed. The setup script does not install CUDA, JetPack, or drivers.

## Install and run on macOS

```bash
bash scripts/setup-mac.sh
bash scripts/start.sh
```

The API is `http://127.0.0.1:8080`. Interactive docs are `http://127.0.0.1:8080/docs`.

Stop a background server with `bash scripts/stop.sh`. `bash scripts/start.sh --detach` runs it in the background.

## Cameras

Six cameras are defined in `config/cameras.json`. Their IDs are `CAM-001` through `CAM-006`. Names, addresses, ports, and RTSP paths are editable there or through `PATCH /api/v1/cameras/{id}`. The default path `/` is a placeholder, not a claim about the real cameras.

Usernames and passwords belong in `config/secrets.json`, which is not committed. Copy `config/secrets.example.json`.

## RTSP

Individual streams:

```text
rtsp://<jetson-host>:8554/camera/CAM-001
```

The shared mosaic:

```text
rtsp://<jetson-host>:8554/mosaic
```

Set `streaming.advertise_host` in `config/config.json` when the URL returned to the ground station must use a specific address, such as `192.168.144.20`. If it is empty, the API uses the host from the request.

Individual streams are remuxed. They are not decoded. The mosaic is decoded, composed, and encoded as one H.264 stream.

## Vehicle link

The same process listens for MAVLink on UDP port 14550 and answers the water-mount protocol. The camera routes do not carry flight or mount commands. On a Mac the mount runs in simulation and no serial port is opened. Motor output stays disabled until `rcwm.allow_hardware_motion` is turned on and the ESP32 pin map is confirmed.

`GET /api/v1/system/status` includes host metrics, the MAVLink link, and the mount. NVIDIA temperature and GPU load are null on macOS.

Details are in `docs/MAVLINK_GATEWAY.md`, `docs/RCWM_INTEGRATION.md`, and `docs/ESP32_FIRMWARE.md`.

## Authentication

`auth.mode` is `disabled`. To require a bearer token later, set `auth.mode` to `bearer` and put the token in `UGV_API_TOKEN` or `api_token` inside `config/secrets.json`. No route code has to change. RTSP playback stays open unless `streaming.playback_authentication` is also set to `bearer`. In that mode the RTSP user is `gcs` and the password is the same token.

## Tests

```bash
.venv/bin/python -m pytest
```

The end-to-end test publishes local test patterns. It does not contact `192.168.144.0/24`.

## macOS simulation

`bash scripts/start-simulation.sh` keeps six virtual cameras, one mosaic, the RCWM simulator, and Rover SITL running for VLC or the Kotlin ground station. Stop it with `bash scripts/stop-simulation.sh`. It does not modify `config/cameras.json` or `config/config.json`, and it does not change network interfaces. Stopping it restores the direct SITL router.

```text
rtsp://127.0.0.1:8554/camera/CAM-001
rtsp://127.0.0.1:8554/mosaic
```

Player commands and the GR03 bind setting are in `docs/SIMULATION.md`.

## More detail

- `docs/API.md`
- `docs/ARCHITECTURE.md`
- `docs/CAMERA_CONFIGURATION.md`
- `docs/MOSAIC.md`
- `docs/NETWORK.md`
- `docs/MAC_DEVELOPMENT.md`
- `docs/SIMULATION.md`
- `docs/JETSON_DEPLOYMENT.md`
- `docs/GCS_INTEGRATION.md`
- `docs/TROUBLESHOOTING.md`
- `AGENTS.md`
