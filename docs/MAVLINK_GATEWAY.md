# MAVLink gateway

The gateway is a UDP service inside the same Python process as the camera API. It is not an HTTP route, and the camera bearer token does not apply to it.

## Identities

| Role | System | Component |
| --- | --- | --- |
| Matek H743 | 1 | 1 |
| Jetson companion | 1 | 191 |
| RCWM replies | 1 | 171 |
| G30 #1 | 255 | 190 |
| G30 #2 | 254 | 190 |

Companion and mount heartbeats use MAVLink type onboard controller and autopilot invalid. The ground station treats a component 171 heartbeat as presence only. The RCWM connection is a fresh version-1 status body inside TUNNEL payload type 31000.

## Paths

`mavlink.bind_host` and `mavlink.bind_port` default to `0.0.0.0:14550`. One socket receives GR03, mesh, and VPN because those are addresses on the Jetson. This process does not rank those paths and does not fail over between them. The ground station keeps its existing route priority.

The direct G30 serial connection to the Matek is outside this process. Wiring that cable does not require a Jetson change, and this gateway does not try to take it over.

## What is forwarded

Packets are accepted from system 255 or 254, component 190. Any other source is counted and dropped. That allowlist is not authentication. MAVLink signing is not used, because the ground station does not sign frames. A host on the same network can still spoof those ids.

From an allowed ground station:

- heartbeats register the UDP source so telemetry has somewhere to go
- TIMESYNC requests get a nanosecond reply
- TUNNEL payload type 31000 aimed at component 171 goes to the RCWM service and is not sent to the Matek
- other messages aimed at component 171 or 191 stay on the Jetson
- messages aimed at system 1 component 1, or broadcast, are forwarded with their original bytes

Matek telemetry is sent to every ground station that has spoken within `peer_timeout_seconds`. It is not written back to the Matek.

The same system, component, message, and sequence seen again within one second is dropped. That suppresses a frame that arrives twice. It is not a path selector. Sequence numbers on frames this process creates increment per identity.

## Flight controller

`mavlink.flight_controller.transport` is `none`, `serial`, or `udp`.

- `none` is the default. Nothing is opened.
- `serial` uses `serial_port` and `baud`. An empty port stays disconnected.
- `udp` binds `udp_bind_host`:`udp_bind_port` for SITL. Set `udp_remote_host` when SITL is listening at a fixed address. When that host is empty, replies go to the address SITL sends from.

The serial device is never assumed to be `/dev/ttyUSB0`. A failed open is reported on `GET /api/v1/system/status` and retried. The camera server keeps running.

The macOS simulation loads `config/config.simulation.json` instead of this file. That copy sets `flight_controller.transport` to `udp` and binds `127.0.0.1:14551`. `scripts/start.sh` does not set `UGV_CONFIG_FILE`, so a production start leaves the transport at `none`.

## Configuration

See `mavlink` in `config/config.json`. Tests and the camera end-to-end run force `mavlink.enabled` false so they do not bind port 14550.
