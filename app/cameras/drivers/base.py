"""Camera driver contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.schemas.camera import CameraRecord, CapabilityReport, PhysicalSettings, SettingsUpdate


@dataclass
class DriverResult:
    capabilities: CapabilityReport
    settings: PhysicalSettings


class CameraDriver(Protocol):
    name: str

    def probe(self, camera: CameraRecord, username: str, password: str) -> DriverResult:
        ...

    def apply(
        self,
        camera: CameraRecord,
        username: str,
        password: str,
        update: SettingsUpdate,
    ) -> PhysicalSettings:
        ...
