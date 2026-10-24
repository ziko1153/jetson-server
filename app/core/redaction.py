"""Redact credentials before they reach logs or API payloads."""

from __future__ import annotations

import re

_RTSP_USERINFO = re.compile(r"(rtsps?://)([^/\s:@]+):([^/\s@]+)@")


def redact(text: str) -> str:
    return _RTSP_USERINFO.sub(r"\1\2:***@", text)
