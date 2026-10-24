# macOS development

`scripts/setup-mac.sh` checks that the machine is macOS, creates `.venv` with Python 3.10 or newer, installs the package, checks for FFmpeg, and downloads the arm64 or x86_64 MediaMTX binary. It does not run Homebrew and it does not change network settings. If FFmpeg is missing it prints `brew install ffmpeg` and stops.

```bash
bash scripts/setup-mac.sh
bash scripts/start.sh
```

Foreground mode is useful while developing. `--detach` writes the log to `data/logs/gateway.log` and the pid to `data/gateway.pid`.

```bash
bash scripts/stop.sh
bash scripts/check-dependencies.sh
.venv/bin/python -m pytest
```

The media backend on this machine is software FFmpeg. NVIDIA plugins are not probed. Virtual playback tests use a second local MediaMTX and FFmpeg test patterns. They do not use the addresses in `config/cameras.json`.

For a session that stays up for VLC or the Kotlin app, run `bash scripts/start-simulation.sh`. That mode is documented in `docs/SIMULATION.md`. It uses `config/cameras.simulation.json` and leaves the vehicle registry untouched.

Call `POST /api/v1/cameras/{id}/probe` only when a camera is intentionally reachable. With the default registry, that call would try `192.168.144.101`.
