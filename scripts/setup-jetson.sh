#!/usr/bin/env bash
# Prepare a Jetson Orin NX. This script does not install CUDA, JetPack, or drivers.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "setup-jetson.sh must be run on the Jetson. It was not executed here." >&2
  exit 1
fi

if [[ "$(uname -m)" != "aarch64" ]]; then
  echo "Expected aarch64. Found $(uname -m)." >&2
  exit 1
fi

model=""
if [[ -f /proc/device-tree/model ]]; then
  model="$(tr -d '\000' < /proc/device-tree/model || true)"
fi
if [[ ! -f /etc/nv_tegra_release && "$model" != *Jetson* && "$model" != *jetson* ]]; then
  echo "This Linux machine does not look like an NVIDIA Jetson." >&2
  echo "ARM64 by itself is not enough. Refusing to continue." >&2
  exit 1
fi

echo "Jetson model: ${model:-unknown}"
if [[ -f /etc/nv_tegra_release ]]; then
  echo "L4T: $(head -n 1 /etc/nv_tegra_release)"
else
  echo "L4T release file /etc/nv_tegra_release was not found."
fi

if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v gst-launch-1.0 >/dev/null 2>&1; then
  echo "FFmpeg and GStreamer are required." >&2
  echo "Install the existing JetPack packages, for example:" >&2
  echo "  sudo apt-get update" >&2
  echo "  sudo apt-get install -y ffmpeg gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-libav" >&2
  echo "Do not install a different CUDA, TensorRT, or JetPack release from this script." >&2
  exit 1
fi

if command -v gst-inspect-1.0 >/dev/null 2>&1; then
  for element in nvv4l2decoder nvv4l2h264enc nvvidconv; do
    if gst-inspect-1.0 "$element" >/dev/null 2>&1; then
      echo "GStreamer element available: $element"
    else
      echo "GStreamer element missing: $element"
    fi
  done
fi

PYTHON=""
for candidate in python3.12 python3.11 python3.10 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    version="$("$candidate" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
    major="${version%%.*}"
    minor="${version#*.}"
    if [[ "$major" -gt 3 || ( "$major" -eq 3 && "$minor" -ge 10 ) ]]; then
      PYTHON="$candidate"
      break
    fi
  fi
done
if [[ -z "$PYTHON" ]]; then
  echo "Python 3.10 or newer is required. Use the Jetson system packages rather than replacing JetPack." >&2
  exit 1
fi

if [[ ! -x .venv/bin/python ]]; then
  if ! "$PYTHON" -m venv .venv; then
    echo "Could not create a virtual environment. Install python3-venv for this Python and run the script again." >&2
    exit 1
  fi
fi

# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"

VERSION="$(python -c 'import json; print(json.load(open("config/config.json"))["streaming"]["media_server_version"])')"
DEST="vendor/mediamtx"
mkdir -p "$DEST"
if [[ ! -x "$DEST/mediamtx" ]]; then
  archive="$(mktemp -d)/mediamtx.tar.gz"
  url="https://github.com/bluenviron/mediamtx/releases/download/${VERSION}/mediamtx_${VERSION}_linux_arm64.tar.gz"
  echo "Downloading MediaMTX ${VERSION} (linux_arm64)"
  curl -fL --retry 3 --retry-delay 2 "$url" -o "$archive"
  tar -xzf "$archive" -C "$DEST"
  chmod 755 "$DEST/mediamtx"
  rm -rf "$(dirname "$archive")"
fi
file "$DEST/mediamtx"

mkdir -p data/logs data/backups
if [[ ! -f config/secrets.json ]]; then
  cp config/secrets.example.json config/secrets.json
  chmod 600 config/secrets.json
fi

UNIT="deployments/systemd/ugv-jetson-gateway.generated.service"
sed "s#__ROOT__#${ROOT}#g" deployments/systemd/ugv-jetson-gateway.service > "$UNIT"
echo "Generated systemd unit: $UNIT"
if [[ "$(id -u)" -eq 0 ]]; then
  cp "$UNIT" /etc/systemd/system/ugv-jetson-gateway.service
  systemctl daemon-reload
  systemctl enable ugv-jetson-gateway.service
  echo "systemd service enabled. Start it with: systemctl start ugv-jetson-gateway"
else
  echo "Not running as root. To install the service:"
  echo "  sudo cp $UNIT /etc/systemd/system/ugv-jetson-gateway.service"
  echo "  sudo systemctl daemon-reload"
  echo "  sudo systemctl enable --now ugv-jetson-gateway"
fi

python - << 'PY'
import importlib
for name in ("pymavlink", "serial"):
    importlib.import_module(name)
print("pymavlink and pyserial import")
PY
python -m app.tools.validate_config
python -m app.tools.doctor
echo "Jetson setup finished on this machine."
echo "Network addresses are not configured by this script."
echo "MAVLink listens on UDP 14550 when mavlink.enabled is true."
echo "Set mavlink.flight_controller.serial_port and rcwm.serial_port before attaching a Matek or ESP32."
echo "This script does not open a serial device and does not change interface addresses."
echo "The service user needs access to the UART, for example: sudo usermod -aG dialout \$USER"
echo "ESP32 firmware is built separately. See docs/ESP32_FIRMWARE.md."
echo "Confirm camera reachability before enabling health checks in config/config.json."
echo "Leave rcwm.allow_hardware_motion false until the emergency stop and pin map are confirmed."
