"""Local virtual-camera playback. Nothing in this module contacts the vehicle network."""

from __future__ import annotations

import json
import socket
import subprocess
import time
from pathlib import Path
from shutil import which

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.router import create_app
from app.core.config import load_settings
from app.infrastructure.processes.supervisor import ManagedProcess
from app.media.virtual import virtual_camera_command

pytestmark = pytest.mark.e2e
ROOT = Path(__file__).resolve().parents[2]


def _reserve_ports(count: int) -> list[int]:
    holders = []
    ports = []
    for _ in range(count):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        ports.append(sock.getsockname()[1])
        holders.append(sock)
    for sock in holders:
        sock.close()
    return ports


def _ffprobe(url: str) -> dict | None:
    ffprobe = which("ffprobe")
    if ffprobe is None:
        return None
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        completed = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-rtsp_transport",
                "tcp",
                "-rw_timeout",
                "4000000",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height,codec_name",
                "-of",
                "json",
                url,
            ],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        if completed.stdout.strip():
            payload = json.loads(completed.stdout)
            if payload.get("streams"):
                return payload
        time.sleep(0.4)
    return None


def _wait_for_port(port: int, timeout: float = 10) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def _wait_online(api_port: int, names: list[str]) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            payload = httpx.get(f"http://127.0.0.1:{api_port}/v3/paths/list", timeout=1).json()
        except httpx.HTTPError:
            time.sleep(0.2)
            continue
        online = {item["name"] for item in payload.get("items", []) if item.get("online")}
        if set(names) <= online:
            return
        time.sleep(0.3)
    raise AssertionError(f"Virtual cameras did not come online: {names}")


@pytest.fixture
def virtual_gateway(tmp_path: Path):
    ffmpeg = which("ffmpeg")
    mediamtx = ROOT / "vendor" / "mediamtx" / "mediamtx"
    if ffmpeg is None or not mediamtx.is_file():
        pytest.skip("ffmpeg and the bundled MediaMTX binary are required")
    camera_rtsp, camera_api, gateway_rtsp, gateway_api = _reserve_ports(4)
    camera_config = tmp_path / "cameras-mediamtx.yml"
    path_lines = ["logLevel: info", "api: yes", f"apiAddress: 127.0.0.1:{camera_api}", "rtsp: yes"]
    path_lines.extend(
        [
            f"rtspAddress: :{camera_rtsp}",
            "rtspTransports: [tcp]",
            "rtmp: no",
            "hls: no",
            "webrtc: no",
            "srt: no",
            "moq: no",
            "playback: no",
            "paths:",
        ]
    )
    for index in range(1, 7):
        path_lines.extend([f"  CAM-00{index}:", "    source: publisher"])
    camera_config.write_text("\n".join(path_lines) + "\n", encoding="utf-8")
    camera_server = ManagedProcess(
        name="virtual-mediamtx",
        args=[str(mediamtx), str(camera_config)],
        log_path=tmp_path / "virtual-mediamtx.log",
    )
    camera_server.start()
    publishers: list[ManagedProcess] = []
    try:
        if not _wait_for_port(camera_rtsp):
            raise AssertionError((tmp_path / "virtual-mediamtx.log").read_text(encoding="utf-8", errors="replace"))
        for index in range(1, 7):
            camera_id = f"CAM-00{index}"
            process = ManagedProcess(
                name=f"virtual-{camera_id}",
                args=virtual_camera_command(
                    f"rtsp://127.0.0.1:{camera_rtsp}/{camera_id}",
                    ffmpeg=ffmpeg,
                ),
                log_path=tmp_path / f"{camera_id}.log",
                restart_attempts=3,
                restart_backoff_seconds=0.5,
            )
            process.start()
            publishers.append(process)
        _wait_online(camera_api, [f"CAM-00{index}" for index in range(1, 7)])
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        for name in ("config.json", "cameras.json", "mosaic.json", "profiles.json"):
            payload = json.loads((ROOT / "config" / name).read_text(encoding="utf-8"))
            if name == "config.json":
                payload["streaming"]["manage_media_server"] = True
                payload["streaming"]["rtsp_port"] = gateway_rtsp
                payload["streaming"]["control_port"] = gateway_api
                payload["streaming"]["media_server_binary"] = str(mediamtx)
                payload["health"]["enabled"] = False
                payload.setdefault("mavlink", {})["enabled"] = False
                payload.setdefault("rcwm", {})["enabled"] = False
            if name == "cameras.json":
                for camera in payload["cameras"]:
                    camera["connection"]["host"] = "127.0.0.1"
                    camera["connection"]["port"] = camera_rtsp
                    camera["connection"]["path"] = f"/{camera['id']}"
                    camera["configuration"]["driver"] = "readonly_rtsp"
            (config_dir / name).write_text(json.dumps(payload), encoding="utf-8")
        with TestClient(create_app(load_settings(tmp_path))) as client:
            yield client, gateway_rtsp, tmp_path
    finally:
        for process in publishers:
            process.stop()
        camera_server.stop()


