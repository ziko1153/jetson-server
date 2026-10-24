# Camera configuration

There are two different operations.

## Physical encoder settings

`PUT /api/v1/cameras/{id}/settings` with `"target": "physical"` sends the change to the camera through ONVIF. The service then reads the encoder configuration back when the camera allows it. The response field `applied_to` is `physical`.

The driver is selected per camera:

- `auto` tries ONVIF, then describes the active RTSP stream if ONVIF is unavailable
- `onvif` uses ONVIF only
- `readonly_rtsp` can describe the active stream and refuses encoder changes
- `vendor` fails until a handler is registered in `app/cameras/drivers/vendor.py`

RTSP probing does not list every encoder option. Unknown capabilities stay `null`. The API does not invent resolutions or frame rates.

`POST /api/v1/cameras/{id}/probe` is the call that contacts the camera. `GET /capabilities` returns the last stored report and does not open a connection. Before the first probe the source is `unknown`.

## Gateway settings

`"target": "gateway"`, or `allow_gateway_processing: true`, stores a profile and overrides on the gateway. The camera encoder is not changed. Individual streams stay in passthrough until a client starts that camera with `"mode": "transcode"`.

Tile size in a mosaic is also a gateway setting. Changing a tile does not change the camera.

## Credentials and persistence

Passwords live in `config/secrets.json` under the camera id. The registry stores `credentials_ref` only. API responses omit credentials, including the direct RTSP URL.

Registry edits are validated, written atomically, copied to `data/backups/`, and the MediaMTX path is updated when the RTSP server is running. Configuration attempts, including rejected ones, are stored in `data/audit.db` and listed at `GET /api/v1/audit/camera-configurations`.

## Defaults

`config/cameras.json` uses `192.168.144.101` through `192.168.144.106`, port `554`, and path `/`. Replace the path with the real camera path before expecting video. Health checks stay disabled so the development machine does not probe those addresses.
