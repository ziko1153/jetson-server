"""Authentication that is off until config turns it on.

Set config auth.mode to "bearer" and provide UGV_API_TOKEN, or api_token in
the secrets file. Route handlers do not need to change.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass

from starlette.requests import Request

from app.core.exceptions import ConfigurationError, UnauthorizedError


@dataclass(frozen=True)
class AuthSettings:
    mode: str
    exempt_paths: tuple[str, ...]
    token: str | None


class Authenticator:
    def __init__(self, settings: AuthSettings) -> None:
        if settings.mode not in {"disabled", "bearer"}:
            raise ConfigurationError(
                f"Unknown auth.mode '{settings.mode}'. Supported values are disabled and bearer."
            )
        if settings.mode == "bearer" and not settings.token:
            raise ConfigurationError(
                "auth.mode is bearer but no token is configured. Set UGV_API_TOKEN or api_token in the secrets file."
            )
        self._settings = settings

    @property
    def mode(self) -> str:
        return self._settings.mode

    def authenticate(self, request: Request) -> None:
        if self._settings.mode == "disabled":
            return
        if request.url.path in self._settings.exempt_paths:
            return
        header = request.headers.get("authorization", "")
        scheme, _, presented = header.partition(" ")
        if scheme.lower() != "bearer" or not presented or not self._token_matches(presented):
            raise UnauthorizedError("A bearer token is required.")

    def _token_matches(self, presented: str) -> bool:
        expected = self._settings.token or ""
        presented_bytes = presented.encode("utf-8")
        expected_bytes = expected.encode("utf-8")
        if len(presented_bytes) != len(expected_bytes):
            hmac.compare_digest(expected_bytes, expected_bytes)
            return False
        return hmac.compare_digest(presented_bytes, expected_bytes)
