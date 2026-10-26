# Camera API

There are **15 camera routes** under `/api/v1`, plus two system routes that reread or report the camera service. MAVLink and the water mount are not on these routes.

Base URL: `http://<host>:8080`

Interactive schema: `http://<host>:8080/docs`

OpenAPI: `http://<host>:8080/openapi.json`

Authentication is off until `auth.mode` is `bearer`. Then every `/api/v1` route needs `Authorization: Bearer <token>`. Camera passwords are never in a response.

Every response includes `X-Request-ID`. Send that header to keep the same id in the audit log.

Errors use one shape:

```json
{"error": {"code": "not_found", "message": "...", "request_id": "...", "details": {}}}
```

A camera id is `CAM-001` through `CAM-999`. The gateway ships six records, `CAM-001` to `CAM-006`.

RTSP playback is not HTTP. The gateway publishes it on port `8554`:

```text
rtsp://<host>:8554/camera/CAM-001
rtsp://<host>:8554/mosaic
```

While `scripts/start-simulation.sh` is running, those same URLs serve the virtual cameras. Registry edits still go to the simulation camera file, not `config/cameras.json`.

## Route list

| Method | Path | What it does |
| --- | --- | --- |
| GET | `/api/v1/cameras` | List the registry |
| PATCH | `/api/v1/cameras/{camera_id}` | Change name, address, driver, or profile |
| GET | `/api/v1/cameras/{camera_id}/status` | Reachability and stream phase |
| POST | `/api/v1/cameras/{camera_id}/probe` | Contact that camera and store the report |
| GET | `/api/v1/cameras/{camera_id}/capabilities` | Last stored report, no camera contact |
| GET | `/api/v1/cameras/{camera_id}/settings` | Physical settings and gateway profile |
| PUT | `/api/v1/cameras/{camera_id}/settings` | Change the camera encoder, or store gateway overrides |
| POST | `/api/v1/streams/{camera_id}/start` | Passthrough (forward) or transcode (process) |
| POST | `/api/v1/streams/{camera_id}/stop` | Return the path to on-demand |
| GET | `/api/v1/streams/{camera_id}/metrics` | Configured values and the few measured ones |
| GET | `/api/v1/mosaic/layouts` | Layout names and camera counts |
| GET | `/api/v1/mosaic` | Current mosaic |
| PUT | `/api/v1/mosaic` | Replace the shared mosaic |
| POST | `/api/v1/mosaic/start` | Publish it |
| POST | `/api/v1/mosaic/stop` | Stop the publisher |
| GET | `/api/v1/audit/camera-configurations` | History of settings changes |

Related:

| Method | Path | What it does |
| --- | --- | --- |
| POST | `/api/v1/system/reload` | Reread `cameras.json` and `mosaic.json` |
| GET | `/api/v1/system/status` | Includes camera count and media-server state |

## How direct RTSP and gateway forwarding work

Each camera has two playback URLs.

`direct_stream_url` is the camera itself, with no username or password:

```text
rtsp://192.168.144.101:554/
```

The host, port, protocol, and path come from the registry. The ground station can open that URL only if it can reach the camera network and already has the password. The gateway does not put the password in this URL. `backup_stream_url` is the same value.

`gateway_stream_url` is the republished path:

```text
rtsp://<request-host>:8554/camera/CAM-001
```

The host is the host from the HTTP request, unless `streaming.advertise_host` is set.

Passthrough is the default forward. `POST /api/v1/streams/CAM-001/start` with `{"mode":"passthrough"}` tells MediaMTX to pull the camera and republish the same encoded video. The gateway does not decode it. The pull uses TCP. The source URL used internally can contain the username and password from `config/secrets.json`. That URL is not returned by the API.

Before start, the path is on demand. MediaMTX connects only when a player opens it, and it drops the source about 10 seconds after the last reader leaves. After start, `sourceOnDemand` is false, so the pull stays up. `POST .../stop` puts it back on demand and stops a transcoder if one is running. Stop is rejected with `stream_in_use` while a viewer is connected, unless the body is `{"force":true}`.

`{"mode":"transcode"}` is the other start mode. The gateway decodes the camera and encodes H.264 at the selected profile, or at the stored gateway overrides. The default limit is two transcodes. A third returns `resource_limit`. A normal camera view should use passthrough.

The mosaic is a third path. It is one composed H.264 stream at `rtsp://<host>:8554/mosaic`. Changing a tile does not change the camera. Viewers must open the URL again after `POST /api/v1/mosaic/start`.

## How camera configuration works

Three different writes exist. They do not do the same job.

