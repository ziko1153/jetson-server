import json

import pytest

from app.core.config import load_settings
from app.core.exceptions import ConfigurationError
from app.core.paths import project_root
from app.media.labels import render_label
from app.media.rtsp.mediamtx import render_config, rtsp_listen_address
from app.media.simulation import (
    gateway_environment,
    load_camera_file,
    load_simulation,
    parse_ifconfig,
    playback_urls,
    player_commands,
    ready_banner,
    render_publisher_config,
    resolve_bind_host,
    validate_sources,
)
from app.media.virtual import virtual_camera_command
from app.schemas.camera import CameraRecord
from app.services.secrets import SecretStore


def test_default_virtual_command_stays_a_test_pattern() -> None:
    command = virtual_camera_command("rtsp://127.0.0.1:8555/CAM-001", ffmpeg="ffmpeg")
    assert command[:9] == [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-re",
        "-f",
        "lavfi",
        "-i",
        "testsrc=size=640x360:rate=10,format=yuv420p",
    ]
    assert command[-1] == "rtsp://127.0.0.1:8555/CAM-001"


def test_pattern_command_can_label_and_shift_hue() -> None:
    command = virtual_camera_command(
        "rtsp://127.0.0.1:8555/CAM-003",
        ffmpeg="ffmpeg",
        pattern="smptebars",
        hue_speed=40,
        label_image="/tmp/CAM-003.ppm",
    )
    assert "smptebars=size=640x360:rate=10,hue=h=t*40,format=yuv420p" in command
    assert "[0:v][1:v]overlay=16:16:eof_action=repeat" in command
    assert "/tmp/CAM-003.ppm" in command
    assert "veryfast" in command


def test_file_command_loops_a_local_video() -> None:
    command = virtual_camera_command(
        "rtsp://127.0.0.1:8555/CAM-001",
        ffmpeg="ffmpeg",
        media_file="/tmp/front.mp4",
    )
    assert "-stream_loop" in command
    assert "/tmp/front.mp4" in command
    assert "lavfi" not in command


def test_unknown_pattern_is_rejected() -> None:
    with pytest.raises(ValueError):
        virtual_camera_command("rtsp://127.0.0.1/CAM-001", ffmpeg="ffmpeg", pattern="camera")


def test_clock_frame_uses_the_camera_size() -> None:
    from app.media.labels import render_clock_frame

    frame = render_clock_frame(640, 360, "CAM-002", "22:14:05.3", (40, 180, 60), 12)
    assert len(frame) == 640 * 360 * 3
    assert frame != b"\x00" * len(frame)


def test_pattern_publisher_command_names_the_camera() -> None:
    from app.media.pattern_publisher import pattern_publisher_command

    command = pattern_publisher_command("python", "rtsp://127.0.0.1:8555/CAM-002", "CAM-002", 640, 360, 10, (1, 2, 3))
    assert command[:3] == ["python", "-m", "app.media.pattern_publisher"]
    assert "CAM-002" in command
    assert "rtsp://127.0.0.1:8555/CAM-002" in command


def test_mosaic_retimes_inputs_so_a_missing_timestamp_still_appears() -> None:
    from app.media.mosaic.layouts import tiles_for
    from app.media.mosaic.pipeline import ffmpeg_mosaic_command
    from app.schemas.mosaic import MosaicOutput

    output = MosaicOutput(width=640, height=360, fps=10, bitrate_kbps=800, codec="h264")
    tiles = tiles_for("single", ["CAM-002"], output)
    command = ffmpeg_mosaic_command("ffmpeg", ["rtsp://127.0.0.1:8555/CAM-002"], tiles, output, "rtsp://127.0.0.1:8554/mosaic")
    graph = command[command.index("-filter_complex") + 1]
    assert "fps=10:round=near,setpts=PTS-STARTPTS" in graph
    assert "nobuffer" in command
    assert command[command.index("-probesize") + 1] == "32"
    assert command[command.index("-analyzeduration") + 1] == "1"


def test_label_is_a_ppm_bitmap() -> None:
    payload = render_label("CAM-001", (220, 40, 40))
    assert payload.startswith(b"P6\n")
    width, height = payload.split(b"\n", 3)[1].split()
    assert int(width) % 2 == 0
    assert int(height) % 2 == 0


