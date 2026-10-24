#pragma once

// Pins stay unassigned until the wiring is confirmed on the vehicle.
// A value of -1 means that output must not be driven.
// Enable polarity: -1 unspecified, 0 active low, 1 active high.

struct BoardConfig {
    static constexpr bool kPinsConfirmed = false;
    static constexpr int kEnablePolarity = -1;
    static constexpr int kPanStep = -1;
    static constexpr int kPanDir = -1;
    static constexpr int kPanEnable = -1;
    static constexpr int kTilt1Step = -1;
    static constexpr int kTilt1Dir = -1;
    static constexpr int kTilt1Enable = -1;
    static constexpr int kTilt2Step = -1;
    static constexpr int kTilt2Dir = -1;
    static constexpr int kTilt2Enable = -1;
    static constexpr unsigned long kBaud = 115200;
};
