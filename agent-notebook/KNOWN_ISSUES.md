# Known issues

- The NVIDIA mosaic command has not been run on an Orin NX. Capabilities will show software fallback if the plugins are missing. Jetson temperature and GPU sysfs files have not been read on hardware either.
- ONVIF has not been tried against the vehicle cameras. A camera that rejects the password digest, or uses a nonstandard media service, will fail the probe with an explicit error.
- `measured_fps` and `last_frame_at` are always null. MediaMTX does not provide frame rate, and the gateway does not decode passthrough streams to estimate it.
- The automated tests do not unplug a camera. Recovery is MediaMTX reconnecting a pull and the mosaic supervisor restarting FFmpeg. That restart path was not part of the passing end-to-end test.
- The API is HTTP. TLS is expected to be a reverse proxy, not part of this process.
- Default camera RTSP paths are `/` and are probably wrong for the real devices.
- `app/cameras/drivers/vendor.py` has no manufacturer handlers.
- The macOS simulation was probed on this Mac with ffprobe. It was not opened from the Skydroid G30, and it was not started on a Jetson. A `file` or real `rtsp` input was not part of that run.
- MAVLink sources are filtered by system id 255 or 254 and component 190. That is an allowlist. It does not authenticate the sender.
- Software stop on the water mount does not remove motor power. A hardware emergency stop is still required.
- Mount angles are commanded-step estimates. They are cleared when the ESP32 boot id changes.
- The firmware has not been flashed. `board.hpp` still has every pin at `-1`.
- An older Kotlin pan-tilt rate stream aimed at component 171 is ignored unless it is RCWM payload type 31000.