**Registry.** `PATCH /api/v1/cameras/CAM-001` changes the record: name, enabled, manufacturer, model, host, port, protocol, path, ONVIF address, driver, or profile. The id stays the same. The file is written atomically and copied under `data/backups/`. If MediaMTX is running, that camera's source URL is updated. This does not talk to the camera and does not change its encoder.

**Probe.** `POST /api/v1/cameras/CAM-001/probe` is the call that opens a connection. `GET .../capabilities` only returns the last stored report.

The driver on the camera record chooses how:

- `auto` tries ONVIF, then describes the RTSP stream if ONVIF fails
- `onvif` uses ONVIF only
- `readonly_rtsp` can describe the active stream and refuses encoder changes
- `vendor` fails until a handler is registered

Unknown resolutions and frame rates stay null. The API does not invent them.

**Settings.** `PUT /api/v1/cameras/CAM-001/settings` has two targets.

`target: physical` sends codec, size, frame rate, bitrate, profile, and keyframe interval to the camera through ONVIF, then reads the encoder back when the camera allows it. `applied_to` is `physical`. A read-only camera returns `422` and code `physical_configuration_unsupported`. A gateway setting does not change the physical camera.

`target: gateway`, or `allow_gateway_processing: true`, stores a profile and size overrides on the gateway. `applied_to` is `gateway`. The camera encoder is not changed. The individual stream stays passthrough until a client starts it with `mode: transcode`.

Profiles in `config/profiles.json`:

| Profile | Size | fps | Bitrate |
| --- | --- | --- | --- |
| low | 960x540 | 25 | 500 kbps |
| medium | 1280x720 | 25 | 1500 kbps |
| high | 1920x1080 | 30 | 3500 kbps |
| custom | 1280x720 | 25 | 1500 kbps (caller overrides width, height, fps, bitrate) |

`profile` is `low`, `medium`, `high`, or `custom`. The `custom` entry is a fallback used only when no gateway overrides are stored. With `custom`, the gateway transcodes at the stored `gateway_overrides` (width, height, fps, bitrate_kbps). The minimum fps is 25 because the handset RTSP reader cannot sustain lower frame rates.

Both successful and rejected settings changes are listed by `GET /api/v1/audit/camera-configurations`.

Health checks are off by default, so an idle server does not contact `192.168.144.0/24`. `connection_status` stays `unknown` until health checks are enabled and have run.

## Cameras

### `GET /api/v1/cameras`

Request: none.

```json
{
  "items": [
    {
      "id": "CAM-001",
      "name": "Front",
      "enabled": true,
      "manufacturer": null,
      "model": null,
      "connection": {
        "host": "192.168.144.101",
        "port": 554,
        "protocol": "rtsp",
        "path": "/",
        "onvif_port": 80,
        "onvif_path": "/onvif/device_service"
      },
      "driver": "readonly_rtsp",
      "profile": "medium",
      "connection_status": "unknown",
      "network_reachable": null,
      "last_success_at": null,
      "stream_phase": "idle",
      "gateway_stream_url": "rtsp://127.0.0.1:8554/camera/CAM-001",
      "direct_stream_url": "rtsp://192.168.144.101:554/",
      "capabilities_known": false,
      "backup_stream_url": "rtsp://192.168.144.101:554/"
    }
  ],
  "count": 6
}
```

### `PATCH /api/v1/cameras/{camera_id}`

Every field is optional. Omitted fields stay as they are.

```json
{
  "name": "Front Camera",
  "enabled": true,
  "manufacturer": "Example",
  "model": "IPC",
  "host": "192.168.144.101",
  "port": 554,
  "protocol": "rtsp",
  "path": "/Streaming/Channels/101",
  "onvif_port": 80,
  "onvif_path": "/onvif/device_service",
  "driver": "auto",
  "profile": "medium"
}
```

`protocol` is `rtsp` or `rtsps`. `driver` is `auto`, `onvif`, `vendor`, or `readonly_rtsp`. `profile` is `low`, `medium`, `high`, or `custom`. `path` must start with `/` and must not contain `..`.

Response: the updated camera object.

Errors: `404 not_found`, `422 validation_failed`.

### `GET /api/v1/cameras/{camera_id}/status`

Request: none.

```json
{
  "camera_id": "CAM-001",
  "enabled": true,
  "network_reachable": null,
  "connection_status": "unknown",
  "last_success_at": null,
  "stream_phase": "idle",
  "last_error": null
}
```

`connection_status` is `unknown`, `online`, or `offline`.

### `POST /api/v1/cameras/{camera_id}/probe`

Request: none. This contacts the camera.

Response is a capability report:

