#pragma once

#include <stdint.h>

// Pin map for the ESP32 DevKit V1 (WROOM-32). Confirmed wiring:
//
//   Axis    STEP (PUL+)   DIR (DIR+)   ENABLE (ENA+, optional)
//   pan     GPIO18        GPIO19       GPIO25
//   tilt 1  GPIO22        GPIO23       GPIO32
//   tilt 2  GPIO26        GPIO27       GPIO33
//
// PUL-/DIR-/ENA- all connect to ESP32 GND (common ground with the driver
// power supply). GPIO 18/19 are the pair already proven on this bench.
// None of these pins are input-only (34-39), flash (6-11), or strapping
// (0/2/5/12/15), so they are safe on any DevKit V1.
//
// A value of -1 means that output must not be driven. STEP and DIR are
// required for an axis to move. ENABLE is optional: leave it -1 while the
// driver ENA input is unwired and wire it later without any other change.
// Enable polarity: -1 unspecified, 0 active low, 1 active high. Most
// TB6600/DM542-style drivers enable when ENA- is pulled low relative to
// ENA+, which reads as active low here (0).
//
// Water outputs, one SSR module input per nozzle, on/off only:
//
//   Output  GPIO
//   WPN-1   GPIO14
//   WPN-2   GPIO16
//   WPN-3   GPIO17
//
// The SSR modules are active high (3.3 V = on). GPIO14 can pulse briefly
// while the ESP32 ROM boots, before this firmware drives it low. GPIO16/17
// are free on WROOM-32 only; WROVER modules use them for PSRAM.
struct BoardConfig {
    static constexpr bool kPinsConfirmed = true;
    static constexpr int kEnablePolarity = -1;
    static constexpr int kPanStep = 18;
    static constexpr int kPanDir = 19;
    static constexpr int kPanEnable = -1;
    static constexpr int kTilt1Step = 22;
    static constexpr int kTilt1Dir = 23;
    static constexpr int kTilt1Enable = -1;
    static constexpr int kTilt2Step = 26;
    static constexpr int kTilt2Dir = 27;
    static constexpr int kTilt2Enable = -1;
    static constexpr int kWpnPins[3] = {14, 16, 17};
    static constexpr bool kWpnActiveHigh = true;
    // The Jetson asks for status every 2 s, so silence this long means the link is gone.
    static constexpr uint32_t kWpnWatchdogMs = 5000;
    static constexpr unsigned long kBaud = 115200;
};
