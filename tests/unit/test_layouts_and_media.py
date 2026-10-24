import pytest
from pydantic import ValidationError

from app.media.backends.jetson import JetsonBackend
from app.media.mosaic.layouts import tiles_for, validate_tiles
from app.media.mosaic.pipeline import ffmpeg_mosaic_command
from app.media.rtsp.mediamtx import render_config
from app.schemas.camera import CameraRecord
from app.schemas.mosaic import MosaicOutput, MosaicTile
from app.core.exceptions import ValidationFailed


def test_preset_layouts_match_camera_counts() -> None:
    output = MosaicOutput(width=1920, height=1080, fps=15, bitrate_kbps=3000, codec="h264")
    single = tiles_for("single", ["CAM-001"], output)
    pair = tiles_for("side_by_side", ["CAM-001", "CAM-006"], output)
    triple = tiles_for("three_focus", ["CAM-001", "CAM-002", "CAM-003"], output)
    six = tiles_for("grid_3x2", [f"CAM-00{index}" for index in range(1, 7)], output)
    assert single[0].width == 1920
    assert pair[0].width == 960 and pair[1].x == 960
    assert triple[0].height == 540 and triple[2].x == 960
    assert len(six) == 6
    assert six[5].x == 1280 and six[5].y == 540


def test_five_camera_preset_uses_three_over_two() -> None:
    output = MosaicOutput(width=1920, height=1080, fps=15, bitrate_kbps=3000, codec="h264")
    tiles = tiles_for("five_3_over_2", [f"CAM-00{index}" for index in range(1, 6)], output)
    assert len(tiles) == 5
    assert tiles[0].width == 640
    assert tiles[3].width == 960
    assert tiles[3].y == 540


def test_tile_outside_canvas_is_rejected() -> None:
    output = MosaicOutput(width=640, height=360, fps=10, bitrate_kbps=500, codec="h264")
    tile = MosaicTile(camera_id="CAM-001", x=400, y=0, width=320, height=180)
    with pytest.raises(ValidationFailed):
        validate_tiles([tile], output)


def test_odd_dimensions_are_rejected() -> None:
    with pytest.raises(ValidationError):
        MosaicOutput(width=1921, height=1080, fps=15, bitrate_kbps=3000, codec="h264")


def test_ffmpeg_command_keeps_urls_as_arguments() -> None:
    output = MosaicOutput(width=640, height=360, fps=10, bitrate_kbps=500, codec="h264")
    tiles = tiles_for("single", ["CAM-001"], output)
    url = "rtsp://user:secret@127.0.0.1:8555/live"
    command = ffmpeg_mosaic_command("ffmpeg", [url], tiles, output, "rtsp://127.0.0.1:8554/mosaic")
    assert isinstance(command, list)
    assert command[0] == "ffmpeg"
    assert url in command
    assert "libx264" in command


def test_jetson_uses_nvidia_encoder_only_when_plugins_exist() -> None:
    output = MosaicOutput(width=640, height=360, fps=10, bitrate_kbps=500, codec="h264")
    tiles = tiles_for("single", ["CAM-001"], output)
    ready = JetsonBackend("ffmpeg", "gst-launch-1.0", {name: True for name in ("nvv4l2decoder", "nvv4l2h264enc", "nvvidconv")}, True)
    missing = JetsonBackend("ffmpeg", "gst-launch-1.0", {}, True)
    nvidia = ready.mosaic_command(["rtsp://127.0.0.1/live"], tiles, output, "rtsp://127.0.0.1/mosaic")
    software = missing.mosaic_command(["rtsp://127.0.0.1/live"], tiles, output, "rtsp://127.0.0.1/mosaic")
    assert "nvv4l2h264enc" in nvidia
    assert ready.capabilities().acceleration == "nvidia"
    assert "libx264" in software
    assert missing.capabilities().acceleration == "software"


def test_mediamtx_config_quotes_paths_and_can_require_playback_token() -> None:
    camera = CameraRecord.model_validate(
        {
            "id": "CAM-001",
            "name": "Front",
            "connection": {"host": "127.0.0.1", "port": 8555, "path": "/live"},
        }
    )
    rendered = render_config(
        cameras=[camera],
        source_urls={"CAM-001": "rtsp://cam:camera-secret@127.0.0.1:8555/live"},
        rtsp_port=8554,
        control_port=9997,
        playback_token="api-token",
    )
    assert '"camera/CAM-001"' in rendered
    assert "sourceOnDemand: yes" in rendered
    assert "user: gcs" in rendered
    assert 'pass: "api-token"' in rendered
    assert "127.0.0.1" in rendered
    open_access = render_config(
        cameras=[camera],
        source_urls={"CAM-001": "rtsp://127.0.0.1:8555/live"},
        rtsp_port=8554,
        control_port=9997,
        playback_token=None,
    )
    assert "user: any" in open_access
    assert "user: gcs" not in open_access
