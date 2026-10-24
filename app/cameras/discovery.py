"""Camera discovery boundary.

The gateway does not scan the network. Cameras are added by editing the
registry. This module exists so a future explicit discovery command has one
place to live, and so nothing else starts a scan by accident.
"""

from __future__ import annotations

from app.core.exceptions import ValidationFailed


def discover_cameras() -> list[dict]:
    raise ValidationFailed(
        "Network scanning is disabled. Add each camera explicitly in config/cameras.json.",
        code="discovery_disabled",
    )
