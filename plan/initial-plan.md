# MASTER DEVELOPMENT PROMPT
## UGV Jetson Orin NX Camera Gateway & Video Management System

### YOUR ROLE

You are a **Principal Software Architect, Senior Python Backend Engineer, NVIDIA Jetson Multimedia Engineer, RTSP/GStreamer Specialist, and DevOps Engineer**.

Your responsibility is to design, implement, test, and document a production-oriented camera management and video streaming server for an Unmanned Ground Vehicle (UGV).

This is a real robotics project, not a demonstration.

Build clean, modular, maintainable, testable, and extensible code.

**Do not stop after generating architecture documents or scaffolding. Implement the working system, execute tests, fix failures, and document the results.**

Do not ask unnecessary clarification questions. Make sensible engineering decisions, document assumptions, and proceed.

---

# 1. PROJECT BACKGROUND

We are building a UGV with the following hardware.

### Ground Control Station

- Skydroid G30 Android controller
- Custom Kotlin-based GCS application
- Skydroid GR03 radio receiver on the UGV
- Separate ground and UGV mesh radio network
- Optional 4G/VPN connection

### UGV Hardware

- NVIDIA Jetson Orin NX
- Six Ethernet IP cameras
- Ethernet switch
- Skydroid GR03 LAN0 connected to the switch
- UGV mesh radio connected to the switch
- Jetson Ethernet connected to the switch
- Matek H743 flight controller
- ESP32 pan/tilt controller

For this development phase, **implement camera and streaming features only**.

Do not implement MAVLink, ESP32, or vehicle control yet.

However, design the architecture so those modules can be added later without restructuring existing services.

### Current Network Plan

The Jetson will have multiple IP addresses on its Ethernet interface.

```text
GR03 network:
192.168.144.20/24

Mesh network:
10.10.0.20/24

VPN:
10.8.0.20
```

These are intended deployment addresses, not guarantees of connectivity.

The VPN address must be assigned through the actual VPN interface, not blindly added to Ethernet.

Do not automatically configure or overwrite Linux network interfaces during application installation.

Provide separate, documented network setup and validation procedures.

### Network Architecture

```text
                    SKYDROID G30
                     Kotlin GCS
                         |
                 Wireless GR03 link
                         |
                    GR03 Receiver
                         |
                       LAN0
                         |
                         v
                  Ethernet Switch
                         |
       +-----------------+------------------+
       |                 |                  |
    Jetson           6 IP Cameras       UGV Mesh
       |                                    |
       |                              Ground Mesh
       |                                    |
       +---------- Network Access ----------+
```

There are three planned communication paths:

1. GR03 radio network
2. Mesh network
3. 4G/VPN network

The G30 must actually have IP connectivity through a path before it can use that path.

Do not assume merely assigning multiple IP addresses to the Jetson creates routing or automatic failover.

---

# 2. PRIMARY DEVELOPMENT GOAL

Build a centralized **Jetson Camera Gateway**.

All normal camera operations should be managed through the Jetson.

The Kotlin GCS should:

1. Request the camera list from Jetson.
2. Retrieve camera names, IDs, capabilities, and status.
3. Request camera configuration changes through Jetson.
4. Request individual RTSP streams through Jetson.
5. Request customized mosaic layouts through Jetson.
6. Receive a single RTSP stream for each mosaic session.
7. Fall back to direct camera RTSP when Jetson is unavailable.
8. Display actual video resolution, FPS, codec, and bitrate information when available.

Jetson should handle:

- Camera registry
- Camera configuration
- Camera health monitoring
- RTSP stream management
- Stream forwarding
- Video quality profiles
- Mosaic generation
- Mosaic configuration
- API validation
- Persistent configuration
- Audit logging
- Error handling
- Stream recovery

The server must be developed first on macOS and deployed later to NVIDIA Jetson Orin NX running Linux.

---

# 3. TECHNOLOGY STACK

Use the following primary stack.

| Component | Technology |
|---|---|
| Language | Python 3 |
| API Framework | FastAPI |
| API Validation | Pydantic |
| ASGI Server | Uvicorn |
| Configuration | JSON |
| Media Processing | GStreamer / FFmpeg |
| RTSP Distribution | MediaMTX |
| Camera Configuration | ONVIF / Vendor API |
| Testing | pytest |
| HTTP Testing | httpx |
| Deployment | Bash scripts |
| Logging | Python structured logging |
| Documentation | Markdown + OpenAPI |

Use Python's standard logging facilities or a lightweight structured logging library.

Use SQLite for operational history and audit logs if appropriate.

Keep JSON as the main human-editable configuration format.

Do not introduce unnecessary frameworks or infrastructure.

Docker must not be required to run the application.

Python virtual environments are required.

---

# 4. CROSS-PLATFORM REQUIREMENTS

This requirement is extremely important.

I currently develop on:

```text
macOS
```

Later, I will deploy the project to:

```text
NVIDIA Jetson Orin NX
JetPack Linux
ARM64
```

I do not want to manually rewrite Python source files when moving from Mac to Jetson.

### Requirements

Create an environment detection system.

It must identify:

- macOS development environment
- Generic Linux environment
- NVIDIA Jetson Linux environment
- NVIDIA JetPack version, when available
- GStreamer availability
- NVIDIA-specific GStreamer plugins
- FFmpeg availability
- MediaMTX availability

Do not identify a machine as Jetson merely because its CPU architecture is ARM64.

Use Jetson-specific system indicators and validate actual multimedia plugin availability.

### Example conceptual configuration

```json
{
  "environment": {
    "mode": "auto",
    "hardware": "auto",
    "media_backend": "auto"
  }
}
```

Expected behavior:

**On macOS:**

