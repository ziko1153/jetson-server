#include <Arduino.h>

#include <FastAccelStepper.h>

#include <cstring>

#include "board.hpp"
#include "motion.hpp"
#include "protocol.hpp"

namespace {

// STEP/DIR must be wired. ENABLE is optional per axis: a value of -1 leaves
// that driver enable input unconnected and the firmware still moves the axis.
bool pinsAssigned() {
    const int stepAndDir[] = {
        BoardConfig::kPanStep, BoardConfig::kPanDir,
        BoardConfig::kTilt1Step, BoardConfig::kTilt1Dir,
        BoardConfig::kTilt2Step, BoardConfig::kTilt2Dir,
    };
    for (int pin : stepAndDir) {
        if (pin < 0) return false;
    }
    if (!BoardConfig::kPinsConfirmed) return false;
    const int enables[] = {BoardConfig::kPanEnable, BoardConfig::kTilt1Enable, BoardConfig::kTilt2Enable};
    for (int pin : enables) {
        if (pin >= 0 && BoardConfig::kEnablePolarity != 0 && BoardConfig::kEnablePolarity != 1) return false;
    }
    return true;
}

const bool kPinsOk = pinsAssigned();

// The planner owns the ramp in degrees per second. The pulse engine only
// needs to reach a newly commanded rate instantly, so its own acceleration
// is set very high and never shapes the motion.
constexpr int32_t kPulseAccel = 100000000;

FastAccelStepperEngine engine;
FastAccelStepper* motors[4] = {nullptr, nullptr, nullptr, nullptr};

MotionPlanner planner(kPinsOk);
FrameParser parser;
uint32_t bootId = 0;
bool energized = false;

std::vector<uint8_t> ack(uint16_t sequence, uint8_t request, uint8_t result, uint8_t fault = 0) {
    return encodeFrame(kAck, sequence, {request, result, fault});
}

// A position report is useful only when the host is keeping up. Skipping it
// keeps the control loop free to read the next stick command and to stop.
bool writeFrame(const std::vector<uint8_t>& frame, bool droppable) {
    if (droppable && Serial.availableForWrite() < static_cast<int>(frame.size())) return false;
    Serial.write(frame.data(), frame.size());
    return true;
}

std::vector<uint8_t> helloAckPayload() {
    return {
        static_cast<uint8_t>(bootId & 0xFF),
        static_cast<uint8_t>((bootId >> 8) & 0xFF),
        static_cast<uint8_t>((bootId >> 16) & 0xFF),
        static_cast<uint8_t>((bootId >> 24) & 0xFF),
        static_cast<uint8_t>(energized ? 1 : 0),
        kProtocolVersion,
    };
}

void rebaseMotor(int axis) {
    FastAccelStepper* s = motors[axis];
    if (s == nullptr) return;
    s->setCurrentPosition(0);
}

void haltMotor(int axis) {
    FastAccelStepper* s = motors[axis];
    if (s == nullptr || !s->isRunning()) return;
    s->stopMove();
}

// The driver position leads the STEP pin while a move is queued, so it is
// only copied once the motor has stopped and that queue is empty.
void settleMotor(int axis) {
    FastAccelStepper* s = motors[axis];
    if (s == nullptr || s->isRunning() || !s->isQueueEmpty()) return;
    const AxisPlan& item = planner.axis(axis);
    if (!item.referenced) return;
    const long pos = s->getCurrentPosition();
    const long delta = pos - item.steps;
    if (delta == 0 || delta > 200 || delta < -200) return;
    planner.adoptSteps(axis, pos);
}

void applyRates() {
    for (int axis = 1; axis <= 3; ++axis) {
        FastAccelStepper* s = motors[axis];
        if (s == nullptr) continue;
        const AxisPlan& item = planner.axis(axis);
        float dps = item.current;
        if (item.reversed) dps = -dps;
        const double stepsPerSec =
            fabs(dps) / 360.0 * item.stepsPerRevolution * (item.gearRatio > 0 ? item.gearRatio : 1.0);
        if (fabsf(dps) < 0.01f || stepsPerSec < 1.0) {
            haltMotor(axis);
            continue;
        }
        s->setSpeedInHz(static_cast<uint32_t>(stepsPerSec + 0.5));
        // runForward/runBackward reverse a motor that is already running the
        // other way. applySpeedAcceleration alone keeps the old direction.
        if (dps > 0) {
            s->runForward();
        } else {
            s->runBackward();
        }
        if (s->isRunning()) s->applySpeedAcceleration();
    }
}

void stopMotors() {
    for (int axis = 1; axis <= 3; ++axis) haltMotor(axis);
}

void handle(const SerialFrame& frame) {
    if (frame.type == kHello) {
        writeFrame(encodeFrame(kHelloAck, frame.sequence, helloAckPayload()), false);
        return;
    }
    if (frame.type == kPing) {
        writeFrame(encodeFrame(kPong, frame.sequence, {}), false);
        return;
    }
    if (frame.type == kStatusReq) {
        writeFrame(encodeFrame(kStatus, frame.sequence, planner.statusBody()), false);
        return;
    }
    if (frame.type == kConfigGet && !frame.payload.empty()) {
        const int axis = frame.payload[0];
        if (axis < 1 || axis > 3) {
            writeFrame(ack(frame.sequence, kConfigGet, kRejected), false);
            return;
        }
        const std::vector<uint8_t> body = planner.configBody(axis);
        std::vector<uint8_t> payload = {static_cast<uint8_t>(axis), kApplied};
        payload.insert(payload.end(), body.begin(), body.end());
        writeFrame(encodeFrame(kConfigReply, frame.sequence, payload), false);
        return;
    }
    if (frame.type == kConfigSet && frame.payload.size() >= 1 + kConfigBody) {
        const int axis = frame.payload[0];
        std::vector<uint8_t> body(frame.payload.begin() + 1, frame.payload.begin() + 1 + kConfigBody);
        if (!planner.applyConfigBody(axis, body)) {
            writeFrame(ack(frame.sequence, kConfigSet, kRejected), false);
            return;
        }
        if (!planner.saveConfig(axis)) {
            // ESP32 could not persist the config. Tell the Jetson so it can error the GCS.
            writeFrame(ack(frame.sequence, kConfigSet, kRejected), false);
            return;
        }
        planner.savePosition(axis);
        writeFrame(ack(frame.sequence, kConfigSet, kApplied), false);
        return;
    }
    if (frame.type == kSelect && !frame.payload.empty()) {
        writeFrame(ack(frame.sequence, kSelect, static_cast<uint8_t>(planner.select(frame.payload[0]))), false);
        return;
    }
    if (frame.type == kMotion && frame.payload.size() >= 12) {
        float rates[3] = {};
        memcpy(rates, frame.payload.data(), sizeof(rates));
        uint8_t fault = 0;
        const int result = planner.motion(rates[0], rates[1], rates[2], millis() / 1000.0f, &fault);
        writeFrame(ack(frame.sequence, kMotion, static_cast<uint8_t>(result), fault), false);
        return;
    }
    if (frame.type == kStop) {
        planner.stop(false);
        planner.clearTimeoutFault();
        writeFrame(ack(frame.sequence, kStop, kApplied), false);
        return;
    }
    if (frame.type == kSetHome && !frame.payload.empty()) {
        const int axis = frame.payload[0];
        const int result = planner.setHome(axis);
        if (result == kApplied) {
            rebaseMotor(axis);
            planner.clearTimeoutFault();
            planner.savePosition(axis);
        }
        writeFrame(ack(frame.sequence, kSetHome, static_cast<uint8_t>(result)), false);
        return;
    }
    writeFrame(ack(frame.sequence, frame.type, 5), false);
}

}  // namespace

