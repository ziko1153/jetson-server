"""Publish URLs shared by mosaic and transcode publishers."""

from __future__ import annotations

from app.infrastructure.networking.urls import public_rtsp_url


def local_publish_url(port: int, path: str) -> str:
    return public_rtsp_url("127.0.0.1", port, path)
