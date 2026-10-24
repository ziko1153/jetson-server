# Troubleshooting

## The API does not start

Run `bash scripts/check-dependencies.sh`. The usual causes are a missing `.venv`, missing FFmpeg, or a missing MediaMTX binary. Run the platform setup script again. It will not download MediaMTX a second time if `vendor/mediamtx/mediamtx` is already executable.

## Port 8080 or 8554 is already in use

`bash scripts/stop.sh` stops the API and any pid under `data/run/`. A virtual-camera session also uses `8555` and `9998` on localhost. Stop that session with `bash scripts/stop-simulation.sh`. If a MediaMTX process was left from an older run, stop that pid and start again.

## A camera stream has no video

The default RTSP path is `/`. Set the real path with `PATCH /api/v1/cameras/CAM-001` and `{"path": "/the/real/path"}`, then start the stream. Credentials belong in `config/secrets.json`. The API will not show them.

`POST /streams/{id}/start` returns 503 when MediaMTX is not running. It returns 409 when the camera is disabled.

Health checks are off by default, so `connection_status: unknown` does not mean the camera is down. It means the gateway has not probed it.

## Capabilities are null

That is the state before a probe. `POST /api/v1/cameras/{id}/probe` contacts the camera. A read-only RTSP camera reports the active stream only and `configuration_supported: false`.

## Mosaic returns 409

Reload `GET /api/v1/mosaic` and send `expected_revision` from that response. If an owner is set, send the same owner or the current revision.

## Mosaic viewers see the old layout

`reconnect_required: true` means the file changed and the published stream did not. Call `POST /api/v1/mosaic/start` again. Playback stops while the new pipeline starts.

## Metrics show configured values but measured values are null

`configured_fps` and `configured_bitrate_kbps` come from the selected profile. `measured_bitrate_kbps` appears after two samples from MediaMTX. `measured_fps` and `last_frame_at` stay null. The gateway does not decode individual streams to invent those numbers.

## Authentication suddenly returns 401

`auth.mode` is `bearer`. Send `Authorization: Bearer <token>`. The token is `UGV_API_TOKEN` or `api_token` in the secrets file. With `playback_authentication` set to `bearer`, RTSP uses the user `gcs` and the same token.

## Jetson mosaic is using software encoding

`GET /api/v1/system/capabilities` lists which NVIDIA elements were found. A missing element selects FFmpeg. The setup script does not install a different JetPack to fill that gap.