void setup() {
    Serial.setRxBufferSize(1024);
    Serial.setTxBufferSize(1024);
    Serial.begin(BoardConfig::kBaud);
    bootId = micros();
    planner.restart();
    energized = false;
    // Load saved config for each axis from Preferences (NVS). ESP32 is the single source of truth.
    for (int axis = 1; axis <= 3; ++axis) {
        planner.loadConfig(axis);
    }
    if (kPinsOk) {
        const int stepPins[4] = {0, BoardConfig::kPanStep, BoardConfig::kTilt1Step, BoardConfig::kTilt2Step};
        const int dirPins[4] = {0, BoardConfig::kPanDir, BoardConfig::kTilt1Dir, BoardConfig::kTilt2Dir};
        const int enablePins[4] = {0, BoardConfig::kPanEnable, BoardConfig::kTilt1Enable, BoardConfig::kTilt2Enable};
        engine.init();
        for (int axis = 1; axis <= 3; ++axis) {
            FastAccelStepper* s = engine.stepperConnectToPin(stepPins[axis]);
            if (s == nullptr) continue;
            s->setDirectionPin(dirPins[axis]);
            s->setAcceleration(kPulseAccel);
            if (enablePins[axis] >= 0) {
                // Optional enable wire. Most drivers are active-low enable.
                s->setEnablePin(enablePins[axis], BoardConfig::kEnablePolarity == 0);
                s->setAutoEnable(true);
                s->setDelayToDisable(500);
            }
            // The library position counts steps still waiting in the queue.
            // The angle is the commanded motion instead, so a limit is not
            // reached before the motor has made those steps.
            s->setCurrentPosition(static_cast<int32_t>(planner.axis(axis).steps));
            motors[axis] = s;
            planner.useExternalSteps(axis, false);
        }
    }
    // Drivers stay released until the first motion command. The planner ramps
    // every rate and the pulse engine follows it.
}

