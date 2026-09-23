from __future__ import annotations

import hmac

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.core.config import Settings
from app.security.cookies import CSRF_COOKIE, SESSION_COOKIE
from app.security.public_paths import PUBLIC_PREFIXES

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}


class CsrfMiddleware(BaseHTTPMiddleware):
    """Double-submit cookie check for cookie-authenticated mutations. Bearer
    token requests (Authorization header present) are exempt -- CSRF only
    matters when the browser is auto-attaching credentials (cookies)."""

    def __init__(self, app, settings: Settings) -> None:
        super().__init__(app)
        self._settings = settings

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method in _SAFE_METHODS or request.url.path.startswith(PUBLIC_PREFIXES):
            return await call_next(request)
        if request.headers.get("authorization", "").lower().startswith("bearer "):
            return await call_next(request)
        if SESSION_COOKIE not in request.cookies:
            return await call_next(request)  # unauthenticated; auth dependency will 401

        cookie_token = request.cookies.get(CSRF_COOKIE, "")
        header_token = request.headers.get(self._settings.csrf_header, "")
        if not cookie_token or not hmac.compare_digest(cookie_token, header_token):
            return JSONResponse(
                status_code=403,
                media_type="application/problem+json",
                content={
                    "type": "urn:installtec:forbidden",
                    "title": "Not authorized",
                    "status": 403,
                    "detail": "CSRF token missing or invalid",
                    "instance": str(request.url.path),
                },
            )
        return await call_next(request)
