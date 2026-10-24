"""ONVIF Profile S media operations used for encoder configuration.

The client speaks SOAP over HTTP. It does not scan the network. The caller
supplies the camera host from the registry.
"""

from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from xml.etree import ElementTree
from xml.sax.saxutils import escape

import httpx

from app.cameras.drivers.base import DriverResult
from app.core.exceptions import UnsupportedError
from app.schemas.camera import CameraRecord, CapabilityReport, PhysicalSettings, Resolution, SettingsUpdate

DEVICE_NS = "http://www.onvif.org/ver10/device/wsdl"
MEDIA_NS = "http://www.onvif.org/ver10/media/wsdl"
SCHEMA_NS = "http://www.onvif.org/ver10/schema"
SOAP_NS = "http://www.w3.org/2003/05/soap-envelope"


class OnvifError(Exception):
    pass


@dataclass
class EncoderConfiguration:
    token: str
    name: str
    encoding: str
    width: int
    height: int
    quality: float
    frame_rate: int
    encoding_interval: int
    bitrate_kbps: int
    gov_length: int | None
    h264_profile: str | None
    use_count: int


class OnvifClient:
    def __init__(self, timeout: float = 5) -> None:
        self._timeout = timeout

    def probe(self, camera: CameraRecord, username: str, password: str) -> DriverResult:
        device_url = _device_url(camera)
        media_url = self._media_url(device_url, username, password)
        profiles = self._get_profiles(media_url, username, password)
        options = self._encoder_options(media_url, username, password, profiles)
        current = profiles[0] if profiles else None
        resolutions = sorted({(item.width, item.height) for item in options}, key=lambda item: item[0] * item[1])
        rates = sorted({item.frame_rate for item in options if item.frame_rate})
        codecs = sorted({item.encoding.lower() for item in options})
        bitrates = [item.bitrate_kbps for item in options if item.bitrate_kbps]
        report = CapabilityReport(
            camera_id=camera.id,
            source="onvif",
            probed_at=_now(),
            codecs=codecs or None,
            resolutions=[Resolution(width=width, height=height) for width, height in resolutions] or None,
            frame_rates=[float(rate) for rate in rates] or None,
            bitrate_kbps_min=min(bitrates) if bitrates else None,
            bitrate_kbps_max=max(bitrates) if bitrates else None,
            encoder_profiles=sorted({item.h264_profile for item in options if item.h264_profile}) or None,
            configuration_supported=True,
            limitations=["Capabilities come from ONVIF encoder options, not from an assumed camera model."],
            detected_width=current.width if current else None,
            detected_height=current.height if current else None,
            detected_fps=float(current.frame_rate) if current else None,
            detected_bitrate_kbps=float(current.bitrate_kbps) if current else None,
            detected_codec=current.encoding.lower() if current else None,
        )
        settings = _settings_from(current, supported=True, source="onvif")
        return DriverResult(capabilities=report, settings=settings)

    def apply(
        self,
        camera: CameraRecord,
        username: str,
        password: str,
        update: SettingsUpdate,
    ) -> PhysicalSettings:
        device_url = _device_url(camera)
        media_url = self._media_url(device_url, username, password)
        profiles = self._get_profiles(media_url, username, password)
        if not profiles:
            raise UnsupportedError("The camera did not return an ONVIF video encoder configuration.")
        selected = profiles[0]
        if update.stream_profile:
            matched = [item for item in profiles if item.name == update.stream_profile or item.token == update.stream_profile]
            if not matched:
                raise UnsupportedError(
                    f"Stream profile '{update.stream_profile}' was not returned by the camera.",
                    details={"profiles": [item.name for item in profiles]},
                )
            selected = matched[0]
        width = update.width or selected.width
        height = update.height or selected.height
        fps = update.fps or selected.frame_rate
        bitrate = update.bitrate_kbps or selected.bitrate_kbps
        codec = (update.codec or selected.encoding).upper().replace("H.264", "H264").replace("H.265", "H265")
        if codec in {"H264", "AVC"}:
            codec = "H264"
        profile_name = update.encoding_profile or selected.h264_profile or "Main"
        gov = update.keyframe_interval or selected.gov_length or fps * 2
        body = _set_encoder_body(
            token=selected.token,
            name=selected.name,
            use_count=selected.use_count,
            encoding=codec,
            width=width,
            height=height,
            quality=selected.quality,
            frame_rate=fps,
            encoding_interval=selected.encoding_interval,
            bitrate=bitrate,
            gov_length=gov,
            h264_profile=profile_name,
            username=username,
            password=password,
        )
        self._call(media_url, username, password, body, header_already=True)
        confirmed = self._get_profiles(media_url, username, password)
        match = next((item for item in confirmed if item.token == selected.token), confirmed[0] if confirmed else None)
        return _settings_from(match, supported=True, source="onvif")

    def _media_url(self, device_url: str, username: str, password: str) -> str:
        body = (
            f'<s:Envelope xmlns:s="{SOAP_NS}" xmlns:tds="{DEVICE_NS}">'
            f"<s:Header>{_security_header(username, password)}</s:Header>"
            "<s:Body><tds:GetCapabilities><tds:Category>Media</tds:Category></tds:GetCapabilities></s:Body>"
            "</s:Envelope>"
        )
        root = self._call(device_url, username, password, body, header_already=True)
        for element in root.iter():
            if _local(element.tag) == "XAddr" and element.text and "media" in element.text.lower():
                return element.text.strip()
        raise OnvifError("ONVIF device service did not advertise a media address.")

    def _get_profiles(self, media_url: str, username: str, password: str) -> list[EncoderConfiguration]:
        body = (
            f'<s:Envelope xmlns:s="{SOAP_NS}" xmlns:trt="{MEDIA_NS}">'
            f"<s:Header>{_security_header(username, password)}</s:Header>"
            "<s:Body><trt:GetProfiles/></s:Body></s:Envelope>"
        )
        root = self._call(media_url, username, password, body, header_already=True)
        found: list[EncoderConfiguration] = []
        for profile in root.iter():
            if _local(profile.tag) != "Profiles":
                continue
            encoder = next((child for child in profile.iter() if _local(child.tag) == "VideoEncoderConfiguration"), None)
            if encoder is None:
                continue
            parsed = _parse_encoder(encoder)
            profile_name = next((child.text for child in list(profile) if _local(child.tag) == "Name" and child.text), parsed.name)
            parsed.name = profile_name or parsed.name
            found.append(parsed)
        return found

    def _encoder_options(
        self,
        media_url: str,
        username: str,
        password: str,
        profiles: list[EncoderConfiguration],
    ) -> list[EncoderConfiguration]:
        if not profiles:
            return []
        token = profiles[0].token
        body = (
            f'<s:Envelope xmlns:s="{SOAP_NS}" xmlns:trt="{MEDIA_NS}">'
            f"<s:Header>{_security_header(username, password)}</s:Header>"
            "<s:Body><trt:GetVideoEncoderConfigurationOptions>"
            f"<trt:ConfigurationToken>{escape(token)}</trt:ConfigurationToken>"
            "</trt:GetVideoEncoderConfigurationOptions></s:Body></s:Envelope>"
        )
        try:
            root = self._call(media_url, username, password, body, header_already=True)
        except OnvifError:
            return profiles
        options: list[EncoderConfiguration] = []
        for element in root.iter():
            if _local(element.tag) not in {"H264", "H265", "MPEG4", "JPEG"}:
                continue
            encoding = _local(element.tag)
            for resolution in element.iter():
                if _local(resolution.tag) != "Width":
                    continue
                parent = _parent_map(root).get(resolution)
                if parent is None or _local(parent.tag) != "Resolution":
                    continue
                width = int(resolution.text or 0)
                height_node = next((node for node in list(parent) if _local(node.tag) == "Height"), None)
                height = int(height_node.text) if height_node is not None and height_node.text else 0
                if width and height:
                    options.append(
                        EncoderConfiguration(
                            token=token,
                            name=encoding,
                            encoding=encoding,
                            width=width,
                            height=height,
                            quality=0,
                            frame_rate=_first_int(element, "FrameRateLimit") or profiles[0].frame_rate,
                            encoding_interval=1,
                            bitrate_kbps=_first_int(element, "BitrateLimit") or profiles[0].bitrate_kbps,
                            gov_length=_first_int(element, "GovLength"),
                            h264_profile=_first_text(element, "H264Profile"),
                            use_count=1,
                        )
                    )
        return options or profiles

    def _call(
        self,
        url: str,
        username: str,
        password: str,
        body: str,
        *,
        header_already: bool = False,
    ) -> ElementTree.Element:
        payload = body if header_already else _wrap(username, password, body)
        headers = {"Content-Type": "application/soap+xml; charset=utf-8"}
        try:
            response = httpx.post(url, content=payload.encode("utf-8"), headers=headers, timeout=self._timeout)
        except httpx.HTTPError as exc:
            raise OnvifError(f"ONVIF request failed: {exc.__class__.__name__}") from exc
        if response.status_code >= 400:
            raise OnvifError(f"ONVIF endpoint returned HTTP {response.status_code}")
        try:
            root = ElementTree.fromstring(response.text)
        except ElementTree.ParseError as exc:
            raise OnvifError("ONVIF endpoint returned a response that was not SOAP") from exc
        fault = next((node.text for node in root.iter() if _local(node.tag) == "Text" and node.text), None)
        if any(_local(node.tag) == "Fault" for node in root.iter()):
            raise OnvifError(fault or "ONVIF fault")
        return root


