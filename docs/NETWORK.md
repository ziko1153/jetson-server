# Network

The application does not configure interfaces, routes, or VPN addresses.

## Intended vehicle addresses

These are deployment targets, not something the installer applies:

```text
GR03 network:  192.168.144.20/24
Mesh network:  10.10.0.20/24
VPN:           10.8.0.20 on the VPN interface, not on Ethernet
```

Assign them with the Jetson's own network configuration. Putting several addresses on one Ethernet interface does not create failover between the GR03 radio, the mesh, and the VPN.

## What the gateway binds

- HTTP API: `server.host` and `server.port` in `config/config.json`, default `0.0.0.0:8080`
- RTSP: all interfaces, TCP only, port `8554`
- MediaMTX control API: `127.0.0.1:9997` only

The ground station must already have an IP path to the Jetson before either URL works. The same is true for direct camera fallback: the station must be able to route to the camera.

The macOS simulation uses the same bind settings, taken from `config/simulation.json`. `bind_host` defaults to `0.0.0.0`, so localhost and the GR03 Ethernet address can both open the API and RTSP ports. `bind_interface` reads one interface's IPv4 address and listens there. The simulation does not configure the interface.

## Camera reachability

`health.enabled` is `false`. Turn it on only after the Jetson can reach the cameras. Probes are TCP connections to the camera RTSP port. They report `online` or `offline`. They do not measure video.

`streaming.advertise_host` should be the address the ground station uses, for example `192.168.144.20`, so returned RTSP URLs do not follow whichever interface received the HTTP request.

## HTTP

The API is plain HTTP. That matches an isolated vehicle network and is not appropriate on a shared or public network. Before exposing it past the rover radios, put a TLS reverse proxy in front of port 8080 and set `auth.mode` to `bearer`. The application process can keep serving HTTP on localhost to that proxy.
