import socket

import pytest
from pydantic import ValidationError

from app.core.environment import GSTREAMER_ELEMENTS
from app.media.backends.jetson import JetsonBackend
from app.media.mosaic.layouts import tiles_for, validate_tiles
from app.media.mosaic.pipeline import ffmpeg_mosaic_command
from app.media.mosaic.sources import NO_SIGNAL_IMAGE, reachable
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
    ready = JetsonBackend("ffmpeg", "gst-launch-1.0", {name: True for name in GSTREAMER_ELEMENTS}, True)
    no_publisher = JetsonBackend("ffmpeg", "gst-launch-1.0", {name: name != "rtspclientsink" for name in GSTREAMER_ELEMENTS}, True)
    missing = JetsonBackend("ffmpeg", "gst-launch-1.0", {}, True)
    nvidia = ready.mosaic_command(["rtsp://127.0.0.1/live"], tiles, output, "rtsp://127.0.0.1/mosaic")
    software = missing.mosaic_command(["rtsp://127.0.0.1/live"], tiles, output, "rtsp://127.0.0.1/mosaic")
    assert "nvv4l2h264enc" in nvidia
    assert "parsebin" in nvidia
    assert "rtph264depay" not in nvidia
    assert ready.capabilities().acceleration == "nvidia"
    assert no_publisher.capabilities().acceleration == "software"
    assert "libx264" in software
    assert missing.capabilities().acceleration == "software"


def test_offline_tiles_are_drawn_as_no_signal() -> None:
    output = MosaicOutput(width=1280, height=720, fps=15, bitrate_kbps=1500, codec="h264")
    tiles = tiles_for("grid_2x2", ["CAM-001", "CAM-002", "CAM-003", "CAM-004"], output)
    sources = [None, "rtsp://127.0.0.1/live", None, None]
    ready = JetsonBackend("ffmpeg", "gst-launch-1.0", {name: True for name in GSTREAMER_ELEMENTS}, True)
    nvidia = ready.mosaic_command(sources, tiles, output, "rtsp://127.0.0.1/mosaic")
    assert nvidia.count("rtspsrc") == 1
    assert nvidia.count("videotestsrc") == 3
    assert "text=NO SIGNAL" in nvidia
    assert nvidia.count("intervideosink") == nvidia.count("intervideosrc") == 1
    software = ffmpeg_mosaic_command("ffmpeg", sources, tiles, output, "rtsp://127.0.0.1:8554/mosaic")
    assert software.count(str(NO_SIGNAL_IMAGE)) == 3
    assert NO_SIGNAL_IMAGE.is_file()


def test_mosaic_camera_login_stays_out_of_the_location_and_pixels_are_square() -> None:
    output = MosaicOutput(width=1280, height=720, fps=15, bitrate_kbps=1500, codec="h264")
    tiles = tiles_for("single", ["CAM-001"], output)
    ready = JetsonBackend("ffmpeg", "gst-launch-1.0", {name: True for name in GSTREAMER_ELEMENTS}, True)
    nvidia = ready.mosaic_command(["rtsp://viewer:p%40ss@10.0.0.5:8554/live1.264"], tiles, output, "rtsp://127.0.0.1/mosaic")
    assert "location=rtsp://10.0.0.5:8554/live1.264" in nvidia
    assert "user-id=viewer" in nvidia
    assert "user-pw=p@ss" in nvidia
    assert not any("@10.0.0.5" in part for part in nvidia)
    assert "caps=video/x-raw,pixel-aspect-ratio=(fraction)1/1" in nvidia
    assert "sink_0::width=1280" in nvidia
    assert "sink_0::height=720" in nvidia
    assert "idrinterval=15" in nvidia


def test_reachable_reports_only_listening_cameras() -> None:
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    open_port = listener.getsockname()[1]
    closed = socket.socket()
    closed.bind(("127.0.0.1", 0))
    closed_port = closed.getsockname()[1]
    closed.close()
    try:
        live = reachable({"CAM-001": ("127.0.0.1", open_port), "CAM-002": ("127.0.0.1", closed_port)}, timeout=0.5)
    finally:
        listener.close()
    assert live == frozenset({"CAM-001"})


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