def _device_url(camera: CameraRecord) -> str:
    connection = camera.connection
    return f"http://{connection.host}:{connection.onvif_port}{connection.onvif_path}"


def _security_header(username: str, password: str) -> str:
    if not username:
        return ""
    nonce = os.urandom(16)
    created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    digest = base64.b64encode(hashlib.sha1(nonce + created.encode() + password.encode()).digest()).decode()
    nonce_b64 = base64.b64encode(nonce).decode()
    return (
        '<wsse:Security xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd" '
        'xmlns:wsu="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd" '
        's:mustUnderstand="1"><wsse:UsernameToken>'
        f"<wsse:Username>{escape(username)}</wsse:Username>"
        '<wsse:Password Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest">'
        f"{digest}</wsse:Password>"
        '<wsse:Nonce EncodingType="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary">'
        f"{nonce_b64}</wsse:Nonce><wsu:Created>{created}</wsu:Created>"
        "</wsse:UsernameToken></wsse:Security>"
    )


def _wrap(username: str, password: str, body: str) -> str:
    return (
        f'<s:Envelope xmlns:s="{SOAP_NS}"><s:Header>{_security_header(username, password)}</s:Header>'
        f"<s:Body>{body}</s:Body></s:Envelope>"
    )


def _set_encoder_body(
    *,
    token: str,
    name: str,
    use_count: int,
    encoding: str,
    width: int,
    height: int,
    quality: float,
    frame_rate: int,
    encoding_interval: int,
    bitrate: int,
    gov_length: int,
    h264_profile: str,
    username: str,
    password: str,
) -> str:
    codec_block = ""
    if encoding == "H264":
        codec_block = (
            f"<tt:H264><tt:GovLength>{gov_length}</tt:GovLength>"
            f"<tt:H264Profile>{escape(h264_profile)}</tt:H264Profile></tt:H264>"
        )
    return (
        f'<s:Envelope xmlns:s="{SOAP_NS}" xmlns:trt="{MEDIA_NS}" xmlns:tt="{SCHEMA_NS}">'
        f"<s:Header>{_security_header(username, password)}</s:Header><s:Body><trt:SetVideoEncoderConfiguration>"
        f'<trt:Configuration token="{escape(token)}">'
        f"<tt:Name>{escape(name)}</tt:Name><tt:UseCount>{use_count}</tt:UseCount>"
        f"<tt:Encoding>{escape(encoding)}</tt:Encoding>"
        f"<tt:Resolution><tt:Width>{width}</tt:Width><tt:Height>{height}</tt:Height></tt:Resolution>"
        f"<tt:Quality>{quality}</tt:Quality>"
        f"<tt:RateControl><tt:FrameRateLimit>{frame_rate}</tt:FrameRateLimit>"
        f"<tt:EncodingInterval>{encoding_interval}</tt:EncodingInterval>"
        f"<tt:BitrateLimit>{bitrate}</tt:BitrateLimit></tt:RateControl>"
        f"{codec_block}"
        "<tt:Multicast><tt:Address><tt:Type>IPv4</tt:Type><tt:IPv4Address>0.0.0.0</tt:IPv4Address></tt:Address>"
        "<tt:Port>0</tt:Port><tt:TTL>1</tt:TTL><tt:AutoStart>false</tt:AutoStart></tt:Multicast>"
        "<tt:SessionTimeout>PT60S</tt:SessionTimeout></trt:Configuration>"
        "<trt:ForcePersistence>true</trt:ForcePersistence>"
        "</trt:SetVideoEncoderConfiguration></s:Body></s:Envelope>"
    )


