from app.core.config import load_settings
from app.core.exceptions import ConflictError
from app.services.context import build_context


class _Media:
    def __init__(self) -> None:
        self.running = True
        self.body: dict | None = None
        self.info = {
            "online": False,
            "readers": [],
            "inboundBytes": 1000,
            "tracks2": [{"codec": "H264", "codecProps": {"width": 640, "height": 360}}],
        }

    def upsert(self, name: str, body: dict) -> None:
        self.body = body

    def delete(self, name: str) -> None:
        self.body = None

    def path_info(self, name: str) -> dict:
        return self.info


def test_passthrough_start_and_stop_do_not_mark_measured_fps(gateway_root) -> None:
    ctx = build_context(load_settings(gateway_root))
    media = _Media()
    ctx.streams._media = media
    started = ctx.streams.start("CAM-001", "passthrough", "127.0.0.1")
    assert started.phase == "active"
    assert started.mode == "passthrough"
    assert media.body is not None
    assert media.body["sourceOnDemand"] is False
    media.info["online"] = True
    media.info["readers"] = [{"id": "viewer"}]
    try:
        ctx.streams.stop("CAM-001", "127.0.0.1", force=False)
    except ConflictError as exc:
        assert exc.status_code == 409
    else:
        raise AssertionError("stop should reject a stream that still has a viewer")
    stopped = ctx.streams.stop("CAM-001", "127.0.0.1", force=True)
    assert stopped.phase == "idle"
    assert media.body["sourceOnDemand"] is True


def test_reconnect_count_and_bitrate_need_real_samples(gateway_root) -> None:
    ctx = build_context(load_settings(gateway_root))
    media = _Media()
    ctx.streams._media = media
    session = ctx.streams._session("CAM-001")
    session.phase = "active"
    session.last_online = False
    media.info["online"] = True
    first = ctx.streams.metrics("CAM-001")
    assert first.reconnect_count == 1
    assert first.codec == "h264"
    assert first.width == 640
    assert first.measured_fps is None
    assert first.measured_bitrate_kbps is None
    assert first.last_frame_at is None
    media.info["online"] = True
    media.info["inboundBytes"] = 1000 + 125_000
    second = ctx.streams.metrics("CAM-001")
    assert second.measured_bitrate_kbps is not None
    assert second.configured_fps == 15
    assert second.measured_fps is None
