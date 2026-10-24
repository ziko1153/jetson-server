#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "Repository: $ROOT"
if [[ -x .venv/bin/python ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
  python -m app.tools.doctor || true
else
  echo "Virtual environment is missing."
fi

if [[ "$(uname -s)" == "Linux" && -f /etc/nv_tegra_release ]]; then
  echo "Jetson L4T file is present. This script cannot prove the video path until streams are played on the vehicle."
elif [[ "$(uname -s)" == "Darwin" ]]; then
  echo "This is macOS. Jetson deployment has not been executed on hardware."
else
  echo "This is not a detected Jetson. Do not treat this run as a Jetson deployment test."
fi

PORT="8080"
if [[ -x .venv/bin/python ]]; then
  PORT="$(python -c 'from app.core.config import load_settings; print(load_settings().server.port)')"
fi
if curl -fsS "http://127.0.0.1:${PORT}/api/v1/health" >/dev/null 2>&1; then
  echo "Health endpoint responded on port ${PORT}."
else
  echo "Health endpoint is not responding. Start the gateway before expecting a live health check."
fi
