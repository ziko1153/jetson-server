# Mosaic

There is one shared mosaic at `rtsp://<host>:8554/mosaic`. Starting it replaces the previous publisher. Viewers have to reconnect after a start.

## Layouts

| Name | Cameras | Arrangement |
|---|---|---|
| `single` | 1 | One camera fills the canvas |
| `side_by_side` | 2 | Two equal columns |
| `three_focus` | 3 | One camera on top, two on the bottom |
| `grid_2x2` | 4 | Two rows of two |
| `five_3_over_2` | 5 | Three on top, two on the bottom |
| `grid_3x2` | 6 | Two rows of three |
| `custom` | 1 to 6 | Caller supplies even pixel geometry |

`GET /api/v1/mosaic/layouts` returns this list. Preset tiles are generated from the canvas size. They are not camera encoder settings.

Custom tiles must lie inside the canvas, use even coordinates, and cannot repeat a camera. `fit` pads, `fill` crops, and `stretch` scales to the tile.

## Output

The composed stream is one H.264 video at the requested width, height, frame rate, and bitrate. A mosaic does not keep each camera's original frame rate in the output. The output frame rate is the mosaic frame rate.

Limits in `config/config.json` reject an output above 1920x1080, 30 fps, or 8000 kbps. Raise the limits there if a later vehicle test shows the Orin NX can sustain more. Do not raise them just to silence the error.

## Revisions

The stored revision starts at 1. The first update may omit `expected_revision`. After that, an update must send the current revision, or the current `owner` must match. A mismatch returns HTTP 409. Updating the mosaic while it is running sets `reconnect_required` and leaves the old stream up until `POST /api/v1/mosaic/start`.

## Pipelines

macOS and generic Linux run FFmpeg `libx264`. A Jetson uses `nvv4l2decoder`, `nvvidconv`, and `nvv4l2h264enc` only when `gst-inspect-1.0` finds all three. Otherwise it uses the same FFmpeg pipeline and says `acceleration: software` on `GET /api/v1/system/capabilities`.

The NVIDIA pipeline has not been played on an Orin NX yet. Treat it as implemented and unverified.
