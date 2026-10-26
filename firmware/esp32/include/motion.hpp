#pragma once

#include <math.h>

#include <algorithm>
#include <cstring>

#include <Preferences.h>

// Step estimate and ramp. GPIO is a separate gate: this class does not know pin numbers.

enum MotionResult : int { kApplied = 2, kRejected = 3, kSafety = 7 };

// Wire protocol config body, 27 bytes. Matches the Jetson and GCS layout.
static constexpr size_t kConfigBody = 27;
static constexpr uint16_t kGearScale = 1000;
static constexpr uint16_t kCenti = 100;
static constexpr uint16_t kU16None = 0xFFFF;
static constexpr int16_t kAngleUnset = -32768;

static constexpr uint8_t kCfgEnabled = 1;
static constexpr uint8_t kCfgReversed = 2;
static constexpr uint8_t kCfgPreserved = 4;

struct AxisPlan {
    bool enabled = false;
    bool reversed = false;
    float maxSpeed = 0;
    float maxAccel = 0;
    float maxDecel = 0;
    float minAngle = 0;
    float maxAngle = 0;
    float deadbandPercent = 0;
    float commanded = 0;
    float current = 0;
    bool referenced = false;
    bool referenceInvalid = true;
    long steps = 0;
    int stepsPerRevolution = 1600;
    float gearRatio = 1;
    float homeDegrees = 0;
    float linkTimeoutS = 0.5f;
};

class MotionPlanner {
public:
    explicit MotionPlanner(bool executionEnabled) : executionEnabled_(executionEnabled) {}

    int select(int axis) {
        if (axis != 2 && axis != 3) return kRejected;
        if (activeTilt_ != 0 && activeTilt_ != axis) {
            axes_[activeTilt_].commanded = 0;
            axes_[activeTilt_].current = 0;
        }
        activeTilt_ = axis;
        return kApplied;
    }

    int motion(float pan, float tilt1, float tilt2, float nowS) {
        if (!executionEnabled_) return kSafety;
        if (tilt1 != 0.f && tilt2 != 0.f) return kSafety;
        if (tilt1 != 0.f && activeTilt_ != 2) return kSafety;
        if (tilt2 != 0.f && activeTilt_ != 3) return kSafety;
        const float rates[4] = {0, pan, tilt1, tilt2};
        for (int axis = 1; axis <= 3; ++axis) {
            if (rates[axis] == 0.f) continue;
            if (!axes_[axis].enabled || axes_[axis].maxSpeed <= 0 || axes_[axis].maxAccel <= 0 || axes_[axis].maxDecel <= 0) {
                return kSafety;
            }
            if (fabsf(rates[axis]) > axes_[axis].maxSpeed) return kSafety;
        }
        for (int axis = 1; axis <= 3; ++axis) axes_[axis].commanded = rates[axis];
        lastMotionS_ = nowS;
        moving_ = pan != 0.f || tilt1 != 0.f || tilt2 != 0.f;
        return kApplied;
    }

    void stop(bool immediate) {
        for (int axis = 1; axis <= 3; ++axis) {
            axes_[axis].commanded = 0;
            if (immediate) axes_[axis].current = 0;
        }
        moving_ = false;
    }

    int setHome(int axis) {
        if (axis < 1 || axis > 3) return kRejected;
        AxisPlan& item = axes_[axis];
        if (fabsf(item.commanded) > 1e-4f || fabsf(item.current) > 1e-3f) return kSafety;
        item.steps = static_cast<long>(lround(item.homeDegrees / 360.0 * item.stepsPerRevolution * item.gearRatio));
        item.referenced = true;
        item.referenceInvalid = false;
        saveConfig(axis);
        return kApplied;
    }

