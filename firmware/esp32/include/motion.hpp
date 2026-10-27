#pragma once

#include <math.h>

#include <algorithm>
#include <cstring>

#if defined(ARDUINO)
#include <Preferences.h>
#endif

#include "protocol.hpp"

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

// Fault codes match the Jetson and GCS RCWM bodies.
static constexpr uint8_t kFaultNone = 0;
static constexpr uint8_t kFaultController = 1;
static constexpr uint8_t kFaultReference = 4;
static constexpr uint8_t kFaultTimeout = 7;

// Status body layout. Matches the 48-byte RCWM status body on the Jetson.
static constexpr uint16_t kFlagEsp32 = 1;
static constexpr uint16_t kFlagGateway = 2;
static constexpr uint16_t kFlagStopped = 4;
static constexpr uint16_t kFlagMoving = 8;
static constexpr uint16_t kFlagClear = 16;
static constexpr uint16_t kFlagFault = 32;
static constexpr uint16_t kFlagDegraded = 64;
static constexpr uint8_t kAxisEnabled = 1;
static constexpr uint8_t kAxisReferenced = 2;
static constexpr uint8_t kAxisInvalid = 8;
static constexpr uint8_t kAxisPos = 16;
static constexpr uint8_t kAxisNeg = 32;
static constexpr uint8_t kAxisFault = 64;
static constexpr int32_t kUnknownI32 = 0x7FFFFFFF;

struct AxisPlan {
    bool enabled = false;
    bool reversed = false;
    float maxSpeed = 0;
    float maxAccel = 0;
    float maxDecel = 0;
    float minAngle = 0;
    float maxAngle = 0;
    bool minAngleSet = false;
    bool maxAngleSet = false;
    float deadbandPercent = 0;
    float commanded = 0;
    float current = 0;
    bool referenced = false;
    bool referenceInvalid = true;
    long steps = 0;
    double stepFraction = 0;  // leftover below one step, so a fast loop does not drop motion
    bool externalSteps = false;  // true when step pulses come from a hardware timer.
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