```json
{
  "camera_id": "CAM-001",
  "source": "rtsp_probe",
  "probed_at": "2026-10-24T12:00:00+00:00",
  "codecs": ["h264"],
  "resolutions": [{"width": 1280, "height": 720}],
  "frame_rates": [15.0],
  "bitrate_kbps_min": null,
  "bitrate_kbps_max": null,
  "encoder_profiles": null,
  "configuration_supported": false,
  "limitations": [],
  "detected_width": 1280,
  "detected_height": 720,
  "detected_fps": 15.0,
  "detected_bitrate_kbps": null,
  "detected_codec": "h264"
}
```

`source` is `unknown`, `onvif`, `rtsp_probe`, or `vendor`. Fields the camera did not report are null.

Errors: `422 physical_configuration_unsupported`.

### `GET /api/v1/cameras/{camera_id}/capabilities`

Request: none. Response: the same capability report. This does not contact the camera. Before the first probe, `source` is `unknown` and the detected fields are null.

### `GET /api/v1/cameras/{camera_id}/settings`

Request: none.

```json
{
  "camera_id": "CAM-001",
  "physical": {
    "supported": false,
    "source": "unknown",
    "codec": null,
    "width": null,
    "height": null,
    "fps": null,
    "bitrate_kbps": null,
    "encoding_profile": null,
    "keyframe_interval": null,
    "stream_profile": null
  },
  "gateway_profile": "medium",
  "gateway_overrides": null,
  "applied_to": null,
  "note": "..."
}
```

`physical.supported` is false until a driver confirms encoder control.

### `PUT /api/v1/cameras/{camera_id}/settings`

Physical encoder change:

```json
{
  "target": "physical",
  "codec": "h264",
  "width": 1280,
  "height": 720,
  "fps": 15,
  "bitrate_kbps": 1500,
  "encoding_profile": "main",
  "keyframe_interval": 30,
  "stream_profile": null,
  "allow_gateway_processing": false
}
```

Gateway-only change:

```json
{
  "target": "gateway",
  "stream_profile": "low",
  "width": 640,
  "height": 360,
  "fps": 10,
  "bitrate_kbps": 500,
  "codec": "h264",
  "allow_gateway_processing": false
}
```

`target` defaults to `physical`. `fps` is 1 to 60. `keyframe_interval` is 1 to 300.

Response: the settings object, with `applied_to` set to `physical` or `gateway`. A gateway result says the physical camera was not changed and that passthrough continues until `mode` is `transcode`.

Errors: `404 not_found`, `422 validation_failed`, `422 physical_configuration_unsupported`.

## Streams

### `POST /api/v1/streams/{camera_id}/start`

Body is optional. The default mode is passthrough (forward). Use `transcode` to process (decode + re-encode at the stored gateway profile).

`stream` selects which camera RTSP path Jetson pulls: `main` (default) uses `connection.path`, `sub` uses `connection.sub_path` when set (falls back to `main`). Only meaningful for passthrough; transcode always uses the main path.

```json
{"mode": "passthrough", "stream": "main"}
```

```json
{"mode": "transcode"}
```

Response: the stream object, with `phase` `active` and `mode` set to the requested mode.

Errors: `404 not_found`, `409 camera_disabled`, `422 resource_limit`, `503 media_server_unavailable`.

### `POST /api/v1/streams/{camera_id}/stop`

Body is optional. `force` defaults to false.

```json
{"force": false}
```

Response: the stream object, with `phase` `idle` and `mode` `none`.

Errors: `409 stream_in_use`. `details.readers` is the viewer count.

### `GET /api/v1/streams/{camera_id}/metrics`

Request: none.

```json
{
  "camera_id": "CAM-001",
  "phase": "active",
  "connected": true,
  "configured_fps": 15.0,
  "measured_fps": null,
  "configured_bitrate_kbps": 1500,
  "measured_bitrate_kbps": null,
  "codec": "h264",
  "width": 1280,
  "height": 720,
  "last_frame_at": null,
  "uptime_seconds": 12.4,
  "reconnect_count": 0,
  "error": null,
  "measurement_notes": []
}
```

`configured_fps` and `configured_bitrate_kbps` come from the profile. They are not measurements. `measured_fps` and `last_frame_at` are always null, because passthrough is not decoded. `measured_bitrate_kbps` stays null until MediaMTX has produced two byte samples. `codec`, `width`, and `height` come from the RTSP server after it has seen the stream.

## Mosaic

### `GET /api/v1/mosaic/layouts`

Request: none.

