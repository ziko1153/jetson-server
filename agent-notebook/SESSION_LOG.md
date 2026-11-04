# Session log

## 2026-10-24

Built the first working gateway from `initial-plan.md`.

Choices confirmed before coding:

- generic ONVIF plus read-only RTSP
- no network scanning and no camera contact during development
- default addresses `192.168.144.101`–`106`
- one shared mosaic
- authentication implemented but disabled

Tests and a local API smoke test were run on macOS. Jetson hardware was not available.

## 2026-10-24 later

Added the MAVLink gateway, the RCWM service, the ESP32 firmware tree, and the system-status fields from `plan/eps32-plan.md`.

The Kotlin ground station was read and not modified. Replies follow its TUNNEL layout. Motor limits were left unset. Hardware motion stays off. Tests were run on this Mac, including a UDP heartbeat stand-in for SITL and a host compile of the firmware core. No Jetson, Matek, or ESP32 was attached.

## 2026-10-24 simulation

Added a continuous macOS simulation in front of the existing gateway. `config/cameras.json` stays on the vehicle addresses. Local patterns publish through the gateway at `rtsp://127.0.0.1:8554/camera/CAM-001` through `CAM-006` and `rtsp://127.0.0.1:8554/mosaic`.

ffprobe on this Mac saw six H.264 640x360 streams and a 960x540 mosaic. Changing the layout to `three_focus` through the API published again. The G30 and the Jetson were not used.

CAM-002 was blank in the mosaic because `testsrc2` frames had no timestamps. Pattern cameras now draw the local time. A large mosaic probe buffered about four seconds per tile and held those clocks apart; the probe is now one packet so the tiles stay within a frame.

The simulation start also opens the flight-controller UDP socket on 14551 from `config/config.simulation.json` and restarts the existing Rover SITL as system 1. `mavp2p` is paused while that session runs. `config/config.json` is unchanged. A local system 255 component 190 peer exchanged a rover heartbeat and a parameter read through the gateway. The Skydroid G30 was not used.

## 2026-11-03 Jetson mosaic NO SIGNAL

Changed on the Jetson only. The Mac tree still has an older draft of this work.

The mosaic accepts any registered cameras. A camera that is disabled or not listening on its RTSP port gets a black NO SIGNAL tile. The manager checks the ports every five seconds and rebuilds the publisher when that set changes or the process exits. `GET /api/v1/mosaic` reports `no_signal`.

On the Jetson each camera decodes on NVDEC into its own `intervideosink` channel, and the compositor reads `intervideosrc`. A camera that connects late or goes quiet shows black and no longer stops the whole mosaic. Before this, the compositor latency query failed while a camera was still connecting, and the mosaic waited forever.

The cameras pull over `udp+tcp`. Over interleaved TCP, GStreamer received no RTP from CAM-001 and CAM-002 on about half of the starts. UDP started every time. `videorate` in the camera branch failed to link and was removed.

Verified on the Jetson with CAM-001, CAM-002, and CAM-004 live and CAM-003 unplugged: `rtsp://192.168.144.20:8554/mosaic` published H.264 1280x720 at 15 fps within about three seconds of the start and ran with no restarts. The remaining test failures assume a Mac host or the Mac `config.json`.

## 2026-11-03 Jetson mosaic fill and faster restart

- Compositor pads now carry `sink_N::width/height`, so each tile fills its cell with no aspect bars.
- `POST /api/v1/mosaic/start` waits until MediaMTX reports the mosaic path ready (bounded by `limits.mosaic_ready_timeout_seconds`, default 5). Measured on the Jetson: about 1.9 s per start, with the stream ready when it returns.
- `limits.mosaic_source_timeout_seconds` default lowered from 1 s to 0.5 s; an unplugged camera no longer costs a full second per start.
- Test failures seen on the Jetson in `test_simulation.py` and `test_api.py` health come from the live production config and media state, not from these changes.

## 2026-11-03 Mosaic aspect, IDR interval, log redaction

- Mosaic tiles were drawn about 69% wide: the cameras send 704x576 with non-square pixels and the compositor kept that shape. Each camera branch now sets `pixel-aspect-ratio=1/1` with `capssetter` before `intervideosink`. Verified with a frame grab from `rtsp://127.0.0.1:8554/mosaic`.
- `nvv4l2h264enc` defaulted to one IDR every 256 frames (about 17 s at 15 fps). New viewers waited for it. `idrinterval` now equals `iframeinterval` (one second). Tablet first frame measured at about 1.4 s, down from about 4.6 s.
- `gst-launch` progress lines printed camera RTSP URLs with the login into `data/logs/mosaic.log`. The login now goes in `rtspsrc user-id/user-pw`, and the existing log was redacted in place.
- Camera SDP (LIBEASYRTSPD) announces H.265 with no `fmtp` line. Media3 cannot play it directly; the GCS now plays Direct mode with LibVLC and Jetson streams with Media3.

## 2026-11-03 ONVIF encoders, PTZ, stream memory, health

- New `app/cameras/drivers/onvif_control.py` (ONVIF Media2 and PTZ) and `app/services/camera_control.py`. Routes: `GET/PUT /cameras/{id}/encoders[/{token}]`, `GET /cameras/{id}/ptz`, `POST /cameras/{id}/ptz/move|stop|home`. Documented in `docs/API.md`.
- Read-only checks on CAM-001, CAM-002 and CAM-004 listed both encoders with their options and found pan, tilt, zoom and home. No encoder change or PTZ move was sent during testing. CAM-003 (unplugged) returns `supported: false`.
- The registry names are the other way round from the cameras: `path` `/live1.264` is the camera's SubStream (704x576), `sub_path` `/live0.264` is its MainStream (2.5K). `encoders` reports `gateway_stream` so clients pick the right one.
- `StreamManager` stores each start as `stream_choice` in the camera state and `restore()` starts it again after a gateway restart. `stop` clears it.
- `health.enabled` is now true in the Jetson `config/config.json`. Status shows `online`/`offline` from the TCP check.
- Per-camera transcode is CPU `ffmpeg`/`libx264`. Decoding the 2.5K MainStream used about 180% CPU and lagged; the GCS keeps Process on the default (small) source.

## 2026-11-04 mosaic restore after restart
- The mosaic stopped when the gateway was restarted for the ONVIF deploy; nothing restarted it.
- MosaicManager now writes data/mosaic_run.json on start/stop and restore() relaunches it in a background thread from the lifespan. Tests: tests/unit/test_mosaic_restore.py.
- GCS: VLC needed --rtsp-frame-buffer-size=2000000; 2.5K keyframes were truncated at 250 KB, causing slow starts.
