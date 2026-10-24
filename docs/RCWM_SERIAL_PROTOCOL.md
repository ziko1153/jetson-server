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
| 4 | STATUS | 48-byte RCWM status body |
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

Axis 1 is pan, 2 is tilt 1, and 3 is tilt 2. Result and fault numbers are the same as the MAVLink RCWM body.

HELLO_ACK is sent at boot and in reply to HELLO. A new boot id means the step reference was lost. The Jetson may send the saved configuration again. It must not send the previous motion rates.

The ESP32 stops commanded motion when MOTION frames stop arriving for the configured control timeout. It does not start moving because a cable was plugged in.
