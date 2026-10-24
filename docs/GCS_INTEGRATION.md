# Ground control station integration

The Jetson API does not play video on the Android controller. The Kotlin application uses the URLs this API returns and implements fallback itself.

## What to cache

Cache the last successful camera list:

- camera id and display name
- `direct_stream_url`
- `gateway_stream_url`
- the last settings response

Use the camera id everywhere. The display name can change.

## Playback order

1. Open `gateway_stream_url`.
2. If that player fails, open `direct_stream_url`.
3. Direct playback works only when the controller can route to the camera. VPN or mesh reachability is not implied by the URL.

The direct URL has no username or password. Store camera credentials in the controller's own protected storage if the camera requires them. Do not expect this API to return them.

## Two live views and a mosaic

The cockpit can show two individual streams at once. Any pair of ids is valid, for example `CAM-001` with `CAM-006`. Start each one:

```http
POST /api/v1/streams/CAM-001/start
{"mode": "passthrough"}
```

For a combined view, put the mosaic configuration, then start it, and play the single `gateway_stream_url` from `GET /api/v1/mosaic`. Send `expected_revision` after the first update so two controllers do not overwrite each other without noticing.

## Overlay text

Use `GET /api/v1/streams/{id}/metrics`.

- Show `measured_fps` and `measured_bitrate_kbps` when they are not null.
- Do not show `configured_fps` or `configured_bitrate_kbps` as if they were measurements.
- `last_frame_at` is null. Do not display a fake latency.

## Authentication later

While `auth.mode` is `disabled`, send no authorization header. When it is changed to `bearer`, send the token on every `/api/v1` request:

```text
Authorization: Bearer <token>
```

If RTSP playback authentication is also enabled, open:

```text
rtsp://gcs:<token>@<host>:8554/camera/CAM-001
```

## Example sequence

```text
GET  /api/v1/cameras
POST /api/v1/streams/CAM-001/start
GET  /api/v1/streams/CAM-001/metrics
PUT  /api/v1/mosaic
POST /api/v1/mosaic/start
```

A non-2xx body has the shape `{"error": {"code", "message", "request_id", "details"}}`.
