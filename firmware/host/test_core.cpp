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

int main() {
    testCrcAndFrame();
    testBlockedHardwareDoesNotRun();
    testRampTimeoutAndHome();
    return 0;
}
