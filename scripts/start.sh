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
python -m app.tools.doctor --require-runtime

HOST="$(python -c 'from app.core.config import load_settings; print(load_settings().server.host)')"
PORT="$(python -c 'from app.core.config import load_settings; print(load_settings().server.port)')"
mkdir -p data/logs

if [[ -f data/gateway.pid ]]; then
  existing="$(cat data/gateway.pid)"
  if kill -0 "$existing" 2>/dev/null; then
    echo "Gateway is already running (pid ${existing})." >&2
    exit 1
  fi
fi

echo "API docs: http://127.0.0.1:${PORT}/docs"
echo "Health: http://127.0.0.1:${PORT}/api/v1/health"
echo "This script does not change network interfaces."

if [[ "${1:-}" == "--detach" ]]; then
  nohup python -m uvicorn app.main:app --host "$HOST" --port "$PORT" >> data/logs/gateway.log 2>&1 &
  echo $! > data/gateway.pid
  echo "Gateway started in the background (pid $(cat data/gateway.pid))."
  exit 0
fi

exec python -m uvicorn app.main:app --host "$HOST" --port "$PORT"
