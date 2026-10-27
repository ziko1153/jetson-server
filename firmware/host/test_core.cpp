#include <cassert>
#include <cstring>
#include <string>

#include "../esp32/include/motion.hpp"
#include "../esp32/include/protocol.hpp"

static void testCrcAndFrame() {
    const std::string sample = "123456789";
    assert(crc16CcittFalse(reinterpret_cast<const uint8_t*>(sample.data()), sample.size()) == 0x29B1);
    const std::vector<uint8_t> payload = {2};
    const auto frame = encodeFrame(kSelect, 7, payload);
    assert(frame[0] == 0xA5 && frame[1] == 0x5A);
    FrameParser parser;
    for (uint8_t byte : frame) parser.push(byte);
    SerialFrame parsed;
    assert(parser.next(parsed));
    assert(parsed.type == kSelect);
    assert(parsed.sequence == 7);
    assert(parsed.payload == payload);
}

static void testBlockedHardwareDoesNotRun() {
    MotionPlanner blocked(false);
    blocked.axis(2).enabled = true;
    blocked.axis(2).maxSpeed = 30;
    blocked.axis(2).maxAccel = 30;
    blocked.axis(2).maxDecel = 30;
    assert(blocked.select(3) == kApplied);
    assert(blocked.motion(0, 0, 10, 0) == kSafety);
    assert(blocked.axis(3).commanded == 0);
    assert(blocked.pulsesFor(3) == 0);
    assert(!blocked.executionEnabled());
}

static void testRampTimeoutAndHome() {
    MotionPlanner planner(true);
    for (int axis = 1; axis <= 3; ++axis) {
        planner.axis(axis).enabled = true;
        planner.axis(axis).maxSpeed = 90;
        planner.axis(axis).maxAccel = 1000;
        planner.axis(axis).maxDecel = 1000;
        planner.axis(axis).linkTimeoutS = 0.2f;
        planner.axis(axis).stepsPerRevolution = 1600;
        planner.axis(axis).gearRatio = 1;
    }
    assert(planner.motion(0, 4, 4, 0) == kSafety);
    assert(planner.select(2) == kApplied);
    assert(planner.motion(0, 36, 0, 1) == kApplied);
    planner.advance(0.05f, 1.05f);
    assert(planner.axis(2).current > 0);
    assert(planner.pulsesFor(2) == 0);
    planner.stop(false);
    planner.advance(0.2f, 1.3f);
    assert(planner.axis(2).current == 0);
    assert(planner.setHome(2) == kApplied);
    assert(planner.axis(2).referenced);
    planner.restart();
    assert(planner.axis(2).referenceInvalid);
    assert(!planner.axis(2).referenced);
    assert(planner.axis(2).current == 0);
    planner.axis(1).enabled = true;
    assert(planner.motion(20, 0, 0, 5) == kApplied);
    planner.advance(0.05f, 5.05f);
    planner.advance(0.3f, 5.4f);
    assert(planner.timedOut());
    assert(planner.axis(1).current == 0);
}

static void testExternalStepsAndLimits() {
    MotionPlanner planner(true);
    AxisPlan& pan = planner.axis(1);
    pan.enabled = true;
    pan.maxSpeed = 360;
    pan.maxAccel = 100000;
    pan.maxDecel = 100000;
    pan.stepsPerRevolution = 3200;
    pan.gearRatio = 1;
    pan.minAngleSet = true;
    pan.minAngle = -90;
    pan.maxAngleSet = true;
    pan.maxAngle = 90;
    planner.useExternalSteps(1, true);
    planner.setHome(1);
    assert(pan.referenced);
    assert(planner.motion(0, 0, 0, 0) == kApplied);
    assert(planner.motion(360, 0, 0, 0) == kApplied);
    // Simulate the hardware emitting 800 pulses = +90 degrees.
    planner.syncSteps(1, 800);
    planner.advance(0.05f, 0.05f);
    // 90 degrees is the upper travel limit: the rate must be dropped.
    assert(pan.current == 0);
    assert(pan.commanded == 0);
    assert(pan.steps == 800);
    // Motion back toward the open range is accepted again.
    assert(planner.motion(-360, 0, 0, 0.1f) == kApplied);
    assert(planner.degreesAt(1) > 89.9f && planner.degreesAt(1) < 90.1f);
}

