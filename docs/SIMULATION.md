# macOS camera simulation

`scripts/start-simulation.sh` runs the normal gateway, MediaMTX, and six local video sources until `scripts/stop-simulation.sh`. The Kotlin ground station and VLC use the same API and RTSP paths as a vehicle. `config/cameras.json` and `config/mosaic.json` are not read or written. Production startup remains `scripts/start.sh`.

The simulation does not change network interfaces, routes, or addresses.

## Start and stop

```bash
bash scripts/start-simulation.sh
bash scripts/stop-simulation.sh
```

`--detach` keeps it running after the shell returns. The foreground process stops when that terminal receives Ctrl-C.

Default ports, from `config/simulation.json`:

- API `0.0.0.0:8080`
- gateway RTSP `0.0.0.0:8554`
- MediaMTX control `127.0.0.1:9997`
- local pattern publishers `127.0.0.1:8555`, which are not the ground-station URLs

`bind_host` `0.0.0.0` accepts both this Mac and the Skydroid G30. To listen on one interface only, set `bind_interface` to that interface name, or pass `--bind-interface en7`. The process reads the interface address. It does not configure the interface. With a single-interface bind, use that address instead of `127.0.0.1`.

`advertise_host` is optional. When it is empty, stream URLs returned by the API use the host from the HTTP request.

## RTSP

```text
rtsp://127.0.0.1:8554/camera/CAM-001
rtsp://127.0.0.1:8554/camera/CAM-002
rtsp://127.0.0.1:8554/camera/CAM-003
rtsp://127.0.0.1:8554/camera/CAM-004
rtsp://127.0.0.1:8554/camera/CAM-005
rtsp://127.0.0.1:8554/camera/CAM-006
rtsp://127.0.0.1:8554/mosaic
```

From the G30, replace `127.0.0.1` with this Mac's Ethernet address on GR03 LAN0. The startup message lists the IPv4 addresses it can see.

One camera:

```bash
ffplay -rtsp_transport tcp rtsp://127.0.0.1:8554/camera/CAM-001
vlc --rtsp-tcp rtsp://127.0.0.1:8554/camera/CAM-001
```

The same commands work for `CAM-002` through `CAM-006`. If `vlc` is not on `PATH`:

```bash
/Applications/VLC.app/Contents/MacOS/VLC --rtsp-tcp rtsp://127.0.0.1:8554/camera/CAM-001
```

Six-camera mosaic:

```bash
ffprobe -v error -rtsp_transport tcp -select_streams v:0 -show_entries stream=codec_name,profile,width,height,pix_fmt -of default=nw=1 rtsp://127.0.0.1:8554/mosaic
ffplay -rtsp_transport tcp rtsp://127.0.0.1:8554/mosaic
vlc --rtsp-tcp rtsp://127.0.0.1:8554/mosaic
```

The shipped mosaic is H.264, 960x540, 10 fps, layout `grid_3x2`. Each pattern camera shows its id and this computer's local time, including tenths of a second. Compare that time with the clock on the Mac, or compare one tile with another. A smaller time is an older picture, which is the lag.

## MAVLink, RCWM, and Rover SITL

The same process serves the G30 on UDP `14550`. Send heartbeats as system 255 or 254, component 190. Address the vehicle as system 1, component 1.

`config/config.simulation.json` is loaded only by this process, through `UGV_CONFIG_FILE`. It turns the existing flight-controller link to UDP `127.0.0.1:14551`. `config/config.json` stays on `transport: none`, so `scripts/start.sh` does not open that socket. The RCWM block in the simulation file stays `transport: simulation`.

Rover SITL is the existing `rover-skid` profile in the sibling `sitl` directory (`sitl.directory` in `config/simulation.json`). The simulation starts it as system 1 and adds a serial output to `127.0.0.1:14551`. It does not edit the SITL scripts. If that rover is already running with those arguments, it is reused. If it is the direct system 2 instance, it is restarted for the session. A second rover is not started.

`mavp2p` forwarding to UDP `14550` is stopped for the session, because that port belongs to the gateway. `bash scripts/stop-simulation.sh` stops the gateway and puts the previous rover profile and the SITL router back, which is the direct G30-to-SITL path.

```bash
bash scripts/start-simulation.sh
bash scripts/stop-simulation.sh
```

`--detach` returns after the cameras, the mount simulator, and the rover link are ready.

## Change the layout while it is running

```bash
curl -sS http://127.0.0.1:8080/api/v1/mosaic
curl -sS -X PUT http://127.0.0.1:8080/api/v1/mosaic \
  -H 'content-type: application/json' \
  -d '{"expected_revision":1,"layout":"three_focus","output":{"width":960,"height":540,"fps":10,"bitrate_kbps":1500,"codec":"h264"},"camera_ids":["CAM-001","CAM-002","CAM-003"]}'
curl -sS -X POST http://127.0.0.1:8080/api/v1/mosaic/start
ffplay -rtsp_transport tcp rtsp://127.0.0.1:8554/mosaic
```

Use the `revision` from the GET response as `expected_revision`. `POST /api/v1/mosaic/start` replaces the publisher. VLC and ffplay have to open the URL again. These calls update `config/mosaic.simulation.json` only.

## Patterns, files, and real RTSP

`config/simulation.json` sets each camera's `input`:

- `pattern` publishes an FFmpeg test source. `pattern` is one of `testsrc`, `testsrc2`, `smptebars`, `smptehdbars`, `rgbtestsrc`, `yuvtestsrc`, or `mandelbrot`. `hue_speed` rotates the color.
- `file` loops a local MP4. Example: `{"id":"CAM-001","input":"file","file":"media/front.mp4"}`. The path may be absolute. A generated input must keep `rtsp://127.0.0.1:8555/CAM-001` in `config/cameras.simulation.json`.
- `rtsp` does not start a local publisher. Put the camera host, port, and path in `config/cameras.simulation.json`. Put a username and password in `config/secrets.json` under that camera's `credentials_ref`. Do not put the password in the camera file.

The gateway still remuxes individual cameras and composes the mosaic with the existing services. A real RTSP input has to be reachable before the mosaic can start.
