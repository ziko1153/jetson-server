#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

stop_pid() {
  local pid="$1"
  if [[ -z "$pid" ]] || ! kill -0 "$pid" 2>/dev/null; then
    return
  fi
  kill "$pid" 2>/dev/null || true
  for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
    if ! kill -0 "$pid" 2>/dev/null; then
      return
    fi
    sleep 0.3
  done
  kill -9 "$pid" 2>/dev/null || true
}

if [[ ! -f data/simulation.pid && ! -f data/gateway.pid && ! -d data/run ]]; then
  echo "No simulation is running." >&2
  exit 1
fi

if [[ -f data/simulation.pid ]]; then
  stop_pid "$(tr -d '[:space:]' < data/simulation.pid)"
  rm -f data/simulation.pid
fi

if [[ -f data/gateway.pid ]]; then
  stop_pid "$(tr -d '[:space:]' < data/gateway.pid)"
  rm -f data/gateway.pid
fi

if [[ -d data/run ]]; then
  for pid_file in data/run/*.pid; do
    [[ -e "$pid_file" ]] || continue
    stop_pid "$(tr -d '[:space:]' < "$pid_file")"
    rm -f "$pid_file"
  done
fi

if [[ -x .venv/bin/python ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
  python -m app.tools.simulation restore-sitl || true
fi

echo "Simulation stopped."