```json
{
  "items": [
    {"name": "single", "camera_count": 1, "description": "One camera fills the canvas."},
    {"name": "side_by_side", "camera_count": 2, "description": "Two equal columns."},
    {"name": "three_focus", "camera_count": 3, "description": "One camera across the top and two cameras on the bottom row."},
    {"name": "grid_2x2", "camera_count": 4, "description": "Two rows of two cameras."},
    {"name": "five_3_over_2", "camera_count": 5, "description": "Three cameras on the top row and two cameras on the bottom row."},
    {"name": "grid_3x2", "camera_count": 6, "description": "Two rows of three cameras."},
    {"name": "custom", "camera_count": 0, "description": "Caller supplies tile geometry."}
  ],
  "count": 7
}
```

### `GET /api/v1/mosaic`

Request: none.

```json
{
  "revision": 1,
  "owner": null,
  "enabled": true,
  "layout": "grid_3x2",
  "output": {
    "width": 1920,
    "height": 1080,
    "fps": 15,
    "bitrate_kbps": 3000,
    "codec": "h264",
    "stream_name": "mosaic"
  },
  "camera_ids": ["CAM-001", "CAM-002", "CAM-003", "CAM-004", "CAM-005", "CAM-006"],
  "tiles": [
    {
      "camera_id": "CAM-001",
      "x": 0,
      "y": 0,
      "width": 640,
      "height": 540,
      "z": 0,
      "visible": true,
      "scaling": "fit",
      "source_profile": null,
      "preferred_source_fps": null
    }
  ],
  "gateway_stream_url": "rtsp://127.0.0.1:8554/mosaic",
  "running": false,
  "reconnect_required": false,
  "effective_output": {
    "width": 1920,
    "height": 1080,
    "fps": 15,
    "bitrate_kbps": 3000,
    "codec": "h264",
    "stream_name": "mosaic"
  },
  "adjustments": []
}
```

`scaling` is `fit`, `fill`, or `stretch`. Tile `x`, `y`, `width`, and `height` are even. `output.codec` is `h264`. `stream_name` is `mosaic`.

The simulation mosaic file uses 960x540 at 25 fps. Production `config/mosaic.json` is the 1920x1080 record.

### `PUT /api/v1/mosaic`

`layout` and `output` are required. After the first successful change, send `expected_revision` from the previous response.

```json
{
  "expected_revision": 1,
  "owner": "gcs-1",
  "enabled": true,
  "layout": "three_focus",
  "output": {
    "width": 1280,
    "height": 720,
    "fps": 15,
    "bitrate_kbps": 1500,
    "codec": "h264",
    "stream_name": "mosaic"
  },
  "camera_ids": ["CAM-001", "CAM-003", "CAM-005"],
  "tiles": null
}
```

For `custom`, `tiles` is required and `camera_ids` can be omitted. A named layout builds the tiles from `camera_ids`. The count must match the layout.

Response: the mosaic object. `revision` increases by one. `reconnect_required` becomes true until the mosaic is started again.

Errors: `409 revision_conflict`, `409 owner_conflict`, `422 validation_failed`, `422 resource_limit`.

### `POST /api/v1/mosaic/start`

Request: none. Response: the mosaic object, with `running` true after the publisher starts. An existing publisher is replaced. Players must reconnect.

Errors: `409 mosaic_disabled`, `503 media_server_unavailable`.

### `POST /api/v1/mosaic/stop`

Request: none. Response: the mosaic object, with `running` false.

## Audit

### `GET /api/v1/audit/camera-configurations`

Query: `camera_id`, `limit` from 1 to 200 (default 50), `offset` from 0.

```json
{
  "items": [
    {
      "id": 1,
      "timestamp": "2026-10-24T12:00:00+00:00",
      "camera_id": "CAM-001",
      "request_id": "abc",
      "success": false,
      "requested": {"target": "physical", "width": 1280, "height": 720},
      "previous": null,
      "confirmed": null,
      "error": "physical_configuration_unsupported"
    }
  ],
  "count": 1
}
```

Newest events are first.

## System routes that touch cameras

### `POST /api/v1/system/reload`

Request: none.

```json
{"reloaded": true, "request_id": "..."}
```

This rereads the camera registry and the mosaic file. A running mosaic is marked `reconnect_required`.

### `GET /api/v1/system/status`

The camera portion is:

```json
{
  "camera_count": 6,
  "cameras": {
    "count": 6,
    "media_server": "running",
    "health_checks": "stopped"
  }
}
```

`media_server` is `running` or `stopped`. `health_checks` is `running` only when `health.enabled` is true.

## Usual playback sequence

1. `PATCH` the path if `/` is not the camera's real RTSP path.
2. `POST /api/v1/streams/CAM-001/start` with `{"mode":"passthrough"}`.
3. Open `gateway_stream_url` in VLC or ffplay with RTSP over TCP.
4. Repeat for the other cameras, or `PUT` a layout and `POST /api/v1/mosaic/start`, then open `/mosaic`.
