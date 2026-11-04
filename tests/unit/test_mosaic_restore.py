import threading

from app.core.config import load_settings
from app.services.context import build_context


def _capture_start(manager) -> threading.Event:
    started = threading.Event()
    manager.start = lambda host: started.set()
    return started


def test_mosaic_restarts_when_it_was_running(gateway_root) -> None:
    settings = load_settings(gateway_root)
    build_context(settings).mosaic._remember_running(True)

    restarted = build_context(settings).mosaic
    started = _capture_start(restarted)
    restarted.restore()
    assert started.wait(2)


def test_stopped_mosaic_stays_stopped(gateway_root) -> None:
    settings = load_settings(gateway_root)
    build_context(settings).mosaic._remember_running(False)

    restarted = build_context(settings).mosaic
    started = _capture_start(restarted)
    restarted.restore()
    assert not started.wait(0.2)
