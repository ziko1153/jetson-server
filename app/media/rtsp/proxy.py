"""Passthrough path configuration for one camera."""

from __future__ import annotations


def passthrough_conf(source_url: str, *, on_demand: bool) -> dict:
    return {
        "source": source_url,
        "sourceOnDemand": on_demand,
        "sourceOnDemandStartTimeout": "10s",
        "sourceOnDemandCloseAfter": "10s",
        "rtspTransport": "tcp",
    }


def publisher_conf() -> dict:
    return {"source": "publisher", "overridePublisher": True}