- Use supported FFmpeg/GStreamer software pipelines.
- Run FastAPI normally.
- Run MediaMTX.
- Support real RTSP cameras.
- Support virtual RTSP cameras.
- Support real mosaic composition.
- Simulate unavailable NVIDIA-specific features.

**On Jetson Linux:**

- Use supported Jetson GStreamer components where appropriate.
- Use NVIDIA-accelerated decoding/conversion/composition when supported.
- Select an available, tested output encoder.
- Run the same FastAPI application.
- Run the same API contracts.
- Run the same camera registry.
- Run the same mosaic configuration logic.

### Critical hardware requirement

Do not assume every NVIDIA Jetson model supports identical hardware video encoding.

Specifically target Jetson Orin NX.

Inspect NVIDIA JetPack and multimedia capabilities before selecting GStreamer elements.

NVIDIA Orin NX and Orin Nano have different hardware video encoding capabilities.

Use NVIDIA-supported plugins only when they are actually available.

Do not hardcode unsupported GStreamer elements.

If hardware acceleration is unavailable, choose a documented software fallback when feasible.

Report unavailable capabilities clearly rather than silently failing.

**Do not promise identical video performance on Mac and Jetson. The goal is identical application behavior and API contracts, with platform-appropriate media implementations.**

---

# 5. ENTERPRISE PROJECT STRUCTURE

Create a professional folder structure similar to the following.

You may improve the structure where justified.

```text
ugv-jetson-gateway/
│
├── app/
│   │
│   ├── main.py
│   │
│   ├── core/
│   │   ├── config.py
│   │   ├── environment.py
│   │   ├── exceptions.py
│   │   ├── logging.py
│   │   └── security.py
│   │
│   ├── api/
│   │   ├── router.py
│   │   ├── health.py
│   │   ├── cameras.py
│   │   ├── camera_settings.py
│   │   ├── streams.py
│   │   └── mosaics.py
│   │
│   ├── schemas/
│   │   ├── camera.py
│   │   ├── stream.py
│   │   ├── mosaic.py
│   │   └── common.py
│   │
│   ├── services/
│   │   ├── camera_registry.py
│   │   ├── camera_manager.py
│   │   ├── camera_configuration.py
│   │   ├── camera_health.py
│   │   ├── stream_manager.py
│   │   ├── mosaic_manager.py
│   │   └── audit_service.py
│   │
│   ├── media/
│   │   ├── backends/
│   │   │   ├── base.py
│   │   │   ├── macos.py
│   │   │   ├── linux.py
│   │   │   └── jetson.py
│   │   │
│   │   ├── rtsp/
│   │   │   ├── proxy.py
│   │   │   ├── publisher.py
│   │   │   └── session.py
│   │   │
│   │   ├── mosaic/
│   │   │   ├── layouts.py
│   │   │   ├── compositor.py
│   │   │   └── pipeline.py
│   │   │
│   │   └── capabilities.py
│   │
│   ├── cameras/
│   │   ├── drivers/
│   │   │   ├── base.py
│   │   │   ├── onvif.py
│   │   │   ├── vendor.py
│   │   │   └── readonly_rtsp.py
│   │   │
│   │   └── discovery.py
│   │
│   ├── infrastructure/
│   │   ├── persistence/
│   │   ├── processes/
│   │   └── networking/
│   │
│   └── future/
│       └── README.md
│
├── config/
│   ├── config.json
│   ├── cameras.json
│   ├── mosaic.json
│   └── profiles.json
│
├── data/
│   └── .gitkeep
│
├── scripts/
│   ├── setup-mac.sh
│   ├── setup-jetson.sh
│   ├── start.sh
│   ├── stop.sh
│   ├── restart.sh
│   ├── check-dependencies.sh
│   └── verify-deployment.sh
│
├── deployments/
│   └── systemd/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
│
├── docs/
│   ├── API.md
│   ├── ARCHITECTURE.md
│   ├── CAMERA_CONFIGURATION.md
│   ├── MOSAIC.md
│   ├── NETWORK.md
│   ├── MAC_DEVELOPMENT.md
│   ├── JETSON_DEPLOYMENT.md
│   └── TROUBLESHOOTING.md
│
├── agent-notebook/
│   ├── README.md
│   ├── PROJECT_STATE.md
│   ├── DECISIONS.md
│   ├── COMPLETED_WORK.md
│   ├── PENDING_WORK.md
│   ├── KNOWN_ISSUES.md
│   ├── TEST_RESULTS.md
│   └── SESSION_LOG.md
│
├── AGENTS.md
├── README.md
├── pyproject.toml
├── requirements.txt
├── .gitignore
└── .env.example
```

The `future` folder should contain only documentation explaining how MAVLink, ESP32, networking, and other services will eventually integrate.

Do not implement those future modules now.

Avoid unnecessary empty directories or placeholder source files.

---

# 6. CAMERA REGISTRY

The Jetson must maintain the authoritative camera registry.

We have exactly six UGV cameras.

**Do not include the drone gimbal camera.**

Each camera must have:

- Permanent camera ID
- Customizable display name
- IP address
- RTSP port
- RTSP path
- Full RTSP URL
- Manufacturer, if known
- Camera model, if known
- Authentication configuration
- Connection status
- Configuration capabilities
- Available resolutions
- Available frame rates
- Available bitrates
- Available codecs
- Preferred video profile
- Backup direct RTSP endpoint
- Last successful connection time

### Important design rule

Camera ID must not depend on the IP address.

For example:

```text
CAM-001
CAM-002
CAM-003
CAM-004
CAM-005
CAM-006
```

Camera names must be customizable.

Example:

```text
CAM-001 → Front Camera
CAM-002 → Rear Camera
CAM-003 → Left Camera
CAM-004 → Right Camera
CAM-005 → Top Camera
CAM-006 → Auxiliary Camera
```

