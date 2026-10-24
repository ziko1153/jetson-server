"""Host metrics stay honest on macOS."""

from pathlib import Path

from app.core.environment import detect_environment
from app.health.metrics import HostSampler


def test_macos_metrics_do_not_invent_nvidia_values() -> None:
    sampler = HostSampler()
    environment = detect_environment()
    first = sampler.collect(environment, Path("."))
    second = sampler.collect(environment, Path("."))
    assert first["cpu_percent"] is None
    assert isinstance(second["cpu_percent"], float)
    assert second["memory"]["total_bytes"] > 0
    assert second["disk"]["total_bytes"] > 0
    assert second["uptime_seconds"] > 0
    if environment.system == "Darwin":
        assert second["temperature_c"] is None
        assert second["gpu_percent"] is None
        assert second["nvidia_metrics"] == "unavailable"
        assert second["hardware"] == "macos"