def _parse_encoder(element: ElementTree.Element) -> EncoderConfiguration:
    def text(name: str) -> str | None:
        return _first_text(element, name)

    width = _first_int(element, "Width") or 0
    height = _first_int(element, "Height") or 0
    return EncoderConfiguration(
        token=element.attrib.get("token", ""),
        name=text("Name") or "",
        encoding=text("Encoding") or "",
        width=width,
        height=height,
        quality=float(text("Quality") or 0),
        frame_rate=_first_int(element, "FrameRateLimit") or 0,
        encoding_interval=_first_int(element, "EncodingInterval") or 1,
        bitrate_kbps=_first_int(element, "BitrateLimit") or 0,
        gov_length=_first_int(element, "GovLength"),
        h264_profile=text("H264Profile"),
        use_count=_first_int(element, "UseCount") or 1,
    )


def _settings_from(encoder: EncoderConfiguration | None, *, supported: bool, source: str) -> PhysicalSettings:
    if encoder is None:
        return PhysicalSettings(supported=supported, source=source)
    return PhysicalSettings(
        supported=supported,
        source=source,
        codec=encoder.encoding.lower() or None,
        width=encoder.width or None,
        height=encoder.height or None,
        fps=float(encoder.frame_rate) if encoder.frame_rate else None,
        bitrate_kbps=encoder.bitrate_kbps or None,
        encoding_profile=encoder.h264_profile,
        keyframe_interval=encoder.gov_length,
        stream_profile=encoder.name or None,
    )


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _first_text(element: ElementTree.Element, name: str) -> str | None:
    for node in element.iter():
        if _local(node.tag) == name and node.text:
            return node.text.strip()
    return None


def _first_int(element: ElementTree.Element, name: str) -> int | None:
    text = _first_text(element, name)
    if text and text.isdigit():
        return int(text)
    return None


def _parent_map(root: ElementTree.Element) -> dict[ElementTree.Element, ElementTree.Element]:
    return {child: parent for parent in root.iter() for child in list(parent)}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