    void advance(float dt, float nowS) {
        if (dt < 0) return;
        if (moving_ && nowS - lastMotionS_ > timeout()) {
            stop(true);
            timedOut_ = true;
            return;
        }
        for (int axis = 1; axis <= 3; ++axis) {
            AxisPlan& item = axes_[axis];
            const float previous = item.current;
            item.current = ramp(item, dt);
            if (!item.referenced) continue;
            const float average = (previous + item.current) * 0.5f;
            const double delta = static_cast<double>(average) * dt / 360.0 * item.stepsPerRevolution * item.gearRatio;
            item.steps += static_cast<long>(lround(delta));
        }
    }

    void restart() {
        activeTilt_ = 0;
        moving_ = false;
        timedOut_ = false;
        for (int axis = 1; axis <= 3; ++axis) {
            AxisPlan& item = axes_[axis];
            item.commanded = 0;
            item.current = 0;
            item.referenced = false;
            item.referenceInvalid = true;
            item.steps = 0;
        }
    }

    AxisPlan& axis(int index) { return axes_[index]; }
    int activeTilt() const { return activeTilt_; }
    bool timedOut() const { return timedOut_; }
    bool executionEnabled() const { return executionEnabled_; }
    int pulsesFor(int) const { return 0; }

    // Encode the current axis config into the 27-byte wire body.
    std::vector<uint8_t> configBody(int axis) const {
        std::vector<uint8_t> body(kConfigBody, 0);
        const AxisPlan& item = axes_[axis];
        uint8_t flags = 0;
        if (item.enabled) flags |= kCfgEnabled;
        if (item.reversed) flags |= kCfgReversed;
        if (item.referenced) flags |= kCfgPreserved;
        body[0] = flags;
        // body[1] reserved (was polarity)
        putU16(body, 2, item.stepsPerRevolution);
        putU32(body, 4, static_cast<uint32_t>(lround(item.gearRatio * kGearScale)));
        putU16(body, 8, speed16(item.maxSpeed));
        putU16(body, 10, speed16(item.maxAccel));
        putU16(body, 12, speed16(item.maxDecel));
        putI16(body, 14, angle16(item.minAngle));
        putI16(body, 16, angle16(item.maxAngle));
        putI16(body, 18, angle16(item.homeDegrees));
        body[20] = static_cast<uint8_t>(item.deadbandPercent);
        // bytes 21..26 reserved
        return body;
    }

    // Apply a 27-byte wire body to the axis. Returns false if the body is malformed.
    bool applyConfigBody(int axis, const std::vector<uint8_t>& body) {
        if (body.size() < kConfigBody) return false;
        if (axis < 1 || axis > 3) return false;
        AxisPlan& item = axes_[axis];
        const uint8_t flags = body[0];
        const bool wasReferenced = item.referenced;
        item.enabled = flags & kCfgEnabled;
        item.reversed = flags & kCfgReversed;
        const bool preserved = flags & kCfgPreserved;
        item.stepsPerRevolution = u16(body, 2);
        item.gearRatio = static_cast<float>(u32(body, 4)) / kGearScale;
        item.maxSpeed = fromSpeed(u16(body, 8));
        item.maxAccel = fromSpeed(u16(body, 10));
        item.maxDecel = fromSpeed(u16(body, 12));
        item.minAngle = fromAngle(i16(body, 14));
        item.maxAngle = fromAngle(i16(body, 16));
        item.homeDegrees = fromAngle(i16(body, 18));
        item.deadbandPercent = body[20];
        if (!item.enabled) {
            item.commanded = 0;
            item.current = 0;
        }
        if (!preserved) {
            item.referenced = false;
            item.referenceInvalid = true;
            item.steps = 0;
        }
        return true;
    }

    // Load config for one axis from Preferences (NVS). Called on boot.
    void loadConfig(int axis) {
        if (axis < 1 || axis > 3) return;
        Preferences prefs;
        prefs.begin(kPrefsNs, true);
        std::vector<uint8_t> body(kConfigBody, 0);
        size_t read = prefs.getBytes(prefsKey(axis), body.data(), kConfigBody);
        prefs.end();
        if (read != kConfigBody) return;
        applyConfigBody(axis, body);
        axes_[axis].referenced = false;
        axes_[axis].referenceInvalid = true;
        axes_[axis].steps = 0;
    }

