# JETSON DEVELOPMENT — PHASE 2

You are a Senior Python Engineer, NVIDIA Jetson Engineer, MAVLink Specialist, ESP32 Firmware Engineer, and Robotics Systems Architect.

Extend my existing Jetson server with **three modules**:

1. MAVLink Gateway

2. ESP32 RCWM Controller

3. Jetson System Health Monitoring

Build production-quality, modular code. Follow the existing project's architecture and conventions.

## 1. Read Existing Projects First

**Kotlin GCS project:**

`/Users/user/Developer/Bhimrul/Bhimrul GCS`

Before implementing anything:

- Read the Kotlin project's `AGENTS.md` and RCWM documentation.

- Read `RCWM_PROTOCOL.md`, `RCWM_SETTINGS.md`, and `RCWM_ARCHITECTURE.md`, wherever they exist.

- Inspect the actual Kotlin MAVLink implementation, RCWM commands, and data models.

- Read the Jetson project's `AGENTS.md`, architecture, API documentation, and `agent-notebook/`.

- Identify unfinished work and protocol mismatches.

**The Kotlin implementation is the existing integration reference.** Verify its messages against MAVLink definitions and correct protocol inconsistencies through documentation and compatible backend design.

Do not modify Kotlin GCS source code. Report required changes separately.

## 2. MAVLink Gateway

Implement a MAVLink gateway using Python and `pymavlink`.

Existing architecture:

| Device | System ID | Component ID |

|---|---|---|

| Rover / Matek H743 | 1 | 1 |

| Jetson companion | 1 | 191 |

| RCWM controller | 1 | 171 |

| G30 #1 | 255 | 190 |

| G30 #2 | 254 | 190 |

### Responsibilities

- Receive MAVLink over UDP port `14550`.

- Support Jetson's GR03, mesh, and VPN network addresses.

- Communicate with Matek H743 through its configured UART.

- Forward flight-controller commands to Matek.

- Forward Matek telemetry back to the appropriate GCS endpoints.

- Route RCWM commands to the RCWM controller service.

- Publish Jetson component `191` heartbeat and respond to supported health/time-sync requests.

- Handle multiple GCS connections.

- Prevent message forwarding loops and unintended duplicate commands.

- Monitor connection status and handle reconnection.

- Preserve MAVLink message routing and target component IDs.

**Important:** The direct G30 → GR03 serial → Matek connection must remain independent and operational.

Do not put MAVLink movement control behind the camera HTTP API or its Bearer Token authentication.

Use appropriate MAVLink channel security and validate command sources. Do not assume that UDP source addresses or component IDs authenticate a controller.

Keep the existing GCS route priorities. Do not implement competing network failover logic inside Jetson.

## 3. ESP32 RCWM Controller

Our RCWM is a **Remote-Controlled Water Mount**, not a camera gimbal.

Hardware:

- ESP32 DevKit connected to Jetson through USB serial.

- Three NEMA 34 stepper motors.

- Three external STEP/DIR motor drivers.

Axes:

| Axis | Function |

|---|---|

| Pan | Horizontal rotation |

| Tilt 1 | First vertical rotation |

| Tilt 2 | Second vertical rotation |

The GCS operator selects either Tilt 1 or Tilt 2.

Only **Pan + the selected Tilt** may respond to joystick commands.

### Responsibilities

Implement both:

**A. Jetson Python RCWM service**

- Decode RCWM MAVLink commands.

- Translate commands into a documented, versioned ESP32 USB serial protocol.

- Validate configurations.

- Persist motor settings.

- Handle controller acknowledgments, timeouts, and errors.

- Return RCWM status and estimated positions to GCS.

- Support two G30 controllers with explicit control ownership.

**B. ESP32 firmware (C++ / PlatformIO)**

- Control three STEP/DIR stepper drivers.

- Generate nonblocking step pulses with acceleration/deceleration.

- Support manual jogging, movement, stop, and manual Set Home.

- Maintain separate configurations for all three motors.

- Count commanded steps to estimate angular position.

- Return controller status and command acknowledgments.

- Stop commanded motion when communication times out.

- Reject invalid commands and unsafe configurations.

### Motor settings

Default:

- Steps per revolution: `1600`

- Gear ratio: `1.0`

Each motor must independently support configurable speed, acceleration, deceleration, direction inversion, soft limits, and manual home position.

Do not assume safe speed, acceleration, or travel limits based on NEMA 34 motor size. These require hardware commissioning.

### Safety requirements

This is heavy machinery.

