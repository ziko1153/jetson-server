"""Application errors with stable codes for the HTTP layer."""

from __future__ import annotations


class GatewayError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        details: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


class ConfigurationError(GatewayError):
    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__("configuration_invalid", message, status_code=500, details=details)


class NotFoundError(GatewayError):
    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__("not_found", message, status_code=404, details=details)


class ValidationFailed(GatewayError):
    def __init__(self, message: str, *, code: str = "validation_failed", details: dict | None = None) -> None:
        super().__init__(code, message, status_code=422, details=details)


class ConflictError(GatewayError):
    def __init__(self, message: str, *, code: str = "conflict", details: dict | None = None) -> None:
        super().__init__(code, message, status_code=409, details=details)


class UnauthorizedError(GatewayError):
    def __init__(self, message: str = "Authentication is required.") -> None:
        super().__init__("unauthorized", message, status_code=401)


class UnavailableError(GatewayError):
    def __init__(self, message: str, *, code: str = "unavailable", details: dict | None = None) -> None:
        super().__init__(code, message, status_code=503, details=details)


class UnsupportedError(GatewayError):
    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(
            "physical_configuration_unsupported",
            message,
            status_code=422,
            details=details,
        )
