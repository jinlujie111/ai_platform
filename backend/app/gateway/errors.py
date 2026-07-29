"""Gateway error types and HTTP mapping."""
from __future__ import annotations

from fastapi import HTTPException
from fastapi.responses import JSONResponse


class GatewayError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 502,
        headers: dict[str, str] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.headers = headers or {}


def raise_http(exc: GatewayError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message},
        headers=exc.headers or None,
    )


def error_response(exc: GatewayError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message}},
        headers=exc.headers or None,
    )


def map_upstream_error(exc: Exception) -> GatewayError:
    msg = str(exc) or "上游调用失败"
    low = msg.lower()
    if "timeout" in low or "timed out" in low:
        return GatewayError("upstream_timeout", msg, status_code=504)
    if any(x in low for x in ("401", "403", "unauthorized", "invalid api", "incorrect api")):
        return GatewayError("upstream_auth", msg, status_code=502)
    return GatewayError("upstream_error", msg, status_code=502)
