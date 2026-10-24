# API

Base URL: `http://<host>:8080`

Interactive schema: `http://<host>:8080/docs`

OpenAPI: `http://<host>:8080/openapi.json`

The versioned API is `/api/v1`. Authentication is disabled until `auth.mode` is `bearer`. Then every `/api/v1` route requires `Authorization: Bearer <token>`, except paths listed in `auth.exempt_paths`.

Errors use one shape:

```json
{"error": {"code": "not_found", "message": "...", "request_id": "...", "details": {}}}
```

`X-Request-ID` is returned on every response. Send one to keep the same id in the audit log.

RTSP URLs below use the request host unless `streaming.advertise_host` is set.

## Service

### `GET /`

Purpose: identify the process.

Authentication: none.

```bash
curl -sS http://127.0.0.1:8080/
```

Response: `{"name": "ugv-jetson-gateway", "api": "/api/v1", "docs": "/docs"}`

### `GET /api/v1/health`

Purpose: process health.

```bash
curl -sS http://127.0.0.1:8080/api/v1/health
```

Response includes `status`, `hardware`, `auth`, and `media_server` (`running` or `stopped`).

### `GET /api/v1/system/capabilities`

Purpose: platform and media detection.

```bash
curl -sS http://127.0.0.1:8080/api/v1/system/capabilities
```

Response includes `environment`, `media_backend`, and the `low`, `medium`, and `high` profiles. `nvidia_encoder` is false unless the Jetson plugins were found.

### `GET /api/v1/system/status`

Purpose: gateway uptime, camera service state, host metrics, MAVLink, and RCWM. This is the only system-status route.

```bash
curl -sS http://127.0.0.1:8080/api/v1/system/status
```

The original fields remain: `started_at`, `uptime_seconds`, `auth_mode`, `health_checks_enabled`, `camera_count`, and `resources`.

Added objects:

- `cameras` — media server and camera health-check state
- `host` — CPU, memory, disk, host uptime, `temperature_c`, `gpu_percent`, `nvidia_metrics`, Jetson model, L4T, and JetPack family
- `mavlink` — bind address, peers, flight-controller link, and forward counters
- `rcwm` and `esp32` — mount transport, ownership, connection, and estimated axes

On macOS, `temperature_c` and `gpu_percent` are null and `nvidia_metrics` is `unavailable`. A missing sensor is null on a Jetson as well. The route does not invent a measurement.

RCWM angles are estimates. `software_stop_is_hardware_estop` is false. MAVLink vehicle commands are not sent through this HTTP route.

### `POST /api/v1/system/reload`

Purpose: reread `cameras.json` and `mosaic.json` from disk.

```bash
curl -sS -X POST http://127.0.0.1:8080/api/v1/system/reload
```

Response: `{"reloaded": true, "request_id": "..."}`. A running mosaic is marked `reconnect_required`.

## Cameras

Request and response bodies for every camera, stream, and mosaic route are in `docs/CAMERA_API.md`.

### `GET /api/v1/cameras`

Purpose: list the registry.

```bash
curl -sS http://127.0.0.1:8080/api/v1/cameras
```

Each item has `id`, `name`, `enabled`, `manufacturer`, `model`, `connection`, `driver`, `profile`, `connection_status`, `network_reachable`, `last_success_at`, `stream_phase`, `gateway_stream_url`, `direct_stream_url`, `backup_stream_url`, and `capabilities_known`.

There is no password field. `direct_stream_url` and `backup_stream_url` are the same credential-free camera URL.

### `GET /api/v1/cameras/{camera_id}`

Purpose: one camera.

Errors: `404 not_found` for an unknown id.

```bash
curl -sS http://127.0.0.1:8080/api/v1/cameras/CAM-001
```

### `PATCH /api/v1/cameras/{camera_id}`

Purpose: change the name, enable flag, manufacturer, model, host, port, protocol, path, ONVIF address, driver, or profile. The id does not change.

```bash
curl -sS -X PATCH http://127.0.0.1:8080/api/v1/cameras/CAM-001 \
  -H 'content-type: application/json' \
  -d '{"name":"Front Camera","path":"/Streaming/Channels/101"}'
```

Errors: `404` unknown id, `422 validation_failed` for a bad host or path.

### `GET /api/v1/cameras/{camera_id}/status`

Purpose: reachability and stream phase. `connection_status` is `unknown` until health checks are enabled and have run.

```bash
curl -sS http://127.0.0.1:8080/api/v1/cameras/CAM-001/status
```

### `GET /api/v1/cameras/{camera_id}/capabilities`

Purpose: last stored capability report. This does not contact the camera.

```bash
curl -sS http://127.0.0.1:8080/api/v1/cameras/CAM-001/capabilities
```

Before a probe, `source` is `unknown` and codec, resolution, and frame-rate fields are null.

### `POST /api/v1/cameras/{camera_id}/probe`

Purpose: contact that camera and store the report. This is the call that opens a network connection.

```bash
curl -sS -X POST http://127.0.0.1:8080/api/v1/cameras/CAM-001/probe
```

Errors: `422 physical_configuration_unsupported` when the selected driver cannot reach the camera.

### `GET /api/v1/cameras/{camera_id}/settings`

