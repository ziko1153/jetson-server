#include <Arduino.h>

#include <cstring>

#include "board.hpp"
#include "motion.hpp"
#include "protocol.hpp"

namespace {
bool pinsAssigned() {
    const int pins[] = {
        BoardConfig::kPanStep, BoardConfig::kPanDir, BoardConfig::kPanEnable,
        BoardConfig::kTilt1Step, BoardConfig::kTilt1Dir, BoardConfig::kTilt1Enable,
        BoardConfig::kTilt2Step, BoardConfig::kTilt2Dir, BoardConfig::kTilt2Enable,
    };
    for (int pin : pins) {
        if (pin < 0) return false;
    }
    return BoardConfig::kPinsConfirmed && BoardConfig::kEnablePolarity >= 0;
}

MotionPlanner planner(pinsAssigned());
FrameParser parser;
uint32_t bootId = 0;
bool energized = false;

std::vector<uint8_t> ack(uint16_t sequence, uint8_t request, uint8_t result) {
    return encodeFrame(kAck, sequence, {request, result, 0});
}

void writeFrame(const std::vector<uint8_t>& frame) {
    Serial.write(frame.data(), frame.size());
}

void handle(const SerialFrame& frame) {
    if (frame.type == kHello) {
        std::vector<uint8_t> payload = {
            static_cast<uint8_t>(bootId & 0xFF),
            static_cast<uint8_t>((bootId >> 8) & 0xFF),
            static_cast<uint8_t>((bootId >> 16) & 0xFF),
            static_cast<uint8_t>((bootId >> 24) & 0xFF),
            static_cast<uint8_t>(energized ? 1 : 0),
            kProtocolVersion,
        };
        writeFrame(encodeFrame(kHelloAck, frame.sequence, payload));
        return;
    }
    if (frame.type == kPing) {
        writeFrame(encodeFrame(kPong, frame.sequence, {}));
        return;
    }
    if (frame.type == kSelect && !frame.payload.empty()) {
        writeFrame(ack(frame.sequence, kSelect, static_cast<uint8_t>(planner.select(frame.payload[0]))));
        return;
    }
    if (frame.type == kMotion && frame.payload.size() >= 12) {
        float rates[3] = {};
        memcpy(rates, frame.payload.data(), sizeof(rates));
        const int result = planner.motion(rates[0], rates[1], rates[2], millis() / 1000.0f);
        energized = result == kApplied && (rates[0] != 0 || rates[1] != 0 || rates[2] != 0);
        writeFrame(ack(frame.sequence, kMotion, static_cast<uint8_t>(result)));
        return;
    }
    if (frame.type == kStop) {
        planner.stop(false);
        energized = false;
        writeFrame(ack(frame.sequence, kStop, kApplied));
        return;
    }
    if (frame.type == kSetHome && !frame.payload.empty()) {
        writeFrame(ack(frame.sequence, kSetHome, static_cast<uint8_t>(planner.setHome(frame.payload[0]))));
        return;
    }
    writeFrame(ack(frame.sequence, frame.type, 5));
}
}  // namespace

void setup() {
    Serial.begin(BoardConfig::kBaud);
    bootId = micros();
    planner.restart();
    energized = false;
    // Drivers stay released. Pulse generation is compiled out until pins are confirmed.
}

void loop() {
    static uint32_t lastMs = millis();
    const uint32_t now = millis();
    planner.advance((now - lastMs) / 1000.0f, now / 1000.0f);
    lastMs = now;
    while (Serial.available() > 0) {
        parser.push(static_cast<uint8_t>(Serial.read()));
        SerialFrame frame;
        while (parser.next(frame)) handle(frame);
    }
    if (planner.timedOut()) energized = false;
}