def test_two_streams_and_mosaics_publish_real_video(virtual_gateway) -> None:
    client, rtsp_port, root = virtual_gateway
    for camera_id in ("CAM-001", "CAM-002"):
        started = client.post(f"/api/v1/streams/{camera_id}/start", json={"mode": "passthrough"})
        assert started.status_code == 200, started.text
        probed = _ffprobe(f"rtsp://127.0.0.1:{rtsp_port}/camera/{camera_id}")
        assert probed is not None, _failure_log(root, camera_id)
        stream = probed["streams"][0]
        assert stream["codec_name"] == "h264"
        assert stream["width"] == 640
        assert stream["height"] == 360

    mosaic = client.put(
        "/api/v1/mosaic",
        json={
            "layout": "three_focus",
            "output": {"width": 640, "height": 360, "fps": 10, "bitrate_kbps": 800, "codec": "h264"},
            "camera_ids": ["CAM-001", "CAM-002", "CAM-003"],
        },
    )
    assert mosaic.status_code == 200, mosaic.text
    started_mosaic = client.post("/api/v1/mosaic/start")
    assert started_mosaic.status_code == 200, started_mosaic.text
    probed = _ffprobe(f"rtsp://127.0.0.1:{rtsp_port}/mosaic")
    assert probed is not None, _failure_log(root, "mosaic")
    assert probed["streams"][0]["width"] == 640
    assert probed["streams"][0]["height"] == 360
    client.post("/api/v1/mosaic/stop")

    six = client.put(
        "/api/v1/mosaic",
        json={
            "expected_revision": mosaic.json()["revision"],
            "layout": "grid_3x2",
            "output": {"width": 960, "height": 540, "fps": 10, "bitrate_kbps": 1200, "codec": "h264"},
            "camera_ids": [f"CAM-00{index}" for index in range(1, 7)],
        },
    )
    assert six.status_code == 200, six.text
    assert client.post("/api/v1/mosaic/start").status_code == 200
    six_probe = _ffprobe(f"rtsp://127.0.0.1:{rtsp_port}/mosaic")
    assert six_probe is not None, _failure_log(root, "mosaic-six")
    assert six_probe["streams"][0]["width"] == 960
    assert six_probe["streams"][0]["height"] == 540


def _failure_log(root: Path, label: str) -> str:
    parts = [label]
    for path in (root / "data" / "logs").glob("*.log"):
        text = path.read_text(encoding="utf-8", errors="replace")[-2000:]
        parts.append(f"\n## {path.name}\n{text}")
    virtual = root / "virtual-mediamtx.log"
    if virtual.is_file():
        parts.append(virtual.read_text(encoding="utf-8", errors="replace")[-1000:])
    return "\n".join(parts)