These are default names only.

### Camera registry JSON

Create:

`config/cameras.json`

Example structure:

```json
{
  "schema_version": 1,
  "cameras": [
    {
      "id": "CAM-001",
      "name": "Front Camera",
      "enabled": true,
      "connection": {
        "host": "192.168.144.101",
        "port": 554,
        "protocol": "rtsp",
        "path": "/"
      },
      "configuration": {
        "driver": "auto",
        "profile": "medium"
      }
    },
    {
      "id": "CAM-002",
      "name": "Rear Camera",
      "enabled": true,
      "connection": {
        "host": "192.168.144.102",
        "port": 554,
        "protocol": "rtsp",
        "path": "/"
      },
      "configuration": {
        "driver": "auto",
        "profile": "medium"
      }
    }
  ]
}
```

Generate all six camera records.

These addresses are configurable defaults.

Do not assume `/` is the correct RTSP path for every physical camera.

The operator must be able to change camera connection settings without editing application source code.

### Camera registry behavior

Changes should be:

1. Validated.
2. Applied safely.
3. Persisted.
4. Logged.
5. Returned to the GCS.

Use atomic writes for JSON configuration changes.

Maintain backups or version history of important configuration files.

Avoid storing usernames and passwords directly in committed JSON files.

Use environment variables or a protected local secrets file.

The API must not expose camera credentials in responses.

---

# 7. CAMERA CONFIGURATION MANAGEMENT

**All normal camera configuration requests must go through the Jetson API.**

Example:

```text
G30 Kotlin GCS
       |
       | Camera configuration request
       v
Jetson FastAPI
       |
       | Validate request
       v
Camera Configuration Service
       |
       | ONVIF / Vendor API
       v
Physical IP Camera
```

Support camera configuration where the hardware allows:

- Resolution
- FPS
- Bitrate
- Video codec
- Encoding profile
- Keyframe interval
- Stream profile selection

Additional camera-specific options may be supported through extensible drivers.

### Configuration rules

There are two different configuration types.

**A. Physical camera configuration**

Changes the actual camera encoder settings.

Use ONVIF or vendor-supported control APIs.

**B. Gateway output configuration**

Changes only the video delivered by Jetson.

May require decoding, scaling, and re-encoding.

These must be separate operations.

Never pretend that changing a Jetson output stream also changes the physical camera configuration.

### Required behavior

When the GCS requests a physical camera setting:

1. Validate camera ID.
2. Check camera availability.
3. Check supported capabilities.
4. Validate requested values.
5. Send configuration to the camera.
6. Read back actual settings when supported.
7. Persist confirmed configuration.
8. Log the operation.
9. Return a clear response.

If unsupported, return a meaningful error.

Do not silently transcode instead unless the request explicitly allows gateway processing.

### Configuration history

Maintain an audit history containing:

- Timestamp
- Camera ID
- Requested settings
- Previous settings, if known
- Confirmed settings, if known
- Success or failure
- Error information
- Request ID

SQLite is acceptable for this history.

Human-editable camera configuration should remain JSON-based.

---

# 8. CAMERA CAPABILITY DETECTION

Implement capability detection.

For cameras supporting ONVIF, retrieve supported video profiles and settings where possible.

For ordinary RTSP-only cameras, use stream probing to detect available stream properties.

### Important limitation

RTSP stream probing can identify properties such as:

- Codec
- Resolution
- Frame rate information
- Stream availability

It does not automatically reveal every configuration option the camera supports.

Do not invent camera capabilities.

Represent unsupported or unknown capabilities explicitly.

---

# 9. RTSP VIDEO GATEWAY

The Jetson must act as the primary video gateway.

The Kotlin GCS should normally receive individual camera streams from Jetson.

### Example endpoints

```text
rtsp://JETSON_HOST:8554/camera/CAM-001

rtsp://JETSON_HOST:8554/camera/CAM-002

rtsp://JETSON_HOST:8554/camera/CAM-003

rtsp://JETSON_HOST:8554/camera/CAM-004

rtsp://JETSON_HOST:8554/camera/CAM-005

rtsp://JETSON_HOST:8554/camera/CAM-006
```

These are desired logical endpoints.

Implement the paths consistently with the chosen RTSP server.

### Stream forwarding requirements

For individual cameras:

- Prefer remuxing or stream passthrough.
- Avoid unnecessary decoding.
- Avoid unnecessary re-encoding.
- Maintain low latency.
- Support H.264 where available.
- Handle stream interruptions.
- Automatically attempt reconnection.
- Track connection status.
- Stop unused expensive processing.
- Share upstream camera connections when practical.

Do not create a separate resource-intensive decoder for every viewer unless required.

### MediaMTX

Use MediaMTX as the RTSP distribution server.

The Python application controls the required stream processes and configuration.

MediaMTX is responsible for exposing RTSP endpoints to clients.

Use an appropriately pinned, supported MediaMTX release.

On macOS, select the correct binary for Intel or Apple Silicon.

On Jetson, use a compatible Linux ARM64 build.

Verify binary architecture and availability during setup.

Do not assume a macOS executable can run on Linux.

---

# 10. GCS DIRECT-CAMERA FALLBACK

The GCS must be able to access cameras directly when Jetson is unavailable.

The Jetson API should provide:

```json
{
  "camera_id": "CAM-001",
  "name": "Front Camera",
  "gateway_stream_url": "rtsp://192.168.144.20:8554/camera/CAM-001",
  "direct_stream_url": "rtsp://192.168.144.101:554/"
}
```

This is an illustrative response.

### Expected GCS behavior

```text
Try Jetson camera stream
           |
           v
       Connected?
        /     \
      YES      NO
       |        |
       v        v
    Display   Try direct
    video     camera RTSP
```

### Critical responsibility separation

