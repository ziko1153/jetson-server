from xml.etree import ElementTree

import pytest

from app.cameras.drivers.onvif import OnvifError
from app.cameras.drivers.onvif_control import EncoderChange, Login, OnvifControl

ENVELOPE = (
    '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" '
    'xmlns:tr2="http://www.onvif.org/ver20/media/wsdl" xmlns:tt="http://www.onvif.org/ver10/schema" '
    'xmlns:tptz="http://www.onvif.org/ver20/ptz/wsdl"><s:Body>{}</s:Body></s:Envelope>'
)

PROFILES = """<tr2:GetProfilesResponse>
<tr2:Profiles token="MainStreamToken"><tr2:Name>MainStream</tr2:Name>
<tr2:Configurations><tr2:VideoEncoder token="VideoMainEncoder"/></tr2:Configurations></tr2:Profiles>
<tr2:Profiles token="SubStreamToken"><tr2:Name>SubStream</tr2:Name>
<tr2:Configurations><tr2:VideoEncoder token="VideoSubEncoder"/></tr2:Configurations></tr2:Profiles>
</tr2:GetProfilesResponse>"""

ENCODERS = """<tr2:GetVideoEncoderConfigurationsResponse>
<tr2:Configurations token="VideoMainEncoder" GovLength="50" Profile="Main"><tt:Name>Main</tt:Name>
<tt:Encoding>H265</tt:Encoding><tt:Resolution><tt:Width>2496</tt:Width><tt:Height>1792</tt:Height></tt:Resolution>
<tt:RateControl ConstantBitRate="false"><tt:FrameRateLimit>25</tt:FrameRateLimit><tt:BitrateLimit>3072</tt:BitrateLimit></tt:RateControl>
</tr2:Configurations>
<tr2:Configurations token="VideoSubEncoder" GovLength="50"><tt:Name>Sub</tt:Name>
<tt:Encoding>H265</tt:Encoding><tt:Resolution><tt:Width>704</tt:Width><tt:Height>576</tt:Height></tt:Resolution>
<tt:RateControl><tt:FrameRateLimit>25</tt:FrameRateLimit><tt:BitrateLimit>682</tt:BitrateLimit></tt:RateControl>
</tr2:Configurations>
</tr2:GetVideoEncoderConfigurationsResponse>"""

OPTIONS = """<tr2:GetVideoEncoderConfigurationOptionsResponse>
<tr2:Options FrameRatesSupported="25 20 15" ProfilesSupported="Main"><tt:Encoding>H265</tt:Encoding>
<tt:ResolutionsAvailable><tt:Width>2496</tt:Width><tt:Height>1792</tt:Height></tt:ResolutionsAvailable>
<tt:ResolutionsAvailable><tt:Width>1920</tt:Width><tt:Height>1080</tt:Height></tt:ResolutionsAvailable>
<tt:GovLengthRange><tt:Min>5</tt:Min><tt:Max>200</tt:Max></tt:GovLengthRange>
<tt:BitrateRange><tt:Min>256</tt:Min><tt:Max>8192</tt:Max></tt:BitrateRange></tr2:Options>
</tr2:GetVideoEncoderConfigurationOptionsResponse>"""

NODES = """<tptz:GetNodesResponse><tptz:PTZNode token="ptz">
<tt:SupportedPTZSpaces><tt:ContinuousPanTiltVelocitySpace/><tt:ContinuousZoomVelocitySpace/></tt:SupportedPTZSpaces>
<tt:HomeSupported>true</tt:HomeSupported></tptz:PTZNode></tptz:GetNodesResponse>"""


def _uri(token: str) -> str:
    path = "/live0.264" if token == "MainStreamToken" else "/live1.264"
    return f"<tr2:GetStreamUriResponse><tr2:Uri>rtsp://10.0.0.1:8554{path}</tr2:Uri></tr2:GetStreamUriResponse>"


class FakeClient:
    def __init__(self) -> None:
        self.sent: list[str] = []

    def request(self, url, username, password, inner, namespaces):
        self.sent.append(inner)
        if "GetProfiles" in inner:
            body = PROFILES
        elif "GetVideoEncoderConfigurations/" in inner:
            body = ENCODERS
        elif "GetVideoEncoderConfigurationOptions" in inner:
            body = OPTIONS
        elif "GetStreamUri" in inner:
            body = _uri("MainStreamToken" if "MainStreamToken" in inner else "SubStreamToken")
        elif "GetNodes" in inner:
            body = NODES
        else:
            body = "<ok/>"
        return ElementTree.fromstring(ENVELOPE.format(body))


LOGIN = Login("user", "secret")
URL = "http://10.0.0.1/onvif/device_service"


def test_streams_reports_encoder_path_and_options():
    streams = OnvifControl(FakeClient()).streams(URL, LOGIN)

    assert [item.encoder_token for item in streams] == ["VideoMainEncoder", "VideoSubEncoder"]
    main = streams[0]
    assert (main.profile_name, main.path, main.codec) == ("MainStream", "/live0.264", "H265")
    assert (main.width, main.height, main.fps, main.bitrate_kbps, main.gov_length) == (2496, 1792, 25, 3072, 50)
    assert streams[1].path == "/live1.264"
    options = main.options[0]
    assert options.resolutions == [(2496, 1792), (1920, 1080)]
    assert options.frame_rates == [15, 20, 25]
    assert (options.bitrate_min, options.bitrate_max, options.gov_min, options.gov_max) == (256, 8192, 5, 200)


def test_set_encoder_sends_edited_configuration():
    client = FakeClient()
    OnvifControl(client).set_encoder(
        URL, LOGIN, "VideoMainEncoder", EncoderChange(width=1920, height=1080, fps=20, bitrate_kbps=2048, gov_length=20)
    )

    sent = client.sent[-1]
    assert sent.startswith("<tr2:SetVideoEncoderConfiguration>")
    body = ElementTree.fromstring(sent.replace("<tr2:SetVideoEncoderConfiguration>", "").replace("</tr2:SetVideoEncoderConfiguration>", ""))
    text = {node.tag.rsplit("}", 1)[-1]: node.text for node in body.iter()}
    assert body.tag.endswith("}Configuration")
    assert body.attrib["token"] == "VideoMainEncoder"
    assert body.attrib["GovLength"] == "20"
    assert (text["Width"], text["Height"], text["FrameRateLimit"], text["BitrateLimit"]) == ("1920", "1080", "20", "2048")
    assert "secret" not in sent


def test_set_encoder_rejects_unknown_token():
    with pytest.raises(OnvifError):
        OnvifControl(FakeClient()).set_encoder(URL, LOGIN, "Missing", EncoderChange(fps=10))


def test_ptz_node_and_moves():
    client = FakeClient()
    control = OnvifControl(client)

    node = control.ptz_node(URL, LOGIN, "MainStreamToken")
    assert (node.pan_tilt, node.zoom, node.home) == (True, True, True)

    control.continuous_move(URL, LOGIN, "MainStreamToken", pan=0.5, tilt=-0.25, zoom=0, timeout_seconds=1)
    move = client.sent[-1]
    assert 'x="0.500" y="-0.250"' in move
    assert "<tptz:Timeout>PT1.0S</tptz:Timeout>" in move
    assert "Zoom" not in move

    control.continuous_move(URL, LOGIN, "MainStreamToken", pan=0, tilt=0, zoom=0, timeout_seconds=1)
    assert client.sent[-1].startswith("<tptz:Stop>")

    control.home(URL, LOGIN, "MainStreamToken")
    assert "GotoHomePosition" in client.sent[-1]
