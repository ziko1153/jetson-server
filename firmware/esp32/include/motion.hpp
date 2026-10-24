#pragma once

#include <math.h>

#include <algorithm>

// Step estimate and ramp. GPIO is a separate gate: this class does not know pin numbers.

enum MotionResult : int { kApplied = 2, kRejected = 3, kSafety = 7 };

struct AxisPlan {
    bool enabled = false;
    float maxSpeed = 0;
    float maxAccel = 0;
    float maxDecel = 0;
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

    bool executionEnabled_;
    int activeTilt_ = 0;
    bool moving_ = false;
    bool timedOut_ = false;
    float lastMotionS_ = 0;
    AxisPlan axes_[4];
};
