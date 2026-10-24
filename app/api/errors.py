"""Consistent error responses."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.exceptions import GatewayError
from app.core.logging import request_id_var


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(GatewayError)
    async def gateway_error(_request: Request, exc: GatewayError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=_body(exc.code, exc.message, exc.details))

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_body("validation_failed", "Request validation failed.", {"errors": exc.errors()}),
        )


def _body(code: str, message: str, details: dict) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "request_id": request_id_var.get(),
            "details": details,
        }
    }
