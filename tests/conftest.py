"""Build an isolated gateway for tests. Tests do not contact cameras."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.router import create_app
from app.core.config import load_settings

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def gateway_root(tmp_path: Path) -> Path:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    for name in ("config.json", "cameras.json", "mosaic.json", "profiles.json"):
        payload = json.loads((ROOT / "config" / name).read_text(encoding="utf-8"))
        if name == "config.json":
            payload["streaming"]["manage_media_server"] = False
            payload["health"]["enabled"] = False
            payload.setdefault("mavlink", {})["enabled"] = False
            payload.setdefault("rcwm", {})["enabled"] = False
        (config_dir / name).write_text(json.dumps(payload), encoding="utf-8")
    (config_dir / "secrets.json").write_text(
        json.dumps({"api_token": "test-token", "cameras": {"CAM-001": {"username": "cam", "password": "camera-secret"}}}),
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def client(gateway_root: Path) -> TestClient:
    app = create_app(load_settings(gateway_root))
    with TestClient(app) as test_client:
        yield test_client
