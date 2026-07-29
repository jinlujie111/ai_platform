"""Request ID middleware for P0 observability."""
from __future__ import annotations

import logging
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("ai_platform.request")


class RequestIdMiddleware(BaseHTTPMiddleware):
    header_name = "X-Request-Id"

    async def dispatch(self, request: Request, call_next) -> Response:
        incoming = (request.headers.get(self.header_name) or "").strip()
        request_id = incoming or uuid.uuid4().hex
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers[self.header_name] = request_id
        return response