- A physical emergency-stop and independent motor power-disable mechanism are required.

- Software STOP is not a replacement for hardware emergency stop.

- Without encoders, physical position cannot be verified.

- Display positions as estimates.

- Invalidate position references after ESP32 restart.

- Prevent conflicting commands from G30 #1 and G30 #2.

- Stop the previously selected tilt before changing active tilt.

- Reject stale movement commands.

- Do not replay movement commands after reconnecting.

- Do not energize motors or start motion automatically during startup.

Implement testable firmware and a hardware-independent simulation mode on macOS.

**Do not assume GPIO pin assignments, driver enable polarity, electrical timing, or safe motion values.** Keep them configurable and require confirmation before physical motor testing.

## 4. Jetson System Health Monitoring

Extend the existing FastAPI server with lightweight system monitoring.

Monitor:

- CPU usage

- RAM usage

- Disk usage

- System uptime

- Jetson temperature

- GPU utilization when supported

- Jetson hardware and JetPack information

- Camera service status

- MAVLink gateway status

- ESP32 connection status

- RCWM controller status

Expose:

```http

GET /api/v1/system/status

```

Reuse existing health APIs where available. Do not create duplicate endpoints.

On macOS, report available system metrics and mark NVIDIA-specific metrics unavailable.

Use supported Jetson interfaces and tools for actual hardware metrics.

Do not fabricate measurements.

## 5. Cross-Platform Development

I currently develop on macOS and will deploy to NVIDIA Jetson Orin NX.

**The same Python application source must work on both platforms.**

Requirements:

- Develop and test Python gateway logic on macOS.

- Support MAVLink SITL testing.

- Support USB-connected ESP32 testing from Mac.

- Use configurable serial ports and network addresses.

- Keep Jetson-specific code isolated.

- Do not hardcode `/dev/ttyUSB0` or other device paths.

- Extend existing setup scripts rather than replacing them.

- Update `setup-jetson.sh` to install and configure necessary dependencies.

- Provide ESP32 firmware build/upload instructions.

- Preserve the existing camera, RTSP, and mosaic modules.

- Do not make Docker mandatory.

**Deployment goal:** Copy the project to Jetson, run the setup script, configure the physical connections, and start the existing server without manually rewriting Python source code.

## 6. Architecture and Documentation

Use the existing enterprise project structure.

Keep these services separate:

```text

Jetson Server

│

├── Camera / RTSP / Mosaic (existing)

├── MAVLink Gateway (new)

├── RCWM Controller (new)

└── System Health (new)

ESP32 Firmware (separate module)

```

Define one stable, versioned communication contract between Jetson and ESP32.

Do not require Jetson source-code changes when ESP32 GPIO pins or internal motor-control algorithms change, provided the protocol remains compatible.

Create or update:

- `docs/MAVLINK_GATEWAY.md`

- `docs/RCWM_INTEGRATION.md`

- `docs/RCWM_SERIAL_PROTOCOL.md`

- `docs/ESP32_FIRMWARE.md`

- `docs/API.md`

- `docs/JETSON_DEPLOYMENT.md`

Update the existing `AGENTS.md` and `agent-notebook/` with architectural decisions, completed work, pending tasks, test results, and known limitations.

Future coding agents must be able to understand the project from these files.

## 7. Testing and Completion

Implement and execute tests for:

- MAVLink message decoding and routing.

- Jetson component 191 heartbeat.

- GCS IDs 255 and 254.

- RCWM component 171 communication.

- ESP32 USB serial commands.

- Three independent motor configurations.

- Active Tilt 1 / Tilt 2 switching.

- Manual reference setting and position estimation.

- Command timeout and stop behavior.

- Connection loss and recovery.

- System health endpoints.

- macOS compatibility.

Use ArduPilot SITL and simulated ESP32 responses where appropriate.

Do not automatically execute physical motor movement tests. Real motor tests require deliberate operator approval and hardware safety checks.

### Final instructions

Start by inspecting both existing projects and their documentation.

Implement these three modules without breaking the camera system or existing Kotlin MAVLink behavior.

Reuse established APIs, configuration patterns, logging, tests, and deployment scripts.

Document unresolved integration mismatches rather than hiding them.

At completion, report:

1. Features implemented.

2. Files created or modified.

3. MAVLink integration status.

4. ESP32 firmware build and USB test instructions.

5. System health API.

6. Tests actually executed.

7. Remaining hardware validation.

8. Any changes required in Kotlin GCS.

**Begin implementation now.**