**The Jetson server cannot implement the actual Kotlin player fallback by itself.**

The Jetson must expose enough information for the Kotlin GCS to implement fallback.

Create a clear integration specification and Kotlin-oriented examples.

If the Android GCS project is available in the workspace, inspect it and integrate only with permission and appropriate scope.

If the GCS source code is unavailable, do not claim the Android fallback is implemented.

### Offline configuration

The GCS must cache:

- Camera IDs
- Camera names
- Direct RTSP URLs
- Last known camera configuration
- Last known gateway endpoints

This allows fallback even when Jetson cannot provide `/api/cameras`.

Direct backup requires actual camera network reachability.

Do not assume the cameras are directly reachable over VPN or mesh without routing.

---

# 11. COCKPIT STREAMING REQUIREMENTS

The Kotlin cockpit should support at most two independent live camera streams.

The server must support:

### Single camera

```text
CAM-001
```

### Dual camera

```text
CAM-001 + CAM-002
```

Other combinations must also work:

```text
CAM-001 + CAM-006
CAM-003 + CAM-004
CAM-002 + CAM-005
```

The GCS selects cameras by their permanent IDs.

Names are display-only labels and must not be used as technical identifiers.

Individual camera streams should normally be forwarded without transcoding.

---

# 12. MOSAIC STREAMING ENGINE

This is a major requirement.

The Jetson must support configurable mosaic streaming.

### Supported camera counts

- 1 camera
- 2 cameras
- 3 cameras
- 4 cameras
- 5 cameras
- 6 cameras

The operator can choose any combination of the six registered cameras.

Examples:

```text
CAM-001 + CAM-003 + CAM-005
```

or:

```text
CAM-002 + CAM-004 + CAM-006
```

### Layout support

Implement sensible default layouts.

**Single camera**

```text
+-----------------------+
|                       |
|       Camera 1        |
|                       |
+-----------------------+
```

**Two cameras**

```text
+-----------+-----------+
|           |           |
| Camera 1  | Camera 2  |
|           |           |
+-----------+-----------+
```

**Three cameras**

```text
+-----------------------+
|        Camera 1       |
+-----------+-----------+
| Camera 2  | Camera 3  |
+-----------+-----------+
```

**Four cameras**

```text
+-----------+-----------+
| Camera 1  | Camera 2  |
+-----------+-----------+
| Camera 3  | Camera 4  |
+-----------+-----------+
```

**Six cameras**

```text
+--------+--------+--------+
| Cam 1  | Cam 2  | Cam 3  |
+--------+--------+--------+
| Cam 4  | Cam 5  | Cam 6  |
+--------+--------+--------+
```

For five cameras, implement a reasonable preset.

### Custom layouts

Allow explicit tile coordinates and dimensions.

Each tile should support:

- Camera ID
- X position
- Y position
- Width
- Height
- Scaling mode
- Crop/fit behavior
- Z-order, if supported
- Optional visibility

Validate that tile dimensions and positions fit within the mosaic canvas.

Support preset layouts and custom layouts.

---

# 13. PER-CAMERA MOSAIC CONFIGURATION

The operator must be able to customize each camera included in a mosaic.

Support:

- Camera selection
- Source video profile
- Preferred source resolution
- Preferred source FPS
- Preferred bitrate
- Tile width
- Tile height
- Scaling method
- Crop/fit mode

Also support mosaic-wide settings:

- Output resolution
- Output FPS
- Output bitrate
- Output codec
- Output stream name
- Layout mode

### Important engineering distinction

Per-camera settings may refer to:

1. Physical camera encoder settings.
2. Selected camera substream/profile.
3. Gateway processing settings.
4. Tile dimensions.

These are not interchangeable.

For example, changing the tile width does not change the camera's original resolution.

Also, a single encoded mosaic has one final output FPS and output resolution.

The implementation must reflect these differences clearly.

### Example mosaic request

```json
{
  "layout": "custom",
  "output": {
    "width": 1920,
    "height": 1080,
    "fps": 20,
    "bitrate_kbps": 3000,
    "codec": "h264"
  },
  "tiles": [
    {
      "camera_id": "CAM-001",
      "x": 0,
      "y": 0,
      "width": 1920,
      "height": 540,
      "source_profile": "high",
      "preferred_source_fps": 20,
      "scaling": "fit"
    },
    {
      "camera_id": "CAM-002",
      "x": 0,
      "y": 540,
      "width": 960,
      "height": 540,
      "source_profile": "medium",
      "preferred_source_fps": 15,
      "scaling": "fit"
    },
    {
      "camera_id": "CAM-003",
      "x": 960,
      "y": 540,
      "width": 960,
      "height": 540,
      "source_profile": "low",
      "preferred_source_fps": 15,
      "scaling": "fit"
    }
  ]
}
```

The API should return the requested configuration, effective configuration, and any unsupported or adjusted settings.

### Mosaic RTSP endpoint

For the first implementation:

```text
rtsp://JETSON_HOST:8554/mosaic
```

The Jetson publishes the mosaic as a single RTSP stream.

Do not assume the stream can be reconfigured without playback interruption.

Implement proper lifecycle management and notify clients when reconnection is required.

### Multiple operator considerations

Initially, one active shared mosaic configuration is acceptable.

Document this behavior.

Avoid silently allowing one GCS client to overwrite another operator's mosaic without appropriate concurrency control.

Use a configuration revision, owner/session mechanism, or another reasonable design.

---

# 14. VIDEO PIPELINE REQUIREMENTS

Create a modular media backend interface.

Conceptually:

```python
class MediaBackend:
    def start_camera_stream(self, camera_id):
        ...

    def stop_camera_stream(self, camera_id):
        ...

    def create_mosaic(self, config):
        ...

    def update_mosaic(self, config):
        ...

    def stop_mosaic(self):
        ...

    def get_stream_metrics(self, stream_id):
        ...
```

