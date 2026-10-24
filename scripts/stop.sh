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
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    if ! kill -0 "$pid" 2>/dev/null; then
      return
    fi
    sleep 0.3
  done
  kill -9 "$pid" 2>/dev/null || true
}

if [[ ! -f data/gateway.pid && ! -d data/run ]]; then
  echo "No background gateway pid file. If it is running in a terminal, stop it with Ctrl-C." >&2
  exit 1
fi

if [[ -f data/gateway.pid ]]; then
  stop_pid "$(cat data/gateway.pid)"
  rm -f data/gateway.pid
fi

if [[ -d data/run ]]; then
  for pid_file in data/run/*.pid; do
    [[ -e "$pid_file" ]] || continue
    stop_pid "$(tr -d '[:space:]' < "$pid_file")"
    rm -f "$pid_file"
  done
fi
echo "Gateway stopped."
