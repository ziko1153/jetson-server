"""Local secrets. The file is not committed."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CameraCredentials:
    username: str
    password: str


class SecretStore:
    def __init__(self, path: Path, api_token: str | None) -> None:
        self.path = path
        self.api_token = api_token
        self._cameras: dict[str, CameraCredentials] = {}

    def camera(self, ref: str | None) -> CameraCredentials:
        if not ref:
            return CameraCredentials("", "")
        return self._cameras.get(ref, CameraCredentials("", ""))


def load_secrets(path: Path) -> SecretStore:
    token = os.environ.get("UGV_API_TOKEN") or None
    cameras: dict[str, CameraCredentials] = {}
    if path.is_file():
        payload = json.loads(path.read_text(encoding="utf-8"))
        file_token = str(payload.get("api_token") or "")
        if token is None and file_token:
            token = file_token
        for key, value in (payload.get("cameras") or {}).items():
            if not isinstance(value, dict):
                continue
            cameras[str(key)] = CameraCredentials(
                username=str(value.get("username") or ""),
                password=str(value.get("password") or ""),
            )
    store = SecretStore(path, token)
    store._cameras = cameras
    return store