Design proper asynchronous behavior and process supervision where needed.

### macOS implementation

Use a supported FFmpeg or GStreamer software pipeline.

Mosaic composition must work with real video.

Do not return fake mosaic URLs.

### Jetson implementation

Prefer supported NVIDIA multimedia processing where available.

Potential technologies include:

- GStreamer
- NVIDIA video decoding plugins
- NVIDIA conversion/composition plugins
- Jetson-compatible encoders
- DeepStream where justified

Do not introduce DeepStream merely because it is available.

Use the simplest reliable implementation that meets the requirements.

Inspect installed GStreamer plugins and build compatible pipelines.

### Important requirements

- No shell command injection.
- No uncontrolled subprocess spawning.
- No orphaned FFmpeg/GStreamer processes.
- Graceful start and stop.
- Timeouts.
- Restart policies.
- Resource cleanup.
- Structured error reporting.
- Resource usage monitoring.

The system should reject unsupported or excessive mosaic configurations instead of exhausting Jetson resources.

---

# 15. VIDEO METRICS

The GCS must be able to display camera information such as:

```text
FRONT CAMERA

LIVE
1280 × 720
20 FPS
H.264
1.5 Mbps
```

Expose:

- Connection status
- Detected codec
- Detected resolution
- Detected or measured FPS
- Estimated or measured bitrate
- Last frame timestamp
- Stream uptime
- Reconnection count
- Error information

### Important

Distinguish:

- Configured FPS
- Actual measured FPS
- Configured bitrate
- Actual measured bitrate

Do not show requested values as measured values.

Metrics that cannot be accurately obtained should be returned as `null` or marked unavailable.

Do not invent latency measurements.

End-to-end video latency requires an appropriate measurement method.

---

# 16. REST API DESIGN

All camera control must be accessible through a single FastAPI application.

Default development endpoint:

```text
http://localhost:8080
```

On Jetson:

```text
http://192.168.144.20:8080
```

or:

```text
http://10.10.0.20:8080
```

Both should reach the same application when network configuration permits.

Use API versioning.

Base path:

```text
/api/v1
```

### Camera APIs

```http
GET /api/v1/cameras
```

Get all six registered cameras.

```http
GET /api/v1/cameras/{camera_id}
```

Get camera details.

```http
PATCH /api/v1/cameras/{camera_id}
```

Update camera metadata or connection settings.

```http
GET /api/v1/cameras/{camera_id}/capabilities
```

Get camera capabilities.

```http
GET /api/v1/cameras/{camera_id}/settings
```

Get effective camera settings.

```http
PUT /api/v1/cameras/{camera_id}/settings
```

Change physical camera settings where supported.

```http
GET /api/v1/cameras/{camera_id}/status
```

Get camera health.

### Stream APIs

```http
GET /api/v1/streams
```

List managed streams.

```http
GET /api/v1/streams/{camera_id}
```

Get individual camera stream information.

```http
POST /api/v1/streams/{camera_id}/start
```

Start or activate a managed stream.

```http
POST /api/v1/streams/{camera_id}/stop
```

Stop a managed stream when safe.

```http
GET /api/v1/streams/{camera_id}/metrics
```

Get stream metrics.

### Mosaic APIs

```http
GET /api/v1/mosaic
```

Get current mosaic configuration.

```http
PUT /api/v1/mosaic
```

Create or replace mosaic configuration.

```http
POST /api/v1/mosaic/start
```

Start mosaic streaming.

```http
POST /api/v1/mosaic/stop
```

Stop mosaic streaming.

```http
GET /api/v1/mosaic/status
```

Get mosaic status.

```http
GET /api/v1/mosaic/layouts
```

Get supported layouts.

### System APIs

```http
GET /api/v1/health
```

Basic server health.

```http
GET /api/v1/system/capabilities
```

Get detected platform and media capabilities.

```http
GET /api/v1/system/status
```

Get server status.

### Audit APIs

```http
GET /api/v1/audit/camera-configurations
```

Get camera configuration history.

Protect sensitive administrative endpoints.

Implement request validation, consistent error responses, and appropriate authentication.

Expose automatically generated OpenAPI documentation through FastAPI.

### API documentation

Create:

```text
docs/API.md
```

Include every endpoint with:

- HTTP method
- URL
- Purpose
- Request parameters
- Request JSON
- Response JSON
- Error responses
- Authentication requirement
- Example curl command

Also provide OpenAPI JSON.

Do not document endpoints as implemented unless they actually work.

---

# 17. SECURITY REQUIREMENTS

Even though this system runs on private radio networks, do not assume every connected device is trustworthy.

Implement:

- API authentication
- Input validation
- Camera ID validation
- RTSP URL validation
- Safe subprocess execution
- Request timeouts
- Protected credentials
- Audit logs
- Restricted configuration updates

Use token-based authentication or another lightweight mechanism appropriate for the GCS.

Use constant-time token comparison where applicable.

Do not commit tokens or camera passwords into Git.

Do not print secrets in logs.

Keep default network exposure conservative.

If plain HTTP is used on the isolated rover network, document its risks and provide a migration path to HTTPS.

Avoid exposing unauthenticated configuration APIs over VPN or public interfaces.

---

# 18. MAC DEVELOPMENT SETUP

Create:

```text
scripts/setup-mac.sh
```

This script should:

1. Detect macOS architecture.
2. Verify or install Python dependencies.
3. Create `.venv`.
4. Install Python requirements.
5. Check FFmpeg.
6. Check GStreamer if used.
7. Install or configure MediaMTX.
8. Create required directories.
9. Validate JSON configuration.
10. Run dependency checks.
11. Report setup status.