static void testReferenceFaultAndStatusBody() {
    MotionPlanner planner(true);
    AxisPlan& tilt = planner.axis(2);
    tilt.enabled = true;
    tilt.maxSpeed = 90;
    tilt.maxAccel = 90;
    tilt.maxDecel = 90;
    tilt.minAngleSet = true;
    tilt.minAngle = -30;
    tilt.maxAngleSet = true;
    tilt.maxAngle = 30;
    planner.select(2);
    uint8_t fault = 99;
    // The reference is invalid while limits are set: SAFETY + FAULT_REFERENCE.
    assert(planner.motion(0, 30, 0, 0) == kSafety);
    assert(planner.motion(0, 30, 0, 0, &fault) == kSafety);
    assert(fault == kFaultReference);
    assert(planner.setHome(2) == kApplied);
    fault = 99;
    assert(planner.motion(0, 30, 0, 0, &fault) == kApplied);
    assert(fault == kFaultNone);
    planner.advance(0.05f, 0.05f);
    assert(planner.axis(2).current > 0);
    const std::vector<uint8_t> body = planner.statusBody();
    assert(body.size() == 48);
    assert(body[4] == kProtocolVersion);
    assert(body[2] == 2);  // active tilt
    const uint16_t flags = static_cast<uint16_t>(body[0] | (body[1] << 8));
    assert(flags & kFlagEsp32);
    assert(flags & kFlagMoving);
    const uint8_t tiltFlags = body[6 + 14];
    assert(tiltFlags & kAxisEnabled);
    assert(tiltFlags & kAxisReferenced);
    assert(tiltFlags & kAxisPos);
    // Degrees: home 0 plus the ramped rate, centi-degrees as int32.
    const int32_t degrees = static_cast<int32_t>(
        static_cast<uint32_t>(body[6 + 14 + 2]) |
        (static_cast<uint32_t>(body[6 + 14 + 3]) << 8) |
        (static_cast<uint32_t>(body[6 + 14 + 4]) << 16) |
        (static_cast<uint32_t>(body[6 + 14 + 5]) << 24));
    assert(degrees >= 0);
}

static void testConfigAngleUnsetRoundTrip() {
    MotionPlanner planner(true);
    const std::vector<uint8_t> body = planner.configBody(1);
    assert(static_cast<int16_t>(body[14] | (body[15] << 8)) == kAngleUnset);
    assert(static_cast<int16_t>(body[16] | (body[17] << 8)) == kAngleUnset);
    std::vector<uint8_t> withConfig(body);
    const int16_t limit = static_cast<int16_t>(12345);  // 123.45 degrees
    withConfig[14] = static_cast<uint8_t>(limit & 0xFF);
    withConfig[15] = static_cast<uint8_t>((limit >> 8) & 0xFF);
    assert(planner.applyConfigBody(1, withConfig));
    assert(planner.axis(1).minAngleSet);
    assert(planner.axis(1).minAngle > 123.4f && planner.axis(1).minAngle < 123.5f);
    assert(!planner.axis(1).maxAngleSet);
    const std::vector<uint8_t> again = planner.configBody(1);
    assert(static_cast<int16_t>(again[14] | (again[15] << 8)) == limit);
    assert(static_cast<int16_t>(again[16] | (again[17] << 8)) == kAngleUnset);
}


static void testConfigKeepsReference() {
    MotionPlanner planner(true);
    AxisPlan& pan = planner.axis(1);
    pan.enabled = true;
    pan.maxSpeed = 30;
    pan.maxAccel = 100;
    pan.maxDecel = 100;
    pan.stepsPerRevolution = 1600;
    pan.gearRatio = 1;
    planner.setHome(1);
    pan.steps = 800;
    std::vector<uint8_t> body = planner.configBody(1);
    body[2] = static_cast<uint8_t>(3200 & 0xFF);
    body[3] = static_cast<uint8_t>((3200 >> 8) & 0xFF);
    assert(planner.applyConfigBody(1, body));
    assert(pan.referenced);
    assert(!pan.referenceInvalid);
    assert(pan.stepsPerRevolution == 3200);
    assert(pan.steps == 800);
}

static void testFastMoveStopsInsideLimit() {
    MotionPlanner planner(true);
    AxisPlan& pan = planner.axis(1);
    pan.enabled = true;
    pan.maxSpeed = 90;
    pan.maxAccel = 1000;
    pan.maxDecel = 100;
    pan.stepsPerRevolution = 360;
    pan.gearRatio = 1;
    pan.maxAngleSet = true;
    pan.maxAngle = 80;
    planner.setHome(1);
    pan.steps = 70;
    pan.commanded = 50;
    pan.current = 50;
    planner.advance(0.01f, 1.0f);
    assert(pan.current < 45.f);
    assert(pan.current > 0.f);
    pan.steps = 80;
    pan.commanded = 50;
    pan.current = 50;
    planner.advance(0.01f, 1.1f);
    assert(pan.current == 0.f);
    assert(pan.commanded == 0.f);
}

static void testRestorePositionAfterRestart() {
    MotionPlanner planner(true);
    planner.restart();
    assert(planner.axis(1).referenceInvalid);
    // Boot path: NVS hands back the position saved at the last halt.
    planner.restorePosition(1, 1234, true);
    assert(planner.axis(1).referenced);
    assert(!planner.axis(1).referenceInvalid);
    assert(planner.axis(1).steps == 1234);
    assert(fabsf(planner.degreesAt(1) - 1234.0f / 1600.0f * 360.0f) < 0.01f);
    planner.restart();
    assert(planner.axis(1).referenceInvalid);
    // A saved unreferenced entry restores nothing.
    planner.restorePosition(2, 500, false);
    assert(planner.axis(2).referenceInvalid);
    assert(!planner.axis(2).referenced);
}

int main() {
    testCrcAndFrame();
    testBlockedHardwareDoesNotRun();
    testRampTimeoutAndHome();
    testExternalStepsAndLimits();
    testReferenceFaultAndStatusBody();
    testConfigAngleUnsetRoundTrip();
    testConfigKeepsReference();
    testFastMoveStopsInsideLimit();
    testRestorePositionAfterRestart();
    return 0;
}
