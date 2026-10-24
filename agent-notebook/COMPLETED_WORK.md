# Completed work

- FastAPI application, JSON configuration, structured logs, SQLite audit log, and atomic registry writes.
- Six-camera registry with stable ids and editable names, addresses, and RTSP paths.
- ONVIF client, read-only RTSP probe, and a vendor-driver map with no handlers registered.
- Disabled-by-default bearer authentication and optional RTSP playback authentication.
- Environment detection that does not treat ARM64 as a Jetson.
- MediaMTX passthrough for individual cameras and an FFmpeg mosaic that was played locally.
- Jetson backend that selects NVIDIA GStreamer elements only when they are present.
- macOS setup script, Jetson setup script, start/stop/restart, systemd unit, and dependency checks.
- Unit, integration, and local virtual-camera tests.
- A persistent macOS simulation: `scripts/start-simulation.sh` and `scripts/stop-simulation.sh`, with the camera files, the flight-controller UDP settings, and Rover SITL kept separate from production config.
- MAVLink UDP gateway with Matek forwarding, SITL UDP, component 191 and 171 heartbeats, and RCWM routing.
- RCWM session for two ground stations, simulated ESP32, and the versioned USB serial protocol.
- ESP32 PlatformIO firmware that refuses to pulse GPIO until the pin map is confirmed, plus a host build of the codec and planner.
- System status extended with host, camera, MAVLink, ESP32, and RCWM fields.
