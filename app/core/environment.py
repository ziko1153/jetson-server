"""Identify the host without treating every ARM64 machine as a Jetson."""

from __future__ import annotations

import platform
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


JETSON_MODEL_PATH = "/proc/device-tree/model"
JETSON_COMPATIBLE_PATH = "/proc/device-tree/compatible"
TEGRA_RELEASE_PATH = "/etc/nv_tegra_release"
NVIDIA_PLUGINS = ("nvv4l2decoder", "nvv4l2h264enc", "nvvidconv")

_L4T_TO_JETPACK = {
    "32": "4",
    "35": "5",
    "36": "6",
}


@dataclass
class SystemReader:
    """Reads the local machine. Tests substitute a fake reader."""

    def system(self) -> str:
        return platform.system()

    def machine(self) -> str:
        return platform.machine()

    def read_text(self, path: str) -> str | None:
        file_path = Path(path)
        if not file_path.is_file():
            return None
        data = file_path.read_bytes().replace(b"\x00", b" ").decode("utf-8", errors="replace")
        return data.strip() or None

    def which(self, name: str) -> str | None:
        return shutil.which(name)

    def plugin_available(self, element: str) -> bool:
        inspector = self.which("gst-inspect-1.0")
        if inspector is None:
            return False
        completed = subprocess.run(
            [inspector, element],
            capture_output=True,
            timeout=15,
            check=False,
        )
        return completed.returncode == 0


@dataclass
class EnvironmentReport:
    hardware: str
    system: str
    machine: str
    jetson_model: str | None = None
    l4t_release: str | None = None
    jetpack_family: str | None = None
    ffmpeg: str | None = None
    ffprobe: str | None = None
    gstreamer: str | None = None
    mediamtx: str | None = None
    nvidia_plugins: dict[str, bool] = field(default_factory=dict)
    hardware_encoder_expected: bool | None = None
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "hardware": self.hardware,
            "system": self.system,
            "machine": self.machine,
            "jetson_model": self.jetson_model,
            "l4t_release": self.l4t_release,
            "jetpack_family": self.jetpack_family,
            "ffmpeg": self.ffmpeg,
            "ffprobe": self.ffprobe,
            "gstreamer": self.gstreamer,
            "mediamtx": self.mediamtx,
            "nvidia_plugins": self.nvidia_plugins,
            "hardware_encoder_expected": self.hardware_encoder_expected,
            "notes": self.notes,
        }


def detect_environment(reader: SystemReader | None = None, mediamtx_path: Path | None = None) -> EnvironmentReport:
    reader = reader or SystemReader()
    system = reader.system()
    machine = reader.machine()
    model = reader.read_text(JETSON_MODEL_PATH)
    compatible = reader.read_text(JETSON_COMPATIBLE_PATH) or ""
    tegra = reader.read_text(TEGRA_RELEASE_PATH)
    jetson = _is_jetson(model, compatible, tegra)
    if system == "Darwin":
        hardware = "macos"
    elif jetson:
        hardware = "jetson"
    elif system == "Linux":
        hardware = "linux"
    else:
        hardware = "unknown"

    l4t = _l4t_revision(tegra)
    notes: list[str] = []
    if system == "Linux" and machine in {"aarch64", "arm64"} and not jetson:
        notes.append("ARM64 alone is not treated as NVIDIA Jetson hardware.")
    encoder_expected = None
    if model:
        lowered = model.lower()
        if "orin nano" in lowered:
            encoder_expected = False
            notes.append("Orin Nano boards do not share the Orin NX hardware encoder. Plugin checks decide the pipeline.")
        elif "orin nx" in lowered:
            encoder_expected = True
            notes.append("Orin NX hardware encoding is expected, and is used only when the plugins are installed.")

    mediamtx = str(mediamtx_path) if mediamtx_path and mediamtx_path.is_file() else reader.which("mediamtx")
    plugins = {name: reader.plugin_available(name) for name in NVIDIA_PLUGINS} if hardware == "jetson" else {}
    if hardware != "jetson":
        notes.append("NVIDIA GStreamer plugins are not probed on this hardware.")

    return EnvironmentReport(
        hardware=hardware,
        system=system,
        machine=machine,
        jetson_model=model if jetson else None,
        l4t_release=l4t,
        jetpack_family=_L4T_TO_JETPACK.get(l4t.split(".")[0], None) if l4t else None,
        ffmpeg=reader.which("ffmpeg"),
        ffprobe=reader.which("ffprobe"),
        gstreamer=reader.which("gst-launch-1.0"),
        mediamtx=mediamtx,
        nvidia_plugins=plugins,
        hardware_encoder_expected=encoder_expected,
        notes=notes,
    )


def _is_jetson(model: str | None, compatible: str, tegra: str | None) -> bool:
    model_text = (model or "").lower()
    compatible_text = compatible.lower()
    if tegra:
        return True
    if "jetson" in model_text:
        return True
    return "nvidia,tegra" in compatible_text


def _l4t_revision(tegra: str | None) -> str | None:
    if not tegra:
        return None
    for token in tegra.replace(",", " ").split():
        if token.startswith("R") and token[1:].isdigit():
            release = token[1:]
            revision = "0"
            if "REVISION:" in tegra:
                after = tegra.split("REVISION:", 1)[1].strip().split(",", 1)[0].strip()
                revision = after or revision
            return f"{release}.{revision}"
    return tegra.splitlines()[0][:120]
