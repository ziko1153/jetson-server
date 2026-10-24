from xml.etree import ElementTree

from app.cameras.discovery import discover_cameras
from app.cameras.drivers.onvif import _parse_encoder, _security_header
from app.cameras.drivers.readonly_rtsp import _bitrate, _frame_rate
from app.core.exceptions import ValidationFailed
import pytest


def test_discovery_does_not_scan() -> None:
    with pytest.raises(ValidationFailed) as caught:
        discover_cameras()
    assert caught.value.code == "discovery_disabled"


def test_security_header_does_not_contain_the_password() -> None:
    header = _security_header("admin", "camera-secret")
    assert "camera-secret" not in header
    assert "PasswordDigest" in header
    assert "admin" in header


def test_encoder_parser_reads_only_present_fields() -> None:
    element = ElementTree.fromstring(
        """
        <VideoEncoderConfiguration token="enc-1">
          <Name>MainStream</Name>
          <UseCount>1</UseCount>
          <Encoding>H264</Encoding>
          <Resolution><Width>1280</Width><Height>720</Height></Resolution>
          <Quality>4</Quality>
          <RateControl>
            <FrameRateLimit>15</FrameRateLimit>
            <EncodingInterval>1</EncodingInterval>
            <BitrateLimit>1500</BitrateLimit>
          </RateControl>
          <H264><GovLength>30</GovLength><H264Profile>Main</H264Profile></H264>
        </VideoEncoderConfiguration>
        """
    )
    parsed = _parse_encoder(element)
    assert parsed.token == "enc-1"
    assert parsed.width == 1280
    assert parsed.frame_rate == 15
    assert parsed.bitrate_kbps == 1500
    assert parsed.h264_profile == "Main"


def test_probe_math_does_not_invent_missing_values() -> None:
    assert _frame_rate("0/0") is None
    assert _frame_rate("15/1") == 15
    assert _bitrate("N/A") is None
    assert _bitrate(None) is None
    assert _bitrate("1500000") == 1500
