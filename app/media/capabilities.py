"""Capability report assembled for the system API."""

from __future__ import annotations

from app.core.environment import EnvironmentReport
from app.media.backends.base import MediaBackend


def system_capabilities(environment: EnvironmentReport, backend: MediaBackend, profiles: dict) -> dict:
    media = backend.capabilities()
    return {
        "environment": environment.as_dict(),
        "media_backend": {
            "name": media.name,
            "acceleration": media.acceleration,
            "mosaic_encoder": media.mosaic_encoder,
            "ffmpeg": media.ffmpeg,
            "gstreamer": media.gstreamer,
            "nvidia_encoder": media.nvidia_encoder,
            "notes": media.notes,
        },
        "profiles": {name: profile.model_dump() for name, profile in profiles.items()},
        "individual_streams": "passthrough",
        "mosaic": "compose_and_encode",
    }
