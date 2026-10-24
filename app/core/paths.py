"""Project paths. Nothing here is specific to one developer machine."""

from __future__ import annotations

import os
from pathlib import Path


def project_root() -> Path:
    override = os.environ.get("UGV_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


def resolve_under_root(root: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (root / path).resolve()