    // Save config for one axis to Preferences (NVS).
    bool saveConfig(int axis) {
        if (axis < 1 || axis > 3) return false;
        Preferences prefs;
        if (!prefs.begin(kPrefsNs, false)) return false;
        const std::vector<uint8_t> body = configBody(axis);
        const size_t written = prefs.putBytes(prefsKey(axis), body.data(), kConfigBody);
        prefs.end();
        return written == kConfigBody;
    }

private:
    static float ramp(const AxisPlan& item, float dt) {
        const float target = item.commanded;
        float current = item.current;
        if (target == current) return current;
        const bool speeding = fabsf(target) >= fabsf(current) && target * current >= 0.f;
        const float limit = speeding ? item.maxAccel : item.maxDecel;
        if (limit <= 0) return current;
        const float step = limit * dt;
        if (target > current) return std::min(target, current + step);
        return std::max(target, current - step);
    }

    float timeout() const {
        float value = 0.5f;
        bool seen = false;
        for (int axis = 1; axis <= 3; ++axis) {
            if (!axes_[axis].enabled) continue;
            if (!seen || axes_[axis].linkTimeoutS < value) {
                value = axes_[axis].linkTimeoutS;
                seen = true;
            }
        }
        return value;
    }

    static uint16_t u16(const std::vector<uint8_t>& b, size_t at) {
        return static_cast<uint16_t>(b[at] | (b[at + 1] << 8));
    }
    static int16_t i16(const std::vector<uint8_t>& b, size_t at) {
        uint16_t v = u16(b, at);
        return static_cast<int16_t>(v & 0x8000 ? v - 0x10000 : v);
    }
    static uint32_t u32(const std::vector<uint8_t>& b, size_t at) {
        return static_cast<uint32_t>(b[at]) | (static_cast<uint32_t>(b[at + 1]) << 8) |
               (static_cast<uint32_t>(b[at + 2]) << 16) | (static_cast<uint32_t>(b[at + 3]) << 24);
    }
    static void putU16(std::vector<uint8_t>& b, size_t at, uint16_t v) {
        b[at] = static_cast<uint8_t>(v & 0xFF);
        b[at + 1] = static_cast<uint8_t>((v >> 8) & 0xFF);
    }
    static void putI16(std::vector<uint8_t>& b, size_t at, int16_t v) {
        putU16(b, at, static_cast<uint16_t>(v));
    }
    static void putU32(std::vector<uint8_t>& b, size_t at, uint32_t v) {
        b[at] = static_cast<uint8_t>(v & 0xFF);
        b[at + 1] = static_cast<uint8_t>((v >> 8) & 0xFF);
        b[at + 2] = static_cast<uint8_t>((v >> 16) & 0xFF);
        b[at + 3] = static_cast<uint8_t>((v >> 24) & 0xFF);
    }
    static uint16_t speed16(float value) {
        if (!isfinite(value)) return kU16None;
        return static_cast<uint16_t>(std::max(0, std::min(static_cast<int>(kU16None) - 1, lround(value * kCenti))));
    }
    static float fromSpeed(uint16_t raw) {
        return raw == kU16None ? 0.f : static_cast<float>(raw) / kCenti;
    }
    static int16_t angle16(float value) {
        if (!isfinite(value)) return kAngleUnset;
        return static_cast<int16_t>(std::max(-32767, std::min(32767, lround(value * kCenti))));
    }
    static float fromAngle(int16_t raw) {
        return raw == kAngleUnset ? 0.f : static_cast<float>(raw) / kCenti;
    }
    static const char* prefsKey(int axis) {
        static char keys[4][8] = {"", "pan", "tilt1", "tilt2"};
        return keys[axis];
    }

    static constexpr const char* kPrefsNs = "rcwm";

    bool executionEnabled_;
    int activeTilt_ = 0;
    bool moving_ = false;
    bool timedOut_ = false;
    float lastMotionS_ = 0;
    AxisPlan axes_[4];
};
