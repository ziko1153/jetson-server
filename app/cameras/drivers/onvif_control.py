"""ONVIF Media2 encoder configuration and PTZ continuous moves.

Media2 reports H.265 encoders, which Media1 cannot describe. Every request goes
to the camera host from the registry; nothing here searches the network.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from urllib.parse import urlsplit
from xml.etree import ElementTree
from xml.sax.saxutils import escape

from app.cameras.drivers.onvif import SCHEMA_NS, OnvifClient, OnvifError, local_name

MEDIA2_NS = "http://www.onvif.org/ver20/media/wsdl"
PTZ_NS = "http://www.onvif.org/ver20/ptz/wsdl"
PAN_TILT_VELOCITY = "http://www.onvif.org/ver10/tptz/PanTiltSpaces/VelocityGenericSpace"
ZOOM_VELOCITY = "http://www.onvif.org/ver10/tptz/ZoomSpaces/VelocityGenericSpace"

ElementTree.register_namespace("tt", SCHEMA_NS)
ElementTree.register_namespace("tr2", MEDIA2_NS)


@dataclass
class EncoderOptions:
    codec: str
    resolutions: list[tuple[int, int]]
    frame_rates: list[int]
    bitrate_min: int | None
    bitrate_max: int | None
    gov_min: int | None
    gov_max: int | None
    profiles: list[str]


@dataclass
class StreamEncoder:
    profile_token: str
    profile_name: str
    encoder_token: str
    path: str | None
    codec: str
    width: int
    height: int
    fps: int
    bitrate_kbps: int
    gov_length: int | None
    encoding_profile: str | None
    constant_bitrate: bool
    options: list[EncoderOptions] = field(default_factory=list)


@dataclass
class EncoderChange:
    codec: str | None = None
    width: int | None = None
    height: int | None = None
    fps: int | None = None
    bitrate_kbps: int | None = None
    gov_length: int | None = None


@dataclass
class PtzNode:
    profile_token: str
    pan_tilt: bool
    zoom: bool
    home: bool


@dataclass(frozen=True)
class Login:
    username: str
    password: str


class OnvifControl:
    def __init__(self, client: OnvifClient) -> None:
        self._client = client

    def streams(self, url: str, login: Login) -> list[StreamEncoder]:
        configurations = self._encoder_configurations(url, login)
        found: list[StreamEncoder] = []
        for token, name, encoder_token in self._profiles(url, login):
            element = configurations.get(encoder_token or "")
            if element is None:
                continue
            stream = _parse_stream(token, name, element)
            stream.path = self._stream_path(url, login, token)
            stream.options = self._options(url, login, stream.encoder_token)
            found.append(stream)
        return found

    def set_encoder(self, url: str, login: Login, encoder_token: str, change: EncoderChange) -> None:
        element = self._encoder_configurations(url, login).get(encoder_token)
        if element is None:
            raise OnvifError(f"The camera has no encoder configuration {encoder_token}.")
        updated = _apply_change(element, change)
        updated.tag = f"{{{MEDIA2_NS}}}Configuration"
        inner = f"<tr2:SetVideoEncoderConfiguration>{ElementTree.tostring(updated, encoding='unicode')}</tr2:SetVideoEncoderConfiguration>"
        self._client.request(url, login.username, login.password, inner, {"tr2": MEDIA2_NS, "tt": SCHEMA_NS})

    def ptz_node(self, url: str, login: Login, profile_token: str) -> PtzNode:
        root = self._client.request(url, login.username, login.password, "<tptz:GetNodes/>", {"tptz": PTZ_NS})
        names = {local_name(node.tag) for node in root.iter()}
        return PtzNode(
            profile_token=profile_token,
            pan_tilt="ContinuousPanTiltVelocitySpace" in names,
            zoom="ContinuousZoomVelocitySpace" in names,
            home=any(local_name(node.tag) == "HomeSupported" and (node.text or "").strip() == "true" for node in root.iter()),
        )

    def continuous_move(
        self,
        url: str,
        login: Login,
        profile_token: str,
        *,
        pan: float,
        tilt: float,
        zoom: float,
        timeout_seconds: float,
    ) -> None:
        velocity = ""
        if pan or tilt:
            velocity += f'<tt:PanTilt x="{pan:.3f}" y="{tilt:.3f}" space="{PAN_TILT_VELOCITY}"/>'
        if zoom:
            velocity += f'<tt:Zoom x="{zoom:.3f}" space="{ZOOM_VELOCITY}"/>'
        if not velocity:
            self.stop(url, login, profile_token)
            return
        inner = (
            "<tptz:ContinuousMove>"
            f"<tptz:ProfileToken>{escape(profile_token)}</tptz:ProfileToken>"
            f"<tptz:Velocity>{velocity}</tptz:Velocity>"
            f"<tptz:Timeout>PT{timeout_seconds:.1f}S</tptz:Timeout>"
            "</tptz:ContinuousMove>"
        )
        self._client.request(url, login.username, login.password, inner, {"tptz": PTZ_NS, "tt": SCHEMA_NS})

    def stop(self, url: str, login: Login, profile_token: str) -> None:
        inner = (
            f"<tptz:Stop><tptz:ProfileToken>{escape(profile_token)}</tptz:ProfileToken>"
            "<tptz:PanTilt>true</tptz:PanTilt><tptz:Zoom>true</tptz:Zoom></tptz:Stop>"
        )
        self._client.request(url, login.username, login.password, inner, {"tptz": PTZ_NS})

    def home(self, url: str, login: Login, profile_token: str) -> None:
        inner = f"<tptz:GotoHomePosition><tptz:ProfileToken>{escape(profile_token)}</tptz:ProfileToken></tptz:GotoHomePosition>"
        self._client.request(url, login.username, login.password, inner, {"tptz": PTZ_NS})

    def profile_tokens(self, url: str, login: Login) -> list[str]:
        return [token for token, _, _ in self._profiles(url, login)]

    def _profiles(self, url: str, login: Login) -> list[tuple[str, str, str | None]]:
        inner = "<tr2:GetProfiles><tr2:Type>VideoEncoder</tr2:Type></tr2:GetProfiles>"
        root = self._client.request(url, login.username, login.password, inner, {"tr2": MEDIA2_NS})
        profiles = []
        for node in root.iter():
            if local_name(node.tag) != "Profiles" or "token" not in node.attrib:
                continue
            name = next((child.text for child in node if local_name(child.tag) == "Name" and child.text), node.attrib["token"])
            encoder = next(
                (item.attrib["token"] for item in node.iter() if local_name(item.tag) == "VideoEncoder" and "token" in item.attrib),
                None,
            )
            profiles.append((node.attrib["token"], name, encoder))
        return profiles

    def _encoder_configurations(self, url: str, login: Login) -> dict[str, ElementTree.Element]:
        root = self._client.request(
            url, login.username, login.password, "<tr2:GetVideoEncoderConfigurations/>", {"tr2": MEDIA2_NS}
        )
        return {
            node.attrib["token"]: node
            for node in root.iter()
            if local_name(node.tag) == "Configurations" and "token" in node.attrib
        }

    def _stream_path(self, url: str, login: Login, profile_token: str) -> str | None:
        inner = (
            "<tr2:GetStreamUri><tr2:Protocol>RTSP</tr2:Protocol>"
            f"<tr2:ProfileToken>{escape(profile_token)}</tr2:ProfileToken></tr2:GetStreamUri>"
        )
        try:
            root = self._client.request(url, login.username, login.password, inner, {"tr2": MEDIA2_NS})
        except OnvifError:
            return None
        uri = next((node.text for node in root.iter() if local_name(node.tag) == "Uri" and node.text), None)
        return urlsplit(uri.strip()).path or None if uri else None

    def _options(self, url: str, login: Login, encoder_token: str) -> list[EncoderOptions]:
        inner = (
            "<tr2:GetVideoEncoderConfigurationOptions>"
            f"<tr2:ConfigurationToken>{escape(encoder_token)}</tr2:ConfigurationToken>"
            "</tr2:GetVideoEncoderConfigurationOptions>"
        )
        try:
            root = self._client.request(url, login.username, login.password, inner, {"tr2": MEDIA2_NS})
        except OnvifError:
            return []
        return [_parse_options(node) for node in root.iter() if local_name(node.tag) == "Options"]


def _parse_stream(profile_token: str, profile_name: str, element: ElementTree.Element) -> StreamEncoder:
    rate = _child(element, "RateControl")
    resolution = _child(element, "Resolution")
    gov = element.attrib.get("GovLength")
    return StreamEncoder(
        profile_token=profile_token,
        profile_name=profile_name,
        encoder_token=element.attrib.get("token", ""),
        path=None,
        codec=(_text(element, "Encoding") or "").upper(),
        width=_int(resolution, "Width") or 0,
        height=_int(resolution, "Height") or 0,
        fps=_int(rate, "FrameRateLimit") or 0,
        bitrate_kbps=_int(rate, "BitrateLimit") or 0,
        gov_length=int(gov) if gov and gov.isdigit() else None,
        encoding_profile=element.attrib.get("Profile"),
        constant_bitrate=(rate.attrib.get("ConstantBitRate", "false").lower() == "true") if rate is not None else False,
    )


def _parse_options(node: ElementTree.Element) -> EncoderOptions:
    resolutions = []
    for item in node:
        if local_name(item.tag) == "ResolutionsAvailable":
            width, height = _int(item, "Width"), _int(item, "Height")
            if width and height:
                resolutions.append((width, height))
    rates = [int(value) for value in node.attrib.get("FrameRatesSupported", "").split() if value.isdigit()]
    bitrate = _child(node, "BitrateRange")
    gov = _child(node, "GovLengthRange")
    return EncoderOptions(
        codec=(_text(node, "Encoding") or "").upper(),
        resolutions=resolutions,
        frame_rates=sorted(set(rates)),
        bitrate_min=_int(bitrate, "Min"),
        bitrate_max=_int(bitrate, "Max"),
        gov_min=_int(gov, "Min"),
        gov_max=_int(gov, "Max"),
        profiles=node.attrib.get("ProfilesSupported", "").split(),
    )


def _apply_change(element: ElementTree.Element, change: EncoderChange) -> ElementTree.Element:
    updated = copy.deepcopy(element)
    if change.codec:
        _set_text(updated, "Encoding", change.codec.upper())
    resolution = _child(updated, "Resolution")
    if resolution is not None:
        if change.width:
            _set_text(resolution, "Width", str(change.width))
        if change.height:
            _set_text(resolution, "Height", str(change.height))
    rate = _child(updated, "RateControl")
    if rate is not None:
        if change.fps:
            _set_text(rate, "FrameRateLimit", str(change.fps))
        if change.bitrate_kbps:
            _set_text(rate, "BitrateLimit", str(change.bitrate_kbps))
    if change.gov_length:
        updated.attrib["GovLength"] = str(change.gov_length)
    return updated


def _child(element: ElementTree.Element | None, name: str) -> ElementTree.Element | None:
    if element is None:
        return None
    return next((child for child in element if local_name(child.tag) == name), None)


def _text(element: ElementTree.Element | None, name: str) -> str | None:
    child = _child(element, name)
    return child.text.strip() if child is not None and child.text else None


def _int(element: ElementTree.Element | None, name: str) -> int | None:
    value = _text(element, name)
    return int(value) if value and value.isdigit() else None


def _set_text(element: ElementTree.Element, name: str, value: str) -> None:
    child = _child(element, name)
    if child is None:
        raise OnvifError(f"The camera encoder configuration has no {name} field.")
    child.text = value
