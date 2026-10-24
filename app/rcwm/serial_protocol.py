"""Version 1 frame between the Jetson and the ESP32.

The frame is independent of GPIO pins and of the step algorithm. CRC-16/CCITT-FALSE
covers the version byte through the payload.
"""

from __future__ import annotations

from dataclasses import dataclass

MAGIC = b"\xA5\x5A"
VERSION = 1

HELLO = 1
HELLO_ACK = 2
STATUS_REQ = 3
STATUS = 4
CONFIG_SET = 5
CONFIG_GET = 6
CONFIG_REPLY = 7
SELECT = 8
MOTION = 9
STOP = 10
SET_HOME = 11
ACK = 12
PING = 13
PONG = 14


@dataclass(frozen=True)
class Frame:
    msg_type: int
    sequence: int
    payload: bytes


def crc16_ccitt_false(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def encode_frame(msg_type: int, sequence: int, payload: bytes = b"") -> bytes:
    if len(payload) > 512:
        raise ValueError("RCWM serial payload is too long")
    body = bytes([VERSION, msg_type & 0xFF]) + (sequence & 0xFFFF).to_bytes(2, "little")
    body += len(payload).to_bytes(2, "little") + payload
    return MAGIC + body + crc16_ccitt_false(body).to_bytes(2, "little")


def pop_frames(buffer: bytearray) -> list[Frame]:
    frames: list[Frame] = []
    while True:
        start = buffer.find(MAGIC)
        if start < 0:
            buffer.clear()
            return frames
        if start:
            del buffer[:start]
        if len(buffer) < 8:
            return frames
        version = buffer[2]
        msg_type = buffer[3]
        sequence = int.from_bytes(buffer[4:6], "little")
        length = int.from_bytes(buffer[6:8], "little")
        total = 8 + length + 2
        if length > 512:
            del buffer[:2]
            continue
        if len(buffer) < total:
            return frames
        body = bytes(buffer[2 : 8 + length])
        expected = int.from_bytes(buffer[8 + length : total], "little")
        del buffer[:total]
        if version != VERSION or crc16_ccitt_false(body) != expected:
            continue
        frames.append(Frame(msg_type, sequence, bytes(buffer_payload(body))))
    return frames


def buffer_payload(body: bytes) -> bytes:
    length = int.from_bytes(body[4:6], "little")
    return body[6 : 6 + length]
