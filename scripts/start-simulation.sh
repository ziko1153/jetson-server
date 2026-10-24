#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -x .venv/bin/python ]]; then
  echo "No virtual environment. Run scripts/setup-mac.sh or scripts/setup-jetson.sh first." >&2
  exit 1
fi

# shellcheck disable=SC1091
source .venv/bin/activate
python -m app.tools.doctor --require-runtime >/dev/null
echo "This script does not change network interfaces."

detach=0
cmd=(python -m app.tools.simulation run)
for arg in "$@"; do
  if [[ "$arg" == "--detach" ]]; then
    detach=1
  else
    cmd+=("$arg")
  fi
done

restore_sitl() {
  python -m app.tools.simulation restore-sitl || true
}

if [[ "$detach" -eq 1 ]]; then
  mkdir -p data/logs
  : > data/logs/simulation.log
  nohup "${cmd[@]}" >> data/logs/simulation.log 2>&1 &
  pid=$!
  echo "$pid" > data/simulation.pid
  for _ in $(seq 1 180); do
    if grep -q "Simulation ready." data/logs/simulation.log; then
      awk '/Simulation ready./,0' data/logs/simulation.log
      exit 0
    fi
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "Simulation stopped before the streams were ready. See data/logs/simulation.log" >&2
      cat data/logs/simulation.log >&2
      restore_sitl
      exit 1
    fi
    sleep 1
  done
  echo "Simulation is still starting. See data/logs/simulation.log" >&2
  exit 1
fi

set +e
"${cmd[@]}"
code=$?
set -e
restore_sitl
exit "$code"
