"""RTSP URL construction and validation. Credentials stay out of public URLs."""

from __future__ import annotations

from urllib.parse import quote, urlsplit

from app.schemas.camera import CameraRecord, ConnectionSettings


def direct_rtsp_url(connection: ConnectionSettings) -> str:
    return f"{connection.protocol}://{connection.host}:{connection.port}{connection.path}"


def source_rtsp_url(camera: CameraRecord, username: str, password: str) -> str:
    connection = camera.connection
    if not username:
        return direct_rtsp_url(connection)
    user = quote(username, safe="")
    secret = quote(password, safe="")
    return f"{connection.protocol}://{user}:{secret}@{connection.host}:{connection.port}{connection.path}"


def public_rtsp_url(host: str, port: int, path: str) -> str:
    cleaned = path.lstrip("/")
    return f"rtsp://{host}:{port}/{cleaned}"


def advertise_host(configured: str, request_host: str | None) -> str:
    if configured:
        return configured
    if request_host:
        return request_host.split(":", 1)[0]
    return "127.0.0.1"


def assert_public_url_has_no_credentials(url: str) -> None:
    parts = urlsplit(url)
    if parts.username or parts.password:
        raise ValueError("public stream URLs cannot contain credentials")
