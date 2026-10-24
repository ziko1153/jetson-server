#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ ! -x .venv/bin/python ]]; then
  echo "No virtual environment. Run the platform setup script first." >&2
  exit 1
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m app.tools.validate_config
exec python -m app.tools.doctor