def test_shipped_simulation_is_six_local_patterns_and_leaves_vehicle_cameras_alone() -> None:
    root = project_root()
    simulation = load_simulation(root / "config" / "simulation.json")
    cameras = load_camera_file(root / "config" / "cameras.simulation.json")
    validate_sources(root, simulation, cameras, SecretStore(root / "missing-secrets.json", None))
    assert [item.id for item in simulation.cameras] == [f"CAM-00{index}" for index in range(1, 7)]
    assert {item.input for item in simulation.cameras} == {"pattern"}
    assert [url.rsplit("/", 1)[-1] for url in playback_urls("127.0.0.1", 8554, [item.id for item in simulation.cameras])][-1] == "mosaic"
    production = json.loads((root / "config" / "cameras.json").read_text(encoding="utf-8"))
    hosts = [camera["connection"]["host"] for camera in production["cameras"]]
    assert hosts == [f"192.168.144.{index}" for index in range(101, 107)]
    mosaic = json.loads((root / "config" / "mosaic.json").read_text(encoding="utf-8"))
    simulated = json.loads((root / "config" / "mosaic.simulation.json").read_text(encoding="utf-8"))
    assert mosaic["output"]["width"] == 1920
    assert simulated["layout"] == "grid_3x2"
    assert simulated["output"]["width"] == 960
    assert len(simulated["camera_ids"]) == 6


def test_generated_camera_must_point_at_the_local_publisher() -> None:
    root = project_root()
    simulation = load_simulation(root / "config" / "simulation.json")
    cameras = []
    for index in range(1, 7):
        host = "192.168.144.101" if index == 1 else "127.0.0.1"
        port = 554 if index == 1 else 8555
        path = "/" if index == 1 else f"/CAM-00{index}"
        cameras.append(
            CameraRecord.model_validate(
                {
                    "id": f"CAM-00{index}",
                    "name": f"Camera {index}",
                    "connection": {"host": host, "port": port, "path": path},
                }
            )
        )
    with pytest.raises(ConfigurationError, match="generated input"):
        validate_sources(root, simulation, cameras, SecretStore(root / "missing-secrets.json", None))


def test_real_rtsp_input_uses_the_simulation_registry_address() -> None:
    root = project_root()
    simulation = load_simulation(root / "config" / "simulation.json").model_copy(deep=True)
    simulation.cameras[0].input = "rtsp"
    camera = CameraRecord.model_validate(
        {
            "id": "CAM-001",
            "name": "Front",
            "connection": {"host": "192.168.144.101", "port": 554, "path": "/stream"},
            "credentials_ref": "CAM-001",
        }
    )
    others = [
        CameraRecord.model_validate(
            {
                "id": f"CAM-00{index}",
                "name": f"Camera {index}",
                "connection": {"host": "127.0.0.1", "port": 8555, "path": f"/CAM-00{index}"},
            }
        )
        for index in range(2, 7)
    ]
    validate_sources(root, simulation, [camera, *others], SecretStore(root / "missing-secrets.json", None))


def test_bind_interface_uses_the_injected_address() -> None:
    simulation = load_simulation(project_root() / "config" / "simulation.json")
    selected = simulation.model_copy(update={"bind_interface": "en7"})
    assert resolve_bind_host(selected, lookup=lambda name: "192.168.144.50" if name == "en7" else "") == "192.168.144.50"


def test_gateway_environment_points_at_simulation_files() -> None:
    simulation = load_simulation(project_root() / "config" / "simulation.json")
    env = gateway_environment({"UGV_RTSP_BIND_HOST": "10.0.0.8"}, simulation, "0.0.0.0", "")
    assert env["UGV_CAMERAS_FILE"] == "config/cameras.simulation.json"
    assert env["UGV_MOSAIC_FILE"] == "config/mosaic.simulation.json"
    assert env["UGV_CONFIG_FILE"] == "config/config.simulation.json"
    assert env["UGV_BIND_HOST"] == "0.0.0.0"
    assert env["UGV_RTSP_PORT"] == "8554"
    assert "UGV_RTSP_BIND_HOST" not in env
    pinned = gateway_environment({}, simulation, "192.168.144.50", "192.168.144.50")
    assert pinned["UGV_RTSP_BIND_HOST"] == "192.168.144.50"


def test_ready_banner_lists_gateway_urls_and_players() -> None:
    banner = ready_banner("127.0.0.1", 8080, 8554, ["CAM-001"])
    assert "rtsp://127.0.0.1:8554/camera/CAM-001" in banner
    assert "rtsp://127.0.0.1:8554/mosaic" in banner
    assert player_commands("rtsp://127.0.0.1:8554/mosaic")[0] in banner
    assert "ffplay -rtsp_transport tcp rtsp://127.0.0.1:8554/mosaic" in banner
    assert "vlc --rtsp-tcp rtsp://127.0.0.1:8554/mosaic" in banner


def test_ifconfig_parser_skips_loopback() -> None:
    text = "lo0: flags=8049<UP,LOOPBACK,RUNNING,MULTICAST> mtu 16384\n\tinet 127.0.0.1 netmask 0xff000000\nen7: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500\n\tinet 192.168.144.50 netmask 0xffffff00 broadcast 192.168.144.255\n"
    assert parse_ifconfig(text) == [("en7", "192.168.144.50")]


