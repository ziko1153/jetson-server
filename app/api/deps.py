"""FastAPI dependencies."""

from __future__ import annotations

from fastapi import Request

from app.infrastructure.networking.urls import advertise_host
from app.services.context import AppContext


def context(request: Request) -> AppContext:
    return request.app.state.ctx


def require_auth(request: Request) -> None:
    context(request).authenticator.authenticate(request)


def client_host(request: Request) -> str:
    settings = context(request).settings
    return advertise_host(settings.streaming.advertise_host, request.url.hostname)
