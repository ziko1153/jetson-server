"""MediaMTX process and path configuration.

Individual camera paths pull the camera and remux. They are not decoded until
a mosaic or an explicit transcode asks for it. Paths stay on demand until a
client starts the stream, so an idle gateway does not connect to cameras.
"""

from __future__ import annotations

import time
from pathlib import Path

import httpx

from app.core.exceptions import UnavailableError
from app.core.logging import get_logger
from app.infrastructure.processes.supervisor import ManagedProcess
from app.schemas.camera import CameraRecord

log = get_logger(__name__)


def camera_path(camera_id: str) -> str:
    return f"camera/{camera_id}"


def quote_yaml(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def rtsp_listen_address(bind_host: str, rtsp_port: int) -> str:
    if bind_host in {"", "0.0.0.0", "::"}:
        return f":{rtsp_port}"
    return f"{bind_host}:{rtsp_port}"


def render_config(
    *,
    cameras: list[CameraRecord],
    source_urls: dict[str, str],
    rtsp_port: int,
    control_port: int,
    playback_token: str | None,
    rtsp_bind_host: str = "",
) -> str:
    lines = [
        "logLevel: info",
        "logDestinations: [stdout]",
        "api: yes",
        f"apiAddress: 127.0.0.1:{control_port}",
        "rtsp: yes",
        f"rtspAddress: {rtsp_listen_address(rtsp_bind_host, rtsp_port)}",
        "rtspTransports: [tcp]",
        "rtmp: no",
        "hls: no",
        "webrtc: no",
        "srt: no",
        "moq: no",
        "playback: no",
        "authMethod: internal",
        "authInternalUsers:",
    ]
    if playback_token:
        lines.extend(
            [
                "  - user: gcs",
                f"    pass: {quote_yaml(playback_token)}",
                "    ips: []",
                "    permissions:",
                "      - action: read",
                "      - action: playback",
            ]
        )
    else:
        lines.extend(
            [
                "  - user: any",
                "    pass:",
                "    ips: []",
                "    permissions:",
                "      - action: read",
                "      - action: playback",
            ]
        )
    lines.extend(
        [
            "  - user: any",
            "    pass:",
            '    ips: ["127.0.0.1", "::1"]',
            "    permissions:",
            "      - action: publish",
            "      - action: read",
            "      - action: playback",
            "      - action: api",
            "      - action: metrics",
            "paths:",
        ]
    )
    for camera in cameras:
        if not camera.enabled:
            continue
        lines.extend(_path_block(camera_path(camera.id), source_urls[camera.id], on_demand=True))
    lines.extend(_publisher_block("mosaic"))
    return "\n".join(lines) + "\n"


def _path_block(name: str, source: str, *, on_demand: bool) -> list[str]:
    demand = "yes" if on_demand else "no"
    return [
        f"  {quote_yaml(name)}:",
        f"    source: {quote_yaml(source)}",
        f"    sourceOnDemand: {demand}",
        "    sourceOnDemandStartTimeout: 10s",
        "    sourceOnDemandCloseAfter: 10s",
        "    rtspTransport: tcp",
    ]


def _publisher_block(name: str) -> list[str]:
    return [
        f"  {quote_yaml(name)}:",
        "    source: publisher",
        "    overridePublisher: yes",
    ]


class MediaMTXServer:
    def __init__(
        self,
        binary: Path | None,
        config_path: Path,
        log_path: Path,
        control_port: int,
        stop_timeout: float,
        pid_file: Path | None = None,
    ) -> None:
        self._binary = binary
        self._config_path = config_path
        self._log_path = log_path
        self._control_port = control_port
        self._stop_timeout = stop_timeout
        self._pid_file = pid_file
        self._process: ManagedProcess | None = None

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.running

    @property
    def pid(self) -> int | None:
        if self._process is None:
            return None
        return self._process.pid

    def start(self, config_text: str) -> None:
        if self._binary is None or not self._binary.is_file():
            raise UnavailableError(
                "MediaMTX is not installed. Run the platform setup script before starting streams.",
                code="media_server_missing",
            )
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        self._config_path.write_text(config_text, encoding="utf-8")
        self._config_path.chmod(0o600)
        self._process = ManagedProcess(
            name="mediamtx",
            args=[str(self._binary), str(self._config_path)],
            log_path=self._log_path,
            restart_attempts=3,
            stop_timeout_seconds=self._stop_timeout,
            pid_file=self._pid_file,
        )
        self._process.start()
        self._wait_until_ready()

    def stop(self) -> None:
        if self._process is not None:
            self._process.stop()

    def terminate_now(self) -> None:
        if self._process is not None:
            self._process.terminate_now()

    def upsert(self, name: str, body: dict) -> None:
        self._request("POST", f"/v3/config/paths/add/{name}", body, missing_ok=True)

    def delete(self, name: str) -> None:
        self._request("DELETE", f"/v3/config/paths/delete/{name}", None, missing_ok=True)

    def path_info(self, name: str) -> dict | None:
        response = self._request("GET", f"/v3/paths/get/{name}", None, missing_ok=True)
        if response is None:
            return None
        return response

    def _wait_until_ready(self) -> None:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                httpx.get(self._url("/v3/paths/list"), timeout=1).raise_for_status()
                return
            except httpx.HTTPError:
                time.sleep(0.2)
        raise UnavailableError("MediaMTX did not open its local control API.", code="media_server_unavailable")

    def _request(self, method: str, path: str, body: dict | None, *, missing_ok: bool) -> dict | None:
        if not self.running:
            raise UnavailableError("The RTSP server is not running.", code="media_server_unavailable")
        try:
            response = httpx.request(method, self._url(path), json=body, timeout=5)
        except httpx.HTTPError as exc:
            raise UnavailableError("The RTSP control API is not responding.", code="media_server_unavailable") from exc
        if response.status_code == 400 and body is not None and "already exists" in response.text.lower():
            replace = path.replace("/add/", "/replace/", 1)
            response = httpx.post(self._url(replace), json=body, timeout=5)
        if response.status_code == 404 and missing_ok:
            return None
        if response.status_code >= 400:
            raise UnavailableError(
                "The RTSP server rejected a path update.",
                details={"status": response.status_code},
            )
        if not response.content:
            return {}
        return response.json()

    def _url(self, path: str) -> str:
        return f"http://127.0.0.1:{self._control_port}{path}"