    int motion(float pan, float tilt1, float tilt2, float nowS, uint8_t* faultOut = nullptr) {
        if (faultOut != nullptr) *faultOut = kFaultNone;
        if (!executionEnabled_) return refuse(faultOut, kSafety, kFaultController);
        if (tilt1 != 0.f && tilt2 != 0.f) return refuse(faultOut, kSafety, kFaultNone);
        if (tilt1 != 0.f && activeTilt_ != 2) return refuse(faultOut, kSafety, kFaultNone);
        if (tilt2 != 0.f && activeTilt_ != 3) return refuse(faultOut, kSafety, kFaultNone);
        const float rates[4] = {0, pan, tilt1, tilt2};
        for (int axis = 1; axis <= 3; ++axis) {
            if (rates[axis] == 0.f) continue;
            const AxisPlan& item = axes_[axis];
            if (!item.enabled || item.maxSpeed <= 0 || item.maxAccel <= 0 || item.maxDecel <= 0) {
                return refuse(faultOut, kSafety, kFaultNone);
            }
            if (fabsf(rates[axis]) > item.maxSpeed) return refuse(faultOut, kSafety, kFaultNone);
            if (item.referenceInvalid && (item.minAngleSet || item.maxAngleSet)) {
                return refuse(faultOut, kSafety, kFaultReference);
            }
        }
        for (int axis = 1; axis <= 3; ++axis) axes_[axis].commanded = rates[axis];
        lastMotionS_ = nowS;
        moving_ = pan != 0.f || tilt1 != 0.f || tilt2 != 0.f;
        timedOut_ = false;
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
        // This physical position becomes 0°. Settings do not call this.
        item.steps = 0;
        item.stepFraction = 0;
        item.homeDegrees = 0;
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
            enforceLimit(item);
            if (!item.referenced || item.externalSteps) continue;
            const float average = (previous + item.current) * 0.5f;
            const double delta = static_cast<double>(average) * dt / 360.0 * item.stepsPerRevolution * item.gearRatio;
            item.stepFraction += delta;
            const double whole = trunc(item.stepFraction);
            item.steps += static_cast<long>(whole);
            item.stepFraction -= whole;
        }
    }

    // Feed real step-pulse counts from the step engine. Call once per loop
    // with the delta reported by the hardware so `steps` stays truthful.
    void syncSteps(int axis, long delta) {
        if (axis < 1 || axis > 3) return;
        axes_[axis].steps += delta;
    }

    // Replace the step count with a position the pulse engine has finished.
    void adoptSteps(int axis, long steps) {
        if (axis < 1 || axis > 3) return;
        axes_[axis].steps = steps;
        axes_[axis].stepFraction = 0;
    }

    // Mark an axis as driven by the hardware pulse engine.
    void useExternalSteps(int axis, bool on) {
        if (axis < 1 || axis > 3) return;
        axes_[axis].externalSteps = on;
    }

    // Current angle of an axis in output-shaft degrees.
    float degreesAt(int axis) const {
        const AxisPlan& item = axes_[axis];
        return stepsToDegrees(item.steps, item.stepsPerRevolution, item.gearRatio);
    }

    // Build the 48-byte RCWM status body. Same layout as the Jetson encoder.
    std::vector<uint8_t> statusBody() const {
        std::vector<uint8_t> raw(48, 0);
        const bool moving = isMoving();
        const uint8_t fault = faultCode();
        uint16_t flags = kFlagEsp32;
        if (!moving) flags |= kFlagStopped;
        if (moving) flags |= kFlagMoving;
        if (fault == kFaultNone) flags |= kFlagClear;
        if (fault != kFaultNone) flags |= kFlagFault | kFlagDegraded;
        putU16(raw, 0, flags);
        raw[2] = static_cast<uint8_t>(activeTilt_);
        raw[3] = 0;  // owner lives on the Jetson
        raw[4] = kProtocolVersion;
        raw[5] = fault;
        for (int index = 0; index < 3; ++index) {
            const int axis = index + 1;
            const AxisPlan& item = axes_[axis];
            const size_t at = 6 + index * 14;
            uint8_t axisFlags = 0;
            if (item.enabled) axisFlags |= kAxisEnabled;
            if (item.referenceInvalid) axisFlags |= kAxisInvalid;
            else if (item.referenced) axisFlags |= kAxisReferenced;
            if (item.current > 1e-3f) axisFlags |= kAxisPos;
            else if (item.current < -1e-3f) axisFlags |= kAxisNeg;
            raw[at] = axisFlags;
            raw[at + 1] = 0;
            const int32_t degrees = item.referenced
                ? static_cast<int32_t>(lround(degreesAt(axis) * kCenti))
                : kUnknownI32;
            const int32_t steps = item.referenced ? static_cast<int32_t>(item.steps) : kUnknownI32;
            putI32(raw, at + 2, degrees);
            putI32(raw, at + 6, steps);
            putU16(raw, at + 10, item.maxSpeed > 0 ? speed16(item.maxSpeed) : kU16None);
            putU16(raw, at + 12, item.maxAccel > 0 ? speed16(item.maxAccel) : kU16None);
        }
        return raw;
    }

    uint8_t faultCode() const {
        if (!executionEnabled_) return kFaultController;
        return timedOut_ ? kFaultTimeout : kFaultNone;
    }

    bool isMoving() const {
        for (int axis = 1; axis <= 3; ++axis) {
            if (fabsf(axes_[axis].current) > 1e-3f) return true;
            if (fabsf(axes_[axis].commanded) > 1e-6f) return true;
        }
        return false;
    }

    // An operator-reachable recovery from a latched link-timeout fault:
    // the software stop or a new reference clears it once axes are halted.
    void clearTimeoutFault() {
        timedOut_ = false;
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
            item.stepFraction = 0;
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
        putU16(body, 8, item.maxSpeed > 0 ? speed16(item.maxSpeed) : kU16None);
        putU16(body, 10, item.maxAccel > 0 ? speed16(item.maxAccel) : kU16None);
        putU16(body, 12, item.maxDecel > 0 ? speed16(item.maxDecel) : kU16None);
        putI16(body, 14, item.minAngleSet ? angle16(item.minAngle) : kAngleUnset);
        putI16(body, 16, item.maxAngleSet ? angle16(item.maxAngle) : kAngleUnset);
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
        const int stepsPerRevolution = u16(body, 2);
        const float gearRatio = static_cast<float>(u32(body, 4)) / kGearScale;
        if (stepsPerRevolution <= 0 || gearRatio <= 0) return false;
        // Steps and the reference stay as they are. Only Set home moves the zero.
        item.enabled = flags & kCfgEnabled;
        item.reversed = flags & kCfgReversed;
        item.stepsPerRevolution = stepsPerRevolution;
        item.gearRatio = gearRatio;
        item.maxSpeed = fromSpeed(u16(body, 8));
        item.maxAccel = fromSpeed(u16(body, 10));
        item.maxDecel = fromSpeed(u16(body, 12));
        const int16_t minRaw = i16(body, 14);
        const int16_t maxRaw = i16(body, 16);
        item.minAngle = fromAngle(minRaw);
        item.maxAngle = fromAngle(maxRaw);
        item.minAngleSet = minRaw != kAngleUnset;
        item.maxAngleSet = maxRaw != kAngleUnset;
        item.homeDegrees = fromAngle(i16(body, 18));
        item.deadbandPercent = body[20];
        if (!item.enabled) {
            item.commanded = 0;
            item.current = 0;
        }
        return true;
    }

    // Load config for one axis from Preferences (NVS). Called on boot.
    void loadConfig(int axis) {
        (void)axis;
#if defined(ARDUINO)
        if (axis < 1 || axis > 3) return;
        Preferences prefs;
        prefs.begin(kPrefsNs, true);
        std::vector<uint8_t> body(kConfigBody, 0);
        size_t read = prefs.getBytes(prefsKey(axis), body.data(), kConfigBody);
        prefs.end();
        if (read != kConfigBody) return;
        applyConfigBody(axis, body);
        loadPosition(axis);
#endif
    }

    // Save config for one axis to Preferences (NVS).
    bool saveConfig(int axis) {
        (void)axis;
#if defined(ARDUINO)
        if (axis < 1 || axis > 3) return false;
        Preferences prefs;
        if (!prefs.begin(kPrefsNs, false)) return false;
        const std::vector<uint8_t> body = configBody(axis);
        const size_t written = prefs.putBytes(prefsKey(axis), body.data(), kConfigBody);
        prefs.end();
        return written == kConfigBody;
#else
        return true;
#endif
    }

    // Persist the last halted position so a reboot keeps the angle. If the
    // mount is moved by hand while powered off the stored angle is wrong
    // until Set home is pressed again.
    void savePosition(int axis) {
        (void)axis;
#if defined(ARDUINO)
        if (axis < 1 || axis > 3) return;
        Preferences prefs;
        if (!prefs.begin(kPrefsNs, false)) return;
        const AxisPlan& item = axes_[axis];
        const int32_t steps = static_cast<int32_t>(item.steps);
        const uint8_t blob[5] = {
            static_cast<uint8_t>(steps & 0xFF),
            static_cast<uint8_t>((steps >> 8) & 0xFF),
            static_cast<uint8_t>((steps >> 16) & 0xFF),
            static_cast<uint8_t>((steps >> 24) & 0xFF),
            static_cast<uint8_t>(item.referenced && !item.referenceInvalid ? 1 : 0),
        };
        prefs.putBytes(prefsPosKey(axis), blob, sizeof(blob));
        prefs.end();
#endif
    }

    void loadPosition(int axis) {
        (void)axis;
#if defined(ARDUINO)
        if (axis < 1 || axis > 3) return;
        Preferences prefs;
        prefs.begin(kPrefsNs, true);
        uint8_t blob[5] = {};
        const size_t read = prefs.getBytes(prefsPosKey(axis), blob, sizeof(blob));
        prefs.end();
        if (read != sizeof(blob) || blob[4] != 1) return;
        const int32_t steps =
            static_cast<int32_t>(blob[0]) | (static_cast<int32_t>(blob[1]) << 8) |
            (static_cast<int32_t>(blob[2]) << 16) | (static_cast<int32_t>(blob[3]) << 24);
        restorePosition(axis, steps, true);
#endif
    }

    // Restore a saved reference in host-testable form.
    void restorePosition(int axis, long steps, bool referenced) {
        if (axis < 1 || axis > 3 || !referenced) return;
        AxisPlan& item = axes_[axis];
        item.steps = steps;
        item.referenced = true;
        item.referenceInvalid = false;
    }