def test_publisher_config_is_local_and_replaceable() -> None:
    rendered = render_publisher_config(["CAM-001", "CAM-002"], 8555, 9998)
    assert "rtspAddress: 127.0.0.1:8555" in rendered
    assert "overridePublisher: yes" in rendered
    assert "CAM-006" not in rendered


def test_rtsp_bind_host_changes_only_the_listen_address() -> None:
    assert rtsp_listen_address("", 8554) == ":8554"
    assert rtsp_listen_address("0.0.0.0", 8554) == ":8554"
    camera = CameraRecord.model_validate(
        {"id": "CAM-001", "name": "Front", "connection": {"host": "127.0.0.1", "port": 8555, "path": "/CAM-001"}}
    )
    rendered = render_config(
        cameras=[camera],
        source_urls={"CAM-001": "rtsp://127.0.0.1:8555/CAM-001"},
        rtsp_port=8554,
        control_port=9997,
        playback_token=None,
        rtsp_bind_host="192.168.144.50",
    )
    assert "rtspAddress: 192.168.144.50:8554" in rendered
    assert "apiAddress: 127.0.0.1:9997" in rendered


def test_process_overrides_are_opt_in(gateway_root, monkeypatch) -> None:
    for name in (
        "UGV_CAMERAS_FILE",
        "UGV_MOSAIC_FILE",
        "UGV_BIND_HOST",
        "UGV_API_PORT",
        "UGV_RTSP_PORT",
        "UGV_RTSP_BIND_HOST",
        "UGV_ADVERTISE_HOST",
        "UGV_CONTROL_PORT",
    ):
        monkeypatch.delenv(name, raising=False)
    settings = load_settings(gateway_root)
    assert settings.cameras_path.name == "cameras.json"
    assert settings.mosaic_path.name == "mosaic.json"
    assert settings.streaming.rtsp_bind_host == ""
    assert settings.server.port == 8080
    assert settings.mavlink.flight_controller.transport == "none"


def test_process_overrides_select_simulation_files(gateway_root, monkeypatch) -> None:
    config = gateway_root / "config"
    (config / "cameras.simulation.json").write_text((config / "cameras.json").read_text(encoding="utf-8"), encoding="utf-8")
    (config / "mosaic.simulation.json").write_text((config / "mosaic.json").read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv("UGV_CAMERAS_FILE", "config/cameras.simulation.json")
    monkeypatch.setenv("UGV_MOSAIC_FILE", "config/mosaic.simulation.json")
    monkeypatch.setenv("UGV_BIND_HOST", "0.0.0.0")
    monkeypatch.setenv("UGV_RTSP_PORT", "8554")
    monkeypatch.setenv("UGV_RTSP_BIND_HOST", "192.168.144.50")
    settings = load_settings(gateway_root)
    assert settings.cameras_path.name == "cameras.simulation.json"
    assert settings.mosaic_path.name == "mosaic.simulation.json"
    assert settings.streaming.rtsp_bind_host == "192.168.144.50"
    assert settings.server.host == "0.0.0.0"


def test_camera_override_cannot_leave_the_project(gateway_root, monkeypatch) -> None:
    monkeypatch.setenv("UGV_CAMERAS_FILE", "/etc/passwd")
    with pytest.raises(ConfigurationError):
        load_settings(gateway_root).cameras_path


def test_simulation_config_opens_flight_controller_udp_without_changing_production(gateway_root, monkeypatch) -> None:
    source = json.loads((project_root() / "config/config.simulation.json").read_text(encoding="utf-8"))
    (gateway_root / "config/config.simulation.json").write_text(json.dumps(source), encoding="utf-8")
    monkeypatch.setenv("UGV_CONFIG_FILE", "config/config.simulation.json")
    settings = load_settings(gateway_root)
    flight = settings.mavlink.flight_controller
    assert flight.transport == "udp"
    assert flight.udp_bind_host == "127.0.0.1"
    assert flight.udp_bind_port == 14551
    assert flight.udp_remote_host == ""
    production = json.loads((project_root() / "config/config.json").read_text(encoding="utf-8"))
    assert production["mavlink"]["flight_controller"]["transport"] == "none"
    assert production["rcwm"]["transport"] == "simulation"


def test_config_override_cannot_leave_the_project(gateway_root, monkeypatch) -> None:
    monkeypatch.setenv("UGV_CONFIG_FILE", "../sitl/sitl-env.sh")
    with pytest.raises(ConfigurationError):
        load_settings(gateway_root)
