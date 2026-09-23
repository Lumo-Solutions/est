from __future__ import annotations

import uuid

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

REQUEST_ID_HEADER = "X-Request-ID"


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        request.state.request_id = request_id
        structlog.contextvars.bind_contextvars(request_id=request_id)
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.unbind_contextvars("request_id")
        response.headers[REQUEST_ID_HEADER] = request_id
        return response


class ClientIpMiddleware(BaseHTTPMiddleware):
    """Resolves the real client IP from X-Forwarded-For, honoring exactly
    TRUSTED_PROXY_HOPS entries from the right -- never trusting the
    left-most (client-supplied, spoofable) value blindly."""

    def __init__(self, app, trusted_proxy_hops: int = 1) -> None:
        super().__init__(app)
        self._hops = max(0, trusted_proxy_hops)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        xff = request.headers.get("x-forwarded-for")
        client_ip = request.client.host if request.client else None
        if xff:
            chain = [h.strip() for h in xff.split(",") if h.strip()]
            if len(chain) >= self._hops and self._hops > 0:
                client_ip = chain[-self._hops]
            elif chain:
                client_ip = chain[0]
        request.state.client_ip = client_ip
        return await call_next(request)
