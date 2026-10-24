"""Manufacturer-specific camera drivers.

No vendor handler is registered. auto mode uses ONVIF and then the read-only
RTSP driver. A future handler can be added to VENDOR_HANDLERS without changing
the API.
"""

from __future__ import annotations

from collections.abc import Callable

from app.cameras.drivers.base import DriverResult
from app.core.exceptions import UnsupportedError
from app.schemas.camera import CameraRecord, SettingsUpdate

VendorHandler = Callable[[CameraRecord, str, str], DriverResult]
VENDOR_HANDLERS: dict[str, VendorHandler] = {}


class VendorDriver:
    name = "vendor"

    def probe(self, camera: CameraRecord, username: str, password: str) -> DriverResult:
        handler = self._handler(camera)
        return handler(camera, username, password)

    def apply(
        self,
        camera: CameraRecord,
        username: str,
        password: str,
        update: SettingsUpdate,
    ):
        raise UnsupportedError(
            "No vendor configuration handler is registered for this camera.",
            details={"manufacturer": camera.manufacturer, "model": camera.model},
        )

    def _handler(self, camera: CameraRecord) -> VendorHandler:
        key = (camera.manufacturer or "").strip().lower()
        handler = VENDOR_HANDLERS.get(key)
        if handler is None:
            raise UnsupportedError(
                "No vendor driver is registered. Set configuration.driver to auto or onvif, or register a handler.",
                details={"manufacturer": camera.manufacturer},
            )
        return handler
