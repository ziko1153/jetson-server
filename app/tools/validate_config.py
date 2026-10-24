"""Validate the JSON configuration without starting media processes."""

from __future__ import annotations

from app.core.config import load_settings
from app.services.camera_registry import CameraRegistry
from app.services.mosaic_manager import MosaicManager
from app.services.secrets import load_secrets


def main() -> None:
    settings = load_settings()
    registry = CameraRegistry(settings.cameras_path, settings.backup_directory)
    load_secrets(settings.secrets_path)
    from app.media.backends.macos import MacOSBackend
    from app.media.rtsp.mediamtx import MediaMTXServer

    media = MediaMTXServer(None, settings.media_server_config_path, settings.log_directory / "mediamtx.log", 9, 1)
    mosaic = MosaicManager(settings, registry, load_secrets(settings.secrets_path), media, MacOSBackend(None))
    print(f"configuration valid: {len(registry.list_cameras())} cameras, mosaic revision {mosaic.view('127.0.0.1').revision}")


if __name__ == "__main__":
    main()
