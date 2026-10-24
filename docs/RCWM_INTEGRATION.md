# RCWM integration

RCWM is the remote-controlled water mount. It is not a camera gimbal. The ground station already defines protocol version 1. This service answers that protocol. It does not invent a second MAVLink body.

## Link

The ground station sends MAVLink TUNNEL message 385, payload type 31000, to system 1 component 171. The body starts with `R` `C`, version 1. Replies use the same payload type and the same request id, and they are sourced from system 1 component 171 so the existing decoder accepts them.

Opcodes, result bytes, flag bits, and the 27-byte motor record match `RcwmProtocol.kt`. Angles are output-shaft degrees. Steps are the pulses the controller was told to make.

## Ownership

G30 #1 is system 255. G30 #2 is system 254. One of them can own the mount. The other can read status. Motion, configuration, tilt selection, and set-home from the non-owner are rejected. Stop is accepted from either station.

If the owner sends nothing for `rcwm.owner_timeout_seconds` (default 1.5), the lease is dropped and motion is stopped. A repeated request id, or an id that steps backward by a small amount, is rejected as stale. A station that starts its ids over after a restart is accepted.

The service does not resend the last motion after the ESP32 boot id changes. It does resend the saved motor configuration, because that is settings rather than a movement command.

## Motors

Defaults are 1600 steps per revolution and gear ratio 1.0. Speed, acceleration, deceleration, soft limits, direction, and enable polarity stay unset until a ground station writes them. A motor cannot be enabled while speed, acceleration, or deceleration is missing. The service does not fill those in from the NEMA 34 frame size.

Changing steps per revolution or gear ratio clears the position reference. Set-home is accepted only while that axis is stopped. The current step count is then defined so the reported angle equals the configured home angle. After an ESP32 restart the reference is invalid and the angles are unknown.

Only pan and the selected tilt may be nonzero. Selecting the other tilt zeroes the previous tilt first. Both tilt rates in one command are rejected.

Motion commands must be repeated. If they stop for the control timeout (500 ms when the ground station leaves the timeout unset), the mount stops and releases the software enable. That timeout is not a travel limit.

## Transports

`rcwm.transport` is `simulation` or `serial`.

Simulation is the default and is what macOS and the tests use. It speaks the same serial frames in-process. It does not open a device.

Serial uses `rcwm.serial_port` and `rcwm.baud`. Motion frames are not written unless `rcwm.allow_hardware_motion` is true. The default is false. Stop is still sent. An empty port is reported as disconnected.

Settings are stored in `data/rcwm_state.json`. Positions are not stored. `reference_kept_across_restart` in the status payload is false.

## Safety

A physical emergency stop and a way to remove motor power are required. Software stop is not that device. `software_stop_is_hardware_estop` is false. Positions are estimates because there are no encoders. The service does not energize the simulator at startup, and the firmware does not pulse GPIO until its pin map is confirmed.

## Kotlin

No Kotlin change is required for protocol version 1. Replies are already what `MavlinkRcwmController` accepts.

These are mismatches to remember, not patches:

- An older pan-tilt rate stream can still target component 171. Frames that are not payload type 31000 are ignored. They are not turned into water-mount motion.
- A component 171 heartbeat does not mean the mount is connected. The status body does.
- The ground station does not sign MAVLink. This gateway does not pretend that a source address or a component id is an authenticator.
- Flight messages to the autopilot still follow the ground station's own route priority. The Jetson forwards them only when they actually arrive here.
