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
