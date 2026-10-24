from pathlib import Path

from app.core.environment import JETSON_MODEL_PATH, TEGRA_RELEASE_PATH, SystemReader, detect_environment
from app.core.security import AuthSettings, Authenticator
from app.core.exceptions import ConfigurationError, UnauthorizedError
from app.core.redaction import redact
import pytest
from starlette.requests import Request


class FakeReader(SystemReader):
    def __init__(self, files: dict[str, str], system: str = "Linux", machine: str = "aarch64") -> None:
        self._files = files
        self._system = system
        self._machine = machine

    def system(self) -> str:
        return self._system

    def machine(self) -> str:
        return self._machine

    def read_text(self, path: str) -> str | None:
        return self._files.get(path)

    def which(self, name: str) -> str | None:
        return None

    def plugin_available(self, element: str) -> bool:
        return False


def test_arm64_without_tegra_is_not_jetson() -> None:
    report = detect_environment(FakeReader({}))
    assert report.hardware == "linux"
    assert any("ARM64" in note for note in report.notes)


def test_tegra_release_is_jetson_and_maps_jetpack_family() -> None:
    report = detect_environment(
        FakeReader(
            {
                TEGRA_RELEASE_PATH: "# R36 (release), REVISION: 4.3, GCID: 1",
                JETSON_MODEL_PATH: "NVIDIA Jetson Orin NX Engineering Reference Developer Kit",
            }
        )
    )
    assert report.hardware == "jetson"
    assert report.l4t_release == "36.4.3"
    assert report.jetpack_family == "6"
    assert report.hardware_encoder_expected is True


def test_orin_nano_does_not_claim_the_nx_encoder() -> None:
    report = detect_environment(
        FakeReader({TEGRA_RELEASE_PATH: "# R36 (release), REVISION: 3.0", JETSON_MODEL_PATH: "NVIDIA Jetson Orin Nano"})
    )
    assert report.hardware_encoder_expected is False


def test_this_mac_is_not_classified_as_jetson() -> None:
    report = detect_environment()
    if report.system == "Darwin":
        assert report.hardware == "macos"


def test_redaction_hides_rtsp_passwords() -> None:
    assert redact("rtsp://front:s3cret@192.168.144.101:554/") == "rtsp://front:***@192.168.144.101:554/"


def test_disabled_auth_allows_requests() -> None:
    authenticator = Authenticator(AuthSettings(mode="disabled", exempt_paths=(), token=None))
    authenticator.authenticate(_request())


def test_bearer_auth_rejects_and_accepts_token() -> None:
    authenticator = Authenticator(AuthSettings(mode="bearer", exempt_paths=(), token="abc"))
    with pytest.raises(UnauthorizedError):
        authenticator.authenticate(_request())
    authenticator.authenticate(_request("Bearer abc"))
    with pytest.raises(UnauthorizedError):
        authenticator.authenticate(_request("Bearer wrong"))


def test_bearer_without_token_fails_closed() -> None:
    with pytest.raises(ConfigurationError):
        Authenticator(AuthSettings(mode="bearer", exempt_paths=(), token=None))


def _request(authorization: str | None = None) -> Request:
    headers = []
    if authorization:
        headers.append((b"authorization", authorization.encode()))
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/v1/cameras",
        "raw_path": b"/api/v1/cameras",
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 1234),
        "server": ("127.0.0.1", 8080),
    }
    return Request(scope)
