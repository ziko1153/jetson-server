# Jetson deployment

This was not run on a Jetson. The script and the backend selection are ready to run there. A successful macOS test does not mean the NVIDIA pipeline has been verified.

## What the script does

`scripts/setup-jetson.sh` refuses to continue unless Linux aarch64 has `/etc/nv_tegra_release` or a device-tree model containing Jetson. It does not install CUDA, JetPack, TensorRT, or drivers.

It expects FFmpeg and GStreamer to come from the existing JetPack packages. If they are missing it prints an `apt-get` command and stops. It then creates `.venv`, downloads the Linux arm64 MediaMTX build, and writes `deployments/systemd/ugv-jetson-gateway.generated.service` with the checkout path filled in. As root it installs and enables that unit. Otherwise it prints the `sudo` commands.

```bash
bash scripts/setup-jetson.sh
bash scripts/start.sh
```

Or, after the unit is installed:

```bash
sudo systemctl start ugv-jetson-gateway
```

## MAVLink and the water mount

The same checkout is used. `scripts/setup-jetson.sh` installs `pymavlink` and `pyserial` into the virtualenv through the existing package install. It does not open a UART, change an address, or upload ESP32 firmware.

Before the first vehicle run:

- set `mavlink.flight_controller.serial_port` to the Matek UART the Jetson actually has
- set `rcwm.transport` to `serial` and `rcwm.serial_port` to the ESP32 the kernel enumerated
- leave `rcwm.allow_hardware_motion` false until `docs/ESP32_FIRMWARE.md` has been followed
- build the firmware on a machine with PlatformIO and flash it by hand

`GET /api/v1/system/status` reports the UDP bind, the flight-controller link, the ESP32 link, and, on the Jetson, temperature and GPU load when those sysfs files exist. A missing file stays null.

## What still has to be checked on the vehicle

- `GET /api/v1/system/capabilities` shows the real L4T release, JetPack family, and whether `nvv4l2decoder`, `nvvidconv`, and `nvv4l2h264enc` exist
- Orin NX is expected to have a hardware encoder. Orin Nano is not. The pipeline still follows the plugin check
- The real camera RTSP paths and credentials
- Playback of one camera, two cameras, a three-camera mosaic, and a six-camera mosaic over the GR03 network
- `streaming.advertise_host` set to the address the ground station uses

No Python files should be edited during that move.
