#pragma once

#include <math.h>
#include <stdint.h>

#include <algorithm>
#include <vector>

#include "motion.hpp"

// Pan patrol between two angles, run on the ESP32 so it keeps going when the
// ground station link drops. It only writes the pan commanded rate through the
// planner's public axis accessor; the planner still ramps the rate and still
// enforces the pan soft limits.
//
// The patrol range must sit inside the configured pan soft limits. Braking is
// planned from the pan deceleration so the axis stops kEdgeMarginDeg inside the
// range and turns around there. While patrol runs, joystick pan is refused and
// joystick tilt keeps working.
class PanPatrol {
public:
    enum Reason : uint8_t {
        kReasonNone = 0,
        kReasonOperator = 1,
        kReasonRange = 2,
        kReasonNoLimits = 3,
        kReasonOutsideLimits = 4,
        kReasonSpeed = 5,
        kReasonNotReady = 6,
        kReasonNoReference = 7,
        kReasonDisabled = 8,
    };

    static constexpr int kPan = 1;
    static constexpr size_t kStatusSize = 8;
    static constexpr float kMinSpanDeg = 1.0f;
    static constexpr float kEdgeMarginDeg = 0.1f;
    static constexpr float kTurnDeg = 0.2f;

    // Returns kReasonNone when patrol started.
    uint8_t start(MotionPlanner& planner, float minDeg, float maxDeg, float speedDps) {
        const uint8_t reason = check(planner, minDeg, maxDeg, speedDps);
        if (reason != kReasonNone) return reason;
        minDeg_ = minDeg;
        maxDeg_ = maxDeg;
        speedDps_ = speedDps;
        const float pos = planner.degreesAt(kPan);
        direction_ = (maxDeg - pos) >= (pos - minDeg) ? 1 : -1;
        active_ = true;
        reason_ = kReasonNone;
        return kReasonNone;
    }

    void stop(MotionPlanner& planner, uint8_t why) {
        if (!active_) return;
        active_ = false;
        reason_ = why;
        planner.axis(kPan).commanded = 0;
    }

    // A joystick motion command with a tilt rate was accepted at nowS.
    void noteJoystick(float nowS, bool tiltMoving) {
        lastJoystickS_ = nowS;
        tiltMoving_ = tiltMoving;
    }

    // Call once per loop before planner.advance().
    void service(MotionPlanner& planner, float nowS) {
        if (!active_) return;
        const uint8_t reason = check(planner, minDeg_, maxDeg_, speedDps_);
        if (reason != kReasonNone) {
            stop(planner, reason);
            return;
        }
        releaseStaleTilt(planner, nowS);
        planner.axis(kPan).commanded = rate(planner);
    }

    bool active() const { return active_; }

    // state, last stop reason, min and max in centi-degrees, speed in centi-degrees/second.
    std::vector<uint8_t> statusBlock() const {
        std::vector<uint8_t> raw(kStatusSize, 0);
        raw[0] = active_ ? 1 : 0;
        raw[1] = reason_;
        putI16(raw, 2, centi(minDeg_));
        putI16(raw, 4, centi(maxDeg_));
        putU16(raw, 6, static_cast<uint16_t>(std::max(0L, std::min(65534L, lround(speedDps_ * 100.f)))));
        return raw;
    }

private:
    static uint8_t check(MotionPlanner& planner, float minDeg, float maxDeg, float speedDps) {
        if (!planner.executionEnabled()) return kReasonDisabled;
        const AxisPlan& pan = planner.axis(kPan);
        if (!pan.enabled || pan.maxSpeed <= 0 || pan.maxAccel <= 0 || pan.maxDecel <= 0) return kReasonNotReady;
        if (!pan.referenced || pan.referenceInvalid) return kReasonNoReference;
        if (!pan.minAngleSet || !pan.maxAngleSet) return kReasonNoLimits;
        if (!isfinite(minDeg) || !isfinite(maxDeg) || maxDeg - minDeg < kMinSpanDeg) return kReasonRange;
        if (minDeg < pan.minAngle || maxDeg > pan.maxAngle) return kReasonOutsideLimits;
        if (!isfinite(speedDps) || speedDps <= 0 || speedDps > pan.maxSpeed) return kReasonSpeed;
        return kReasonNone;
    }

    // Commanded pan rate that brakes to a stop inside the range, then turns.
    float rate(MotionPlanner& planner) {
        const AxisPlan& pan = planner.axis(kPan);
        const float pos = planner.degreesAt(kPan);
        const float low = minDeg_ + kEdgeMarginDeg;
        const float high = maxDeg_ - kEdgeMarginDeg;
        float room = direction_ > 0 ? high - pos : pos - low;
        if (room <= kTurnDeg) {
            direction_ = -direction_;
            room = direction_ > 0 ? high - pos : pos - low;
        }
        if (room <= 0.f) return 0.f;
        // Planned at half the deceleration, so the planner ramp can always
        // follow the braking curve and never coasts past it.
        const float allow = sqrtf(pan.maxDecel * room);
        return direction_ * std::min(speedDps_, allow);
    }

    // The planner stops every axis at once when joystick commands go quiet.
    // During patrol that would slam pan to a halt, so a quiet tilt stick is
    // released here first and ramps down instead.
    void releaseStaleTilt(MotionPlanner& planner, float nowS) {
        if (!tiltMoving_) return;
        if (nowS - lastJoystickS_ < 0.7f * linkTimeout(planner)) return;
        tiltMoving_ = false;
        planner.motion(0, 0, 0, nowS);
    }

    static float linkTimeout(MotionPlanner& planner) {
        float value = 0.5f;
        bool seen = false;
        for (int axis = 1; axis <= 3; ++axis) {
            const AxisPlan& item = planner.axis(axis);
            if (!item.enabled) continue;
            if (!seen || item.linkTimeoutS < value) value = item.linkTimeoutS;
            seen = true;
        }
        return value;
    }

    static int16_t centi(float degrees) {
        return static_cast<int16_t>(std::max(-32767L, std::min(32767L, lround(degrees * 100.f))));
    }
    static void putU16(std::vector<uint8_t>& b, size_t at, uint16_t v) {
        b[at] = static_cast<uint8_t>(v & 0xFF);
        b[at + 1] = static_cast<uint8_t>((v >> 8) & 0xFF);
    }
    static void putI16(std::vector<uint8_t>& b, size_t at, int16_t v) { putU16(b, at, static_cast<uint16_t>(v)); }

    bool active_ = false;
    uint8_t reason_ = kReasonNone;
    float minDeg_ = 0;
    float maxDeg_ = 0;
    float speedDps_ = 0;
    int direction_ = 1;
    float lastJoystickS_ = 0;
    bool tiltMoving_ = false;
};
