#pragma once

#include <stddef.h>
#include <stdint.h>

#include <vector>

// Jetson serial protocol version 1. CRC-16/CCITT-FALSE over version..payload.

static constexpr uint8_t kFrameMagic0 = 0xA5;
static constexpr uint8_t kFrameMagic1 = 0x5A;
static constexpr uint8_t kProtocolVersion = 1;

enum FrameType : uint8_t {
    kHello = 1,
    kHelloAck = 2,
    kStatusReq = 3,
    kStatus = 4,
    kConfigSet = 5,
    kConfigGet = 6,
    kConfigReply = 7,
    kSelect = 8,
    kMotion = 9,
    kStop = 10,
    kSetHome = 11,
    kAck = 12,
    kPing = 13,
    kPong = 14,
};

struct SerialFrame {
    uint8_t type = 0;
    uint16_t sequence = 0;
    std::vector<uint8_t> payload;
};

inline uint16_t crc16CcittFalse(const uint8_t* data, size_t length) {
    uint16_t crc = 0xFFFF;
    for (size_t index = 0; index < length; ++index) {
        crc ^= static_cast<uint16_t>(data[index]) << 8;
        for (int bit = 0; bit < 8; ++bit) {
            if (crc & 0x8000) {
                crc = static_cast<uint16_t>((crc << 1) ^ 0x1021);
            } else {
                crc = static_cast<uint16_t>(crc << 1);
            }
        }
    }
    return crc;
}

inline std::vector<uint8_t> encodeFrame(uint8_t type, uint16_t sequence, const std::vector<uint8_t>& payload) {
    std::vector<uint8_t> body;
    body.push_back(kProtocolVersion);
    body.push_back(type);
    body.push_back(static_cast<uint8_t>(sequence & 0xFF));
    body.push_back(static_cast<uint8_t>((sequence >> 8) & 0xFF));
    body.push_back(static_cast<uint8_t>(payload.size() & 0xFF));
    body.push_back(static_cast<uint8_t>((payload.size() >> 8) & 0xFF));
    body.insert(body.end(), payload.begin(), payload.end());
    const uint16_t crc = crc16CcittFalse(body.data(), body.size());
    std::vector<uint8_t> frame = {kFrameMagic0, kFrameMagic1};
    frame.insert(frame.end(), body.begin(), body.end());
    frame.push_back(static_cast<uint8_t>(crc & 0xFF));
    frame.push_back(static_cast<uint8_t>((crc >> 8) & 0xFF));
    return frame;
}

class FrameParser {
public:
    void push(uint8_t byte) { buffer_.push_back(byte); }

    bool next(SerialFrame& out) {
        while (buffer_.size() >= 2) {
            if (buffer_[0] != kFrameMagic0 || buffer_[1] != kFrameMagic1) {
                buffer_.erase(buffer_.begin());
                continue;
            }
            if (buffer_.size() < 8) return false;
            const uint8_t version = buffer_[2];
            const uint16_t length = static_cast<uint16_t>(buffer_[6] | (buffer_[7] << 8));
            if (length > 512) {
                buffer_.erase(buffer_.begin(), buffer_.begin() + 2);
                continue;
            }
            const size_t total = 8u + length + 2u;
            if (buffer_.size() < total) return false;
            const uint16_t expected = static_cast<uint16_t>(buffer_[8 + length] | (buffer_[9 + length] << 8));
            const uint16_t actual = crc16CcittFalse(&buffer_[2], 6u + length);
            if (version != kProtocolVersion || actual != expected) {
                buffer_.erase(buffer_.begin(), buffer_.begin() + 2);
                continue;
            }
            out.type = buffer_[3];
            out.sequence = static_cast<uint16_t>(buffer_[4] | (buffer_[5] << 8));
            out.payload.assign(buffer_.begin() + 8, buffer_.begin() + 8 + length);
            buffer_.erase(buffer_.begin(), buffer_.begin() + static_cast<std::ptrdiff_t>(total));
            return true;
        }
        return false;
    }

private:
    std::vector<uint8_t> buffer_;
};
