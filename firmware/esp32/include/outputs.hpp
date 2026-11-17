#pragma once

#include <stdint.h>

#if defined(ARDUINO)
#include <Arduino.h>
#endif

// On/off solid-state relay outputs (WPN-1..WPN-3). Bit n of the mask is
// output n. This class never touches the stepper pins or the motion planner.
//
// Every output is off at boot and is never restored from storage. When no
// valid frame has arrived from the Jetson for the watchdog period, every
// output is switched off. STOP does not switch outputs off, because the
// ground station sends STOP on every stick release and tilt change.
class OutputBank {
public:
    static constexpr int kCount = 3;
    static constexpr uint8_t kValidMask = (1u << kCount) - 1u;

    OutputBank(const int (&pins)[kCount], bool activeHigh, uint32_t watchdogMs)
        : activeHigh_(activeHigh), watchdogMs_(watchdogMs) {
        for (int index = 0; index < kCount; ++index) pins_[index] = pins[index];
    }

    // Drive every wired pin to its off level. Call first in setup().
    void begin() {
        mask_ = 0;
#if defined(ARDUINO)
        for (int index = 0; index < kCount; ++index) {
            if (pins_[index] < 0) continue;
            digitalWrite(pins_[index], offLevel());
            pinMode(pins_[index], OUTPUT);
            digitalWrite(pins_[index], offLevel());
        }
#endif
    }

    // Set the full output mask. Unknown bits or an unwired output are refused.
    bool apply(uint8_t mask) {
        if (mask & ~kValidMask) return false;
        for (int index = 0; index < kCount; ++index) {
            if ((mask & (1u << index)) && pins_[index] < 0) return false;
        }
        mask_ = mask;
        write();
        return true;
    }

    // Any valid frame from the Jetson keeps the outputs alive.
    void heard(uint32_t nowMs) {
        lastHeardMs_ = nowMs;
        heardOnce_ = true;
    }

    // Switch everything off once the Jetson has gone silent.
    void service(uint32_t nowMs) {
        if (mask_ == 0) return;
        if (!heardOnce_ || nowMs - lastHeardMs_ > watchdogMs_) {
            mask_ = 0;
            write();
        }
    }

    uint8_t mask() const { return mask_; }

private:
    void write() const {
#if defined(ARDUINO)
        for (int index = 0; index < kCount; ++index) {
            if (pins_[index] < 0) continue;
            const bool on = mask_ & (1u << index);
            digitalWrite(pins_[index], on ? onLevel() : offLevel());
        }
#endif
    }

    uint8_t onLevel() const { return activeHigh_ ? 1 : 0; }
    uint8_t offLevel() const { return activeHigh_ ? 0 : 1; }

    int pins_[kCount] = {-1, -1, -1};
    bool activeHigh_;
    uint32_t watchdogMs_;
    uint8_t mask_ = 0;
    uint32_t lastHeardMs_ = 0;
    bool heardOnce_ = false;
};
