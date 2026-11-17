# RCWM serial protocol

Version 1 is the contract between the Jetson and the ESP32. GPIO pins, enable polarity, and the step algorithm can change inside the firmware without a Jetson change, as long as these frames stay compatible.

The MAVLink body is not this protocol. The Jetson translates one into the other.

## Frame

| Offset | Field |
| --- | --- |
| 0 | `0xA5` |
| 1 | `0x5A` |
| 2 | version, must be 1 |
| 3 | type |
| 4 | sequence, uint16 little-endian |
| 6 | payload length, uint16 little-endian, at most 512 |
| 8 | payload |
| end | CRC-16/CCITT-FALSE, little-endian, over version through payload |

CRC-16/CCITT-FALSE uses polynomial `0x1021`, initial value `0xFFFF`, no reflection, and no final xor. The check value of `123456789` is `0x29B1`. A bad CRC is dropped.

## Types

| Type | Name | Payload |
| --- | --- | --- |
| 1 | HELLO | empty |
| 2 | HELLO_ACK | boot id uint32, energized uint8, protocol uint8 |
| 3 | STATUS_REQ | empty |
| 4 | STATUS | 48-byte RCWM status body, the output mask uint8, then the 8-byte patrol block |
| 5 | CONFIG_SET | axis uint8, then the 27-byte RCWM config |
| 6 | CONFIG_GET | axis uint8 |
| 7 | CONFIG_REPLY | axis uint8, result uint8, 27-byte config |
| 8 | SELECT | axis uint8, 2 or 3 |
| 9 | MOTION | three little-endian float32 degrees per second: pan, tilt 1, tilt 2 |
| 10 | STOP | empty |
| 11 | SET_HOME | axis uint8 |
| 12 | ACK | request type, result, fault |
| 13 | PING | empty |
| 14 | PONG | empty |
| 15 | OUTPUTS | output mask uint8. ACK carries the applied mask as a fourth byte |
| 16 | PATROL | action uint8: 0 stop, 1 start. Start adds min int16, max int16 (centi-degrees), speed uint16 (centi-degrees/s). ACK carries the patrol reason as a fourth byte |

Axis 1 is pan, 2 is tilt 1, and 3 is tilt 2. Result and fault numbers are the same as the MAVLink RCWM body.

HELLO_ACK is sent at boot and in reply to HELLO. A new boot id means the step position was restored from the controller's saved store, unless the mount was moved by hand while powered off. The Jetson may send the saved configuration again. It must not send the previous motion rates.

The ESP32 stops commanded motion when MOTION frames stop arriving for the configured control timeout. It does not start moving because a cable was plugged in.

## Outputs

Bit 0, 1, and 2 of the output mask are WPN-1, WPN-2, and WPN-3, the on/off SSR inputs on GPIO 14, 16, and 17. OUTPUTS sets the whole mask. A mask with any other bit set is rejected. Every output is off at boot and is never restored after a restart.

STOP does not change the outputs. When no valid frame has arrived for 5 seconds, the ESP32 switches every output off. The Jetson asks for status every 2 seconds, so that only happens when the link is gone.

Firmware without outputs sends a 48-byte STATUS and answers OUTPUTS with result 5 (unsupported).

## Patrol

`firmware/esp32/include/patrol.hpp` sweeps pan between min and max at the given speed. The ESP32 runs it, so it keeps going when the Jetson or the ground station goes quiet. It ends only on PATROL stop, an ESP32 restart, or a failed check.

Start is refused unless pan is enabled with speed, acceleration and deceleration set, pan is referenced, both pan soft limits are set, min and max lie inside them at least 1° apart, and the speed is above 0 and not above the pan maximum. The same checks run every loop, so a config change that breaks them stops patrol. Braking is planned at half the pan deceleration, so pan turns 0.1° to 0.3° inside the range. The planner's soft limits still apply underneath.

While patrol runs, MOTION with a non-zero pan rate is rejected (result 3). MOTION with pan 0 drives the tilts as usual. STOP halts the tilts and leaves patrol running. When tilt commands go quiet, the tilts ramp down instead of the planner's link timeout halting every axis at once.

Patrol block in STATUS (8 bytes): state uint8 (1 running), last stop reason uint8, min int16, max int16 (centi-degrees), speed uint16 (centi-degrees/s).

Reasons: 0 none, 1 operator stop, 2 bad range, 3 pan limits not set, 4 outside the pan limits, 5 bad speed, 6 pan not configured, 7 pan not referenced, 8 motion disabled by the firmware.