Use Homebrew when appropriate.

Do not perform destructive package operations without clear warnings.

Create:

```text
scripts/start.sh
```

The start script should:

- Detect the platform.
- Activate the correct virtual environment.
- Load configuration.
- Verify dependencies.
- Start required services.
- Start the API.
- Report URLs.
- Handle failures clearly.

Expected development workflow:

```bash
git clone <repository>
cd ugv-jetson-gateway

bash scripts/setup-mac.sh
bash scripts/start.sh
```

The system should also be testable through:

```bash
pytest
```

---

# 19. JETSON DEPLOYMENT — CRITICAL REQUIREMENT

I want to develop on my Mac and later transfer the project to NVIDIA Jetson Orin NX.

**I do not want to manually modify Python application source code to make it run on Jetson.**

Create:

```text
scripts/setup-jetson.sh
```

This must be a real, working Linux Jetson setup script.

### Required responsibilities

1. Verify Linux ARM64 architecture.
2. Verify NVIDIA Jetson hardware.
3. Detect the installed JetPack/L4T release.
4. Detect available Python versions.
5. Create a Linux-compatible `.venv`.
6. Install compatible Python dependencies.
7. Detect FFmpeg.
8. Detect GStreamer.
9. Detect NVIDIA-specific multimedia plugins.
10. Install or configure a compatible MediaMTX binary.
11. Configure application directories.
12. Validate all JSON files.
13. Configure persistent logging.
14. Prepare systemd service files.
15. Run deployment validation.
16. Print detected capabilities.
17. Explain any remaining hardware-specific setup requirements.

### NVIDIA compatibility

Do not blindly install arbitrary versions of:

- CUDA
- JetPack
- TensorRT
- NVIDIA drivers
- DeepStream

These components must be compatible with the installed JetPack version.

Do not overwrite the Jetson's BSP or NVIDIA multimedia libraries.

Use existing JetPack packages and supported package repositories when possible.

If a required NVIDIA component is absent, report it and provide clear instructions.

### Deployment command

The desired deployment workflow is:

```bash
git clone <repository>

cd ugv-jetson-gateway

bash scripts/setup-jetson.sh
```

After setup:

```bash
bash scripts/start.sh
```

Or through systemd:

```bash
sudo systemctl start ugv-jetson-gateway
```

Create the appropriate service file and installation procedure.

### Important expectation

One-command installation means automating everything safely possible.

It does not mean pretending that hardware setup, network routing, JetPack compatibility, and camera-specific configuration never require verification.

The script must identify and clearly report any manual prerequisites.

Do not claim Jetson deployment has been tested unless it has actually been run on Jetson hardware.

---

# 20. JSON CONFIGURATION DESIGN

Keep configuration files separate by responsibility.

### `config/config.json`

General server configuration:

```json
{
  "server": {
    "host": "0.0.0.0",
    "port": 8080
  },
  "environment": {
    "mode": "auto",
    "media_backend": "auto"
  },
  "streaming": {
    "rtsp_port": 8554,
    "transport": "tcp",
    "default_codec": "h264"
  }
}
```

### `config/cameras.json`

Six camera definitions.

### `config/mosaic.json`

Default mosaic configuration:

```json
{
  "enabled": true,
  "layout": "grid_3x2",
  "output": {
    "width": 1920,
    "height": 1080,
    "fps": 15,
    "bitrate_kbps": 3000,
    "codec": "h264"
  },
  "camera_ids": [
    "CAM-001",
    "CAM-002",
    "CAM-003",
    "CAM-004",
    "CAM-005",
    "CAM-006"
  ]
}
```

### `config/profiles.json`

Default streaming profiles:

```json
{
  "profiles": {
    "low": {
      "width": 960,
      "height": 540,
      "fps": 10,
      "bitrate_kbps": 500
    },
    "medium": {
      "width": 1280,
      "height": 720,
      "fps": 15,
      "bitrate_kbps": 1500
    },
    "high": {
      "width": 1920,
      "height": 1080,
      "fps": 20,
      "bitrate_kbps": 3500
    }
  }
}
```

These are suggested defaults, not guaranteed encoder capabilities.

Validate them against the selected media backend.

### Configuration management rules

- Never hardcode camera IP addresses in service logic.
- Never hardcode camera names in service logic.
- Never hardcode RTSP paths in service logic.
- Never hardcode environment-specific filesystem paths.
- Never hardcode platform-specific multimedia binaries.
- Validate JSON using Pydantic models.
- Provide useful validation errors.
- Support controlled configuration reloads.
- Persist runtime changes safely.
- Keep secrets outside committed JSON files.

---

# 21. TESTING REQUIREMENTS

Implement automated tests.

### Unit tests

Cover:

- Camera registry
- Camera ID validation
- Camera renaming
- JSON configuration
- Camera capability handling
- Mosaic layout validation
- Stream state transitions
- API request validation
- Authentication

### Integration tests

Cover:

- FastAPI endpoints
- MediaMTX integration
- FFmpeg/GStreamer pipeline execution
- RTSP stream publication
- Camera disconnections
- Camera reconnections
- Configuration persistence
- Audit logging

### End-to-end tests

Use virtual RTSP cameras.

The system must support testing without physical cameras.

Provide test utilities to generate six virtual camera feeds.

Use video files or synthetic test patterns.

Do not depend on public RTSP servers for automated tests.

### Required practical test cases

1. Register six cameras.
2. Start Camera 1 stream.
3. Start Camera 2 stream.
4. Verify two independent streams.
5. Create a three-camera mosaic.
6. Verify its output dimensions.
7. Create a six-camera mosaic.
8. Verify the output stream.
9. Change mosaic configuration.
10. Disconnect one camera.
11. Verify recovery behavior.
12. Restart the server.
13. Verify persisted configuration.
14. Verify invalid requests are rejected.
15. Verify protected endpoints require authentication.

