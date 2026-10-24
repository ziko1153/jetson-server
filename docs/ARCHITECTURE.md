# Architecture

The ground station uses HTTP for cameras and UDP for MAVLink. One process owns both. It also owns the camera registry, settings, audit log, and the lifetime of MediaMTX and FFmpeg or GStreamer.

```text
GCS
  |  HTTP /api/v1                         UDP :14550 MAVLink
  v                                       v
FastAPI                                   MAVLink gateway
  |-- camera registry                        |-- flight controller UART or SITL UDP
  |-- secrets and audit                      |-- RCWM service (component 171)
  |-- MediaMTX and mosaic                    +-- ESP32 USB serial, or the in-process simulator
  +-- GET /api/v1/system/status
        host metrics, camera, MAVLink, RCWM
```

## Modules

- `app/core` loads JSON config, detects the machine, and authenticates requests.
- `app/services/camera_registry.py` is the authority for camera identity. IDs do not follow IP addresses.
- `app/services/camera_configuration.py` separates physical encoder changes from gateway overrides.
- `app/cameras/drivers` contains ONVIF, a read-only RTSP probe, and an empty vendor-handler map.
- `app/media/backends` selects macOS, generic Linux, or Jetson.
- `app/media/rtsp/mediamtx.py` writes the MediaMTX config and updates paths through its localhost control API.
- `app/services/mosaic_manager.py` keeps one shared mosaic and a revision.
- `app/infrastructure/processes/supervisor.py` starts media processes from argument lists. It never uses a shell.
- `app/mavlink/gateway.py` is the UDP gateway.
- `app/rcwm/` is the water-mount session and the ESP32 simulator.
- `app/health/metrics.py` reads host metrics for the existing status route.

## Startup

`scripts/start.sh` runs Uvicorn. The application lifespan starts MediaMTX, if `streaming.manage_media_server` is true, and starts health checks only when `health.enabled` is true. It also starts the RCWM service and the MAVLink socket when those sections are enabled. Camera paths are `sourceOnDemand`, so MediaMTX does not connect to a camera until a stream is started or a player connects.

Shutdown stops MAVLink, the mount link, the mosaic, transcoders, health checks, and MediaMTX. `scripts/stop.sh` also stops any pid recorded under `data/run/` if the API process dies first.

`scripts/start-simulation.sh` is a development supervisor. It publishes local test patterns, or optional files and real RTSP sources, into a localhost MediaMTX, then starts this same gateway with `config/cameras.simulation.json`, `config/mosaic.simulation.json`, and `config/config.simulation.json`. The ground station still plays `camera/CAM-00N` and `mosaic` from the gateway RTSP port, and it still uses UDP 14550 for MAVLink. The simulation flight-controller socket is UDP 14551. See `docs/SIMULATION.md`.

## Vehicle services

Camera routes do not forward MAVLink and do not accept mount commands. `app/mavlink` listens on UDP. `app/rcwm` speaks the ground station's TUNNEL payload and the ESP32 serial protocol. `app/health` only fills `GET /api/v1/system/status`.

The gateway binds one UDP socket. GR03, mesh, and VPN are just addresses on that host. This process does not choose between them, and it does not replace the direct ground-station serial link to the Matek.

`firmware/esp32` is the water-mount controller. GPIO and the step algorithm stay there. The Jetson only sees the versioned serial frames.

## What is intentionally absent

There is no network-failover policy in this process. There is no MAVLink signing key, because the ground station does not sign. System ids 255 and 254 are an allowlist, not authentication. Software stop is not a hardware emergency stop.