void loop() {
    static uint32_t lastMs = millis();
    static bool helloAnnounced = false;
    const uint32_t now = millis();
    float dt = (now - lastMs) / 1000.0f;
    if (dt > 0.5f) dt = 0.5f;  // cap after a stall so the ramp stays sane
    lastMs = now;

    for (int axis = 1; axis <= 3; ++axis) settleMotor(axis);

    // 2. Ramp toward the commanded rates and enforce travel limits.
    planner.advance(dt, now / 1000.0f);

    // 3. Push the current rates to the pulse engines.
    if (kPinsOk) applyRates();

    // 4. Persist position shortly after an axis comes to a halt, so a reboot
    //    keeps the last halted angle. The short delay lets any in-flight
    //    pulses from the engine land in the count before the save.
    static bool wasMoving[4] = {false, false, false, false};
    static uint32_t saveDueMs = 0;
    for (int axis = 1; axis <= 3; ++axis) {
        const AxisPlan& item = planner.axis(axis);
        const bool moving = fabsf(item.current) > 1e-3f || fabsf(item.commanded) > 1e-6f;
        if (wasMoving[axis] && !moving) saveDueMs = now + 50;
        wasMoving[axis] = moving;
    }
    if (saveDueMs != 0 && now >= saveDueMs) {
        saveDueMs = 0;
        for (int axis = 1; axis <= 3; ++axis) planner.savePosition(axis);
    }

    // 4. Serve the serial protocol.
    while (Serial.available() > 0) {
        parser.push(static_cast<uint8_t>(Serial.read()));
        SerialFrame frame;
        while (parser.next(frame)) handle(frame);
    }

    if (planner.timedOut()) {
        stopMotors();
        energized = false;
    } else {
        energized = planner.isMoving();
    }

    // Announce once after boot so an already-open Jetson link learns the new
    // boot id and can re-pull configuration.
    if (!helloAnnounced && now > 2000) {
        helloAnnounced = true;
        writeFrame(encodeFrame(kHelloAck, 0, helloAckPayload()), true);
    }

    // Position goes out on its own four times a second. A stick command gets
    // only its short acknowledgement, so a burst of motion cannot fill the
    // serial buffer and stall the loop.
    static uint32_t lastStatusMs = 0;
    if (now - lastStatusMs >= 250) {
        if (writeFrame(encodeFrame(kStatus, 0, planner.statusBody()), true)) lastStatusMs = now;
    }
}