Where possible, inspect real RTSP output using `ffprobe` or equivalent tooling.

Do not accept an API response containing a stream URL as proof that actual video is being published.

---

# 22. RESOURCE MANAGEMENT

The target hardware is an embedded robotics computer.

Resource efficiency matters.

Implement:

- Stream lifecycle management
- Bounded retry policies
- Controlled worker processes
- Camera timeout handling
- Worker health monitoring
- Resource cleanup
- Graceful shutdown
- CPU monitoring
- Memory monitoring
- Media process monitoring

Avoid unnecessary transcoding for single-camera RTSP forwarding.

For mosaic composition, select compatible decoding, scaling, compositing, and encoding components.

Provide configurable resource limits.

Do not start six full-resolution transcoders automatically when no GCS client needs them.

The implementation should be able to report when a requested video configuration exceeds available capabilities.

---

# 23. FUTURE EXPANSION

This project will later include:

- MAVLink gateway
- Matek H743 communication
- ESP32 pan/tilt control
- Network failover
- GR03 connectivity monitoring
- Mesh connectivity monitoring
- VPN connectivity
- Vehicle health monitoring
- Additional robotics services

Do not implement these now.

However, keep clean architectural boundaries.

For example:

```text
app/
  api/
  services/
  media/
  cameras/
  infrastructure/
```

Future modules should be addable without rewriting camera management.

Camera streaming must not depend on MAVLink being connected.

MAVLink failures must not bring down camera services.

Camera pipeline failures must not crash the complete gateway API.

---

# 24. AGENT NOTEBOOK — MANDATORY

Create:

```text
agent-notebook/
```

This directory will preserve project knowledge between coding agents.

Future development may be performed by:

- Claude Code
- OpenAI Codex
- ChatGPT
- Cursor
- Other coding agents

Every agent must be able to understand the project without requiring the original conversation.

### Required files

**`agent-notebook/README.md`**

Explain how agents should use the notebook.

**`agent-notebook/PROJECT_STATE.md`**

Document:

- Current architecture
- Current implementation
- Working modules
- Incomplete modules
- Current development phase
- Important dependencies

**`agent-notebook/DECISIONS.md`**

Record important technical decisions and why they were made.

**`agent-notebook/COMPLETED_WORK.md`**

Record completed features with verification evidence.

**`agent-notebook/PENDING_WORK.md`**

Record remaining implementation tasks.

**`agent-notebook/KNOWN_ISSUES.md`**

Record bugs, limitations, and unresolved risks.

**`agent-notebook/TEST_RESULTS.md`**

Record actual executed tests and results.

**`agent-notebook/SESSION_LOG.md`**

Maintain a chronological development history.

### Important rule

Do not claim functionality is complete merely because source code was generated.

Mark work complete only when implementation and relevant tests have been verified.

Clearly distinguish:

- Implemented
- Tested on macOS
- Tested on generic Linux
- Tested on actual Jetson
- Not tested
- Blocked by hardware availability

---

# 25. AGENTS.MD — MANDATORY GUARDRAILS

Create a root-level:

```text
AGENTS.md
```

This is the main entry point for every future coding agent.

It must instruct agents to read the following before modifying code:

1. `README.md`
2. `docs/ARCHITECTURE.md`
3. `agent-notebook/PROJECT_STATE.md`
4. `agent-notebook/DECISIONS.md`
5. `agent-notebook/KNOWN_ISSUES.md`
6. `agent-notebook/PENDING_WORK.md`

### Agent rules

Every coding agent must:

- Understand the existing architecture before changing files.
- Preserve established API contracts unless changes are documented.
- Avoid unnecessary rewrites.
- Follow existing project conventions.
- Maintain macOS and Jetson compatibility.
- Keep hardware-specific code isolated.
- Update tests for modified behavior.
- Update API documentation when endpoints change.
- Update the agent notebook after meaningful work.
- Record unresolved issues.
- Avoid introducing unnecessary dependencies.
- Never silently replace working features with mocks.
- Never claim untested functionality is verified.
- Never expose secrets in source code or logs.

After every substantial development session, update:

```text
agent-notebook/PROJECT_STATE.md
agent-notebook/COMPLETED_WORK.md
agent-notebook/PENDING_WORK.md
agent-notebook/SESSION_LOG.md
```

Update other files when relevant.

---

# 26. DOCUMENTATION REQUIREMENTS

Provide documentation that a beginner can understand.

### `README.md`

Explain:

- What the system does
- Supported platforms
- Requirements
- Installation
- Startup
- API access
- Camera configuration
- RTSP URLs
- Mosaic configuration
- Testing

### `docs/API.md`

Complete API reference.

### `docs/ARCHITECTURE.md`

Explain system modules and data flow.

### `docs/CAMERA_CONFIGURATION.md`

Explain camera registration and setting changes.

### `docs/MOSAIC.md`

Explain layouts, per-camera settings, and output streams.

### `docs/NETWORK.md`

Explain GR03, mesh, and VPN addressing assumptions.

### `docs/MAC_DEVELOPMENT.md`

Explain macOS installation and testing.

### `docs/JETSON_DEPLOYMENT.md`

Explain deployment to NVIDIA Jetson Orin NX.

### `docs/TROUBLESHOOTING.md`

Explain common problems and their solutions.

All documentation must reflect the actual implementation.

---

# 27. IMPLEMENTATION ORDER

Develop the system in the following order.

### Phase 1 — Foundation

Implement:

- Project structure
- Environment detection
- JSON configuration
- Logging
- FastAPI server
- Health endpoints
- Authentication
- Camera registry
- Persistent storage

### Phase 2 — Camera Management

Implement:

