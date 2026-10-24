#!/usr/bin/env bash
# Compile the hardware-independent RCWM core. This does not flash an ESP32.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
g++ -std=c++17 -Wall -Wextra -I "$ROOT/firmware/esp32/include" \
  "$ROOT/firmware/host/test_core.cpp" -o "$ROOT/firmware/host/test_core"
"$ROOT/firmware/host/test_core"
rm -f "$ROOT/firmware/host/test_core"
echo "Firmware host tests passed."