Purpose: physical settings and gateway profile, kept separate.

```bash
curl -sS http://127.0.0.1:8080/api/v1/cameras/CAM-001/settings
```

`physical.supported` is false until a driver confirms encoder control. `gateway_profile` is `low`, `medium`, or `high`.

### `PUT /api/v1/cameras/{camera_id}/settings`

Purpose: change physical encoder settings, or store gateway overrides.

Physical:

```bash
curl -sS -X PUT http://127.0.0.1:8080/api/v1/cameras/CAM-001/settings \
  -H 'content-type: application/json' \
  -d '{"target":"physical","width":1280,"height":720,"fps":15,"bitrate_kbps":1500,"codec":"h264"}'
```

Gateway only:

```bash
curl -sS -X PUT http://127.0.0.1:8080/api/v1/cameras/CAM-001/settings \
  -H 'content-type: application/json' \
  -d '{"target":"gateway","stream_profile":"low","width":640,"height":360}'
```

A successful body includes `applied_to` of `physical` or `gateway`. A read-only camera returns `422` with code `physical_configuration_unsupported`. Both results are written to the audit log.

## Streams

### `GET /api/v1/streams`

Purpose: phase and URLs for every camera.

```bash
curl -sS http://127.0.0.1:8080/api/v1/streams
```

`phase` is `idle` or `active`. `mode` is `none`, `passthrough`, or `transcode`.

### `GET /api/v1/streams/{camera_id}`

```bash
curl -sS http://127.0.0.1:8080/api/v1/streams/CAM-001
```

### `POST /api/v1/streams/{camera_id}/start`

Purpose: pull the camera through MediaMTX, or transcode it.

```bash
curl -sS -X POST http://127.0.0.1:8080/api/v1/streams/CAM-001/start \
  -H 'content-type: application/json' \
  -d '{"mode":"passthrough"}'
```

Passthrough remuxes. `transcode` decodes and encodes with the gateway profile. Errors: `409 camera_disabled`, `422 resource_limit` when the transcode limit is reached, `503 media_server_unavailable`.

### `POST /api/v1/streams/{camera_id}/stop`

Purpose: return the path to on-demand and stop a transcoder.

```bash
curl -sS -X POST http://127.0.0.1:8080/api/v1/streams/CAM-001/stop \
  -H 'content-type: application/json' \
  -d '{"force":false}'
```

Errors: `409 stream_in_use` when a viewer is connected and `force` is false.

### `GET /api/v1/streams/{camera_id}/metrics`

Purpose: separate configured values from measured values.

```bash
curl -sS http://127.0.0.1:8080/api/v1/streams/CAM-001/metrics
```

`configured_fps` and `configured_bitrate_kbps` come from the profile. `measured_fps` and `last_frame_at` are null. `measured_bitrate_kbps` is null until two MediaMTX byte samples exist. `codec`, `width`, and `height` come from the RTSP server when it has seen the stream.

## Mosaic

### `GET /api/v1/mosaic/layouts`

```bash
curl -sS http://127.0.0.1:8080/api/v1/mosaic/layouts
```

### `GET /api/v1/mosaic`

Purpose: current revision, tiles, output, and whether viewers must reconnect.

```bash
curl -sS http://127.0.0.1:8080/api/v1/mosaic
```

### `PUT /api/v1/mosaic`

Purpose: replace the shared mosaic.

```bash
curl -sS -X PUT http://127.0.0.1:8080/api/v1/mosaic \
  -H 'content-type: application/json' \
  -d '{"layout":"three_focus","owner":"gcs-1","output":{"width":1280,"height":720,"fps":15,"bitrate_kbps":1500,"codec":"h264"},"camera_ids":["CAM-001","CAM-003","CAM-005"]}'
```

After the first change, send `expected_revision` from the previous response. Errors: `409 revision_conflict`, `409 owner_conflict`, `422 validation_failed`, `422 resource_limit`.

The macOS simulation uses these same routes. While `scripts/start-simulation.sh` is running, mosaic updates are stored in `config/mosaic.simulation.json`. See `docs/SIMULATION.md`.

### `POST /api/v1/mosaic/start`

Purpose: publish the current mosaic. This interrupts an existing mosaic publisher.

```bash
curl -sS -X POST http://127.0.0.1:8080/api/v1/mosaic/start
```

Errors: `409 mosaic_disabled`, `503 media_server_unavailable`.

### `POST /api/v1/mosaic/stop`

```bash
curl -sS -X POST http://127.0.0.1:8080/api/v1/mosaic/stop
```

### `GET /api/v1/mosaic/status`

Purpose: running flag, pid, restart count, backend name, and acceleration (`software` or `nvidia`).

```bash
curl -sS http://127.0.0.1:8080/api/v1/mosaic/status
```

## Audit

### `GET /api/v1/audit/camera-configurations`

Query: `camera_id`, `limit` (1 to 200, default 50), `offset`.

```bash
curl -sS 'http://127.0.0.1:8080/api/v1/audit/camera-configurations?limit=20'
```

Each item has `timestamp`, `camera_id`, `request_id`, `success`, `requested`, `previous`, `confirmed`, and `error`.
