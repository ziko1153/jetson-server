# ESP32 firmware

The firmware is a PlatformIO project at `firmware/esp32`. It is the water-mount controller: three STEP/DIR drivers for pan, tilt 1, and tilt 2. It speaks `docs/RCWM_SERIAL_PROTOCOL.md` at 115200 baud by default.

## What it will not do until the board is commissioned

`firmware/esp32/include/board.hpp` ships with every pin at `-1`, enable polarity unspecified, and `kPinsConfirmed` false. In that state the firmware answers the serial protocol and rejects motion. It does not configure GPIO and it does not emit step pulses.

Before a bench test, an operator has to:

1. Confirm a physical emergency stop removes motor power without help from the ESP32 or the Jetson.
2. Write the measured STEP, DIR, and ENABLE pins and the driver enable polarity into `board.hpp`.
3. Set `kPinsConfirmed` to true only after that wiring has been checked.
4. Set `rcwm.allow_hardware_motion` to true on the Jetson. The default is false, including for a USB ESP32 attached to a Mac.
5. Set speed, acceleration, deceleration, and travel limits from the ground station. The firmware does not choose them from the motor size.

Software stop and the link timeout release the software enable output. They are not the emergency stop. Position values are step counts, not encoder readings. A restart marks the reference invalid.

## Host test

The motion math and the frame codec build without an ESP32 or PlatformIO:

```bash
bash scripts/test-firmware-host.sh
```

That compile does not flash a board and does not move a motor.

## Build and flash

Install PlatformIO on the machine that has the USB cable. This repository's setup scripts do not install it and do not upload firmware.

```bash
cd firmware/esp32
pio run -e esp32dev
pio run -e esp32dev -t upload --upload-port /dev/cu.usbserial-XXXX
pio device monitor -b 115200
```

Use the port the operating system actually assigns. On macOS that is usually `/dev/cu.usbserial-*` or `/dev/cu.usbmodem*`. On the Jetson it is often `/dev/ttyACM0` or `/dev/ttyUSB0`, but only after the device enumerates. Put that path in `rcwm.serial_port`. Do not leave a guessed path in `board.hpp` or in the default config.

The Jetson user must be able to open the port, for example as a member of `dialout`. `scripts/setup-jetson.sh` prints that hint and does not change group membership itself.

Upload is a manual step. Nothing in `scripts/start.sh` flashes the ESP32 or enables the drivers.