private:
    static int refuse(uint8_t* faultOut, int result, uint8_t fault) {
        if (faultOut != nullptr) *faultOut = fault;
        return result;
    }

    // Keep a moving axis inside its travel. Braking starts early enough that a
    // fast stick cannot coast past the limit. Motion back toward the range is
    // still allowed.
    static void enforceLimit(AxisPlan& item) {
        if (!item.referenced) return;
        const float degrees = stepsToDegrees(item.steps, item.stepsPerRevolution, item.gearRatio);
        const float decel = item.maxDecel > 0 ? item.maxDecel : item.maxAccel;
        if (item.maxAngleSet) clampToward(item, item.maxAngle - degrees, decel, true);
        if (item.minAngleSet) clampToward(item, degrees - item.minAngle, decel, false);
    }

    static void clampToward(AxisPlan& item, float room, float decel, bool positive) {
        const float speed = positive ? item.current : -item.current;
        const float command = positive ? item.commanded : -item.commanded;
        if (speed <= 0.f && command <= 0.f) return;
        if (room <= 0.05f || decel <= 0.f) {
            if (positive) {
                if (item.current > 0.f) item.current = 0.f;
                if (item.commanded > 0.f) item.commanded = 0.f;
            } else {
                if (item.current < 0.f) item.current = 0.f;
                if (item.commanded < 0.f) item.commanded = 0.f;
            }
            return;
        }
        const float allow = sqrtf(2.f * decel * room);
        if (positive) {
            if (item.current > allow) item.current = allow;
            if (item.commanded > allow) item.commanded = allow;
        } else {
            if (item.current < -allow) item.current = -allow;
            if (item.commanded < -allow) item.commanded = -allow;
        }
    }

    static float stepsToDegrees(long steps, int stepsPerRevolution, float gearRatio) {
        const double divisor = static_cast<double>(stepsPerRevolution) * (gearRatio > 0 ? gearRatio : 1.0);
        return static_cast<float>(static_cast<double>(steps) / divisor * 360.0);
    }

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
    static void putI32(std::vector<uint8_t>& b, size_t at, int32_t v) {
        putU32(b, at, static_cast<uint32_t>(v));
    }
    static uint16_t speed16(float value) {
        if (!isfinite(value)) return kU16None;
        const long clamped = std::min(lround(value * kCenti), static_cast<long>(kU16None) - 1);
        return static_cast<uint16_t>(std::max(0L, clamped));
    }
    static float fromSpeed(uint16_t raw) {
        return raw == kU16None ? 0.f : static_cast<float>(raw) / kCenti;
    }
    static int16_t angle16(float value) {
        if (!isfinite(value)) return kAngleUnset;
        const long clamped = std::min(lround(value * kCenti), 32767L);
        return static_cast<int16_t>(std::max(-32767L, clamped));
    }
    static float fromAngle(int16_t raw) {
        return raw == kAngleUnset ? 0.f : static_cast<float>(raw) / kCenti;
    }
    static const char* prefsKey(int axis) {
        static char keys[4][8] = {"", "pan", "tilt1", "tilt2"};
        return keys[axis];
    }
    static const char* prefsPosKey(int axis) {
        static char keys[4][10] = {"", "panpos", "t1pos", "t2pos"};
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