- Six camera definitions
- Camera status monitoring
- Camera capability detection
- ONVIF integration
- Camera configuration
- Configuration history

### Phase 3 — RTSP Gateway

Implement:

- MediaMTX integration
- Camera stream forwarding
- Individual RTSP endpoints
- Stream monitoring
- Automatic recovery
- Stream metadata

### Phase 4 — Mosaic Engine

Implement:

- Mosaic layouts
- Custom tile positioning
- Per-camera source configuration
- Mosaic output profiles
- RTSP mosaic publishing
- Pipeline lifecycle management

### Phase 5 — Cross-Platform Support

Implement and verify:

- macOS software media backend
- Generic Linux media backend
- Jetson-specific media backend
- Runtime capability detection
- Compatible backend selection

### Phase 6 — Deployment

Implement:

- Mac setup script
- Jetson setup script
- Start/stop/restart scripts
- Systemd service
- Deployment verification
- Logging and recovery

### Phase 7 — Final Testing and Documentation

Execute:

- Unit tests
- Integration tests
- RTSP playback tests
- Mosaic tests
- Configuration persistence tests
- Failure handling tests

Update all documentation and agent notebook files.

---

# 28. FINAL ACCEPTANCE CRITERIA

The project is ready for initial hardware deployment when the following are true.

### API

- FastAPI starts successfully.
- Camera APIs work.
- Mosaic APIs work.
- Request validation works.
- Authentication works.
- OpenAPI documentation is available.

### Cameras

- Six cameras are represented in the registry.
- Camera IDs remain stable.
- Camera names are customizable.
- Camera settings persist.
- Capability limitations are reported accurately.
- Configuration history is recorded.

### Streaming

- Individual RTSP streams are published.
- Single-camera forwarding works.
- Two independent camera streams work.
- Three-camera mosaic works.
- Six-camera mosaic works.
- Mosaic output is one RTSP stream.
- Stream recovery is implemented.
- Video metrics are available where measurable.

### Cross-platform

- The same Python application source works on macOS and supported Jetson Linux environments.
- Platform-specific media handling is isolated.
- Setup scripts install appropriate dependencies.
- Jetson-specific features are detected rather than assumed.
- Unsupported hardware features produce clear errors or documented fallbacks.

### Deployment

- `setup-mac.sh` works on the available Mac development environment.
- `start.sh` launches the required services.
- `setup-jetson.sh` is provided and validated as far as possible without hardware.
- systemd service files are provided.
- No manual Python source-code rewrite should be required for deployment.

### Documentation

- README is complete.
- API documentation is complete.
- Architecture documentation is complete.
- Deployment documentation is complete.
- Agent notebook is maintained.
- `AGENTS.md` exists.

---

# 29. IMPORTANT DEVELOPMENT RULES

Follow these rules throughout implementation.

**Rule 1:** This is a real application. Do not substitute mock functionality for real streaming functionality in production paths.

**Rule 2:** Mock services are allowed only for explicit development and testing scenarios.

**Rule 3:** All camera IDs, names, IP addresses, and RTSP paths must be configurable.

**Rule 4:** Keep camera configuration separate from video stream configuration.

**Rule 5:** Do not unnecessarily transcode individual camera streams.

**Rule 6:** Mosaic composition must generate actual playable video.

**Rule 7:** Keep the Kotlin GCS independent of Jetson-specific implementation details.

**Rule 8:** Keep API contracts stable across macOS and Jetson.

**Rule 9:** Do not hardcode development-machine paths.

**Rule 10:** All startup and installation scripts must provide meaningful failure messages.

**Rule 11:** Do not modify Linux network settings automatically without explicit authorization.

**Rule 12:** Do not assume GR03, mesh, or VPN routing is operational without connectivity tests.

**Rule 13:** Do not mix MAVLink or ESP32 implementation into the camera module.

**Rule 14:** Do not create documentation claiming unsupported functionality works.

**Rule 15:** Maintain the agent notebook continuously.

---

# 30. START IMPLEMENTATION NOW

Begin by inspecting the current workspace.

If an existing project is present, inspect it before creating or changing files.

Preserve existing useful code.

Then:

1. Create the project foundation.
2. Implement the camera registry.
3. Implement camera management APIs.
4. Implement the RTSP gateway.
5. Implement mosaic streaming.
6. Implement configuration persistence.
7. Implement environment-specific media backends.
8. Implement installation and startup scripts.
9. Write automated tests.
10. Execute all tests possible in the current environment.
11. Fix discovered failures.
12. Write complete documentation.
13. Create and update the agent notebook.
14. Prepare Jetson deployment.

Do not stop at the planning stage.

Deliver a working macOS development implementation that is architecturally ready for NVIDIA Jetson Orin NX deployment.

### FINAL REPORT FORMAT

At the end of your implementation, provide:

**1. Implemented features**

State what actually works.

**2. Project structure**

Show the important folders.

**3. Installation commands**

Show the exact commands required on macOS.

**4. Startup commands**

Show how to run the application.

**5. API access**

Show the FastAPI address and documentation URL.

**6. RTSP endpoints**

Show how to access individual streams and mosaics.

**7. Test results**

Report tests actually executed and whether they passed.

**8. Jetson readiness**

Explain what has been prepared and what still requires real Jetson hardware testing.

**9. Known limitations**

List unresolved issues.

**10. Next steps**

Explain what should be tested first when the Jetson Orin NX arrives.

### MOST IMPORTANT GOAL

**Build once on macOS, deploy the same application source to Jetson Orin NX, and let configuration files, installation scripts, and media backend detection handle the platform differences.**

Avoid manual source-code changes during deployment.

The final system should be modular, reliable, well-documented, and ready for future MAVLink, ESP32, and network-management integrations.

**NOW START IMPLEMENTING THE PROJECT.**