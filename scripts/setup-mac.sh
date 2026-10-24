#!/usr/bin/env bash
# Install the macOS development environment. Does not change network settings.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "setup-mac.sh is for macOS. On the Jetson, run scripts/setup-jetson.sh." >&2
  exit 1
fi

case "$(uname -m)" in
  arm64) MEDIA_ARCH="darwin_arm64" ;;
  x86_64) MEDIA_ARCH="darwin_amd64" ;;
  *)
    echo "Unsupported macOS architecture: $(uname -m)" >&2
    exit 1
    ;;
esac

PYTHON=""
for candidate in python3.12 python3.11 python3.13 python3.10 python3; do
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
  echo "Python 3.10 or newer is required. Install it with: brew install python@3.12" >&2
  exit 1
fi

if [[ ! -x .venv/bin/python ]]; then
  "$PYTHON" -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"

if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
  echo "FFmpeg is required for mosaic composition and stream probing." >&2
  echo "Install it with: brew install ffmpeg" >&2
  echo "This script will not run Homebrew for you." >&2
  exit 1
fi

VERSION="$(python -c 'import json; print(json.load(open("config/config.json"))["streaming"]["media_server_version"])')"
DEST="vendor/mediamtx"
mkdir -p "$DEST"
if [[ ! -x "$DEST/mediamtx" ]]; then
  archive="$(mktemp -d)/mediamtx.tar.gz"
  url="https://github.com/bluenviron/mediamtx/releases/download/${VERSION}/mediamtx_${VERSION}_${MEDIA_ARCH}.tar.gz"
  echo "Downloading MediaMTX ${VERSION} (${MEDIA_ARCH})"
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

python -m app.tools.validate_config
python -m app.tools.doctor
echo "macOS setup finished."
echo "Start the gateway with: bash scripts/start.sh"
