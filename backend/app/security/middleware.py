from __future__ import annotations

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.core.config import Settings
from app.core.context import RequestContext, reset_context, set_context
from app.security.cookies import SESSION_COOKIE
from app.security.identity import derive_user_id
from app.security.jwt import TokenValidationError, TokenValidator
from app.security.oidc import OidcClient, resolve_principal_with_refresh
from app.security.public_paths import PUBLIC_PREFIXES
from app.security.sessions import SessionStore

logger = structlog.get_logger(__name__)


class AuthContextMiddleware(BaseHTTPMiddleware):
    """Resolves the caller's identity -- Authorization: Bearer header first,
    then the BFF session cookie -- into a RequestContext bound to a
    ContextVar for the duration of the request. Never raises: an
    unauthenticated request simply proceeds with no context bound, and the
    CurrentUser dependency (security/deps.py) is what turns that into a 401,
    so FastAPI's normal exception-handler chain applies (see csrf.py for why
    middleware-level raises are avoided)."""

    def __init__(self, app, settings: Settings, store: SessionStore) -> None:
        super().__init__(app)
        self._settings = settings
        self._validator = TokenValidator(settings)
        self._oidc = OidcClient(settings)
        self._store = store

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path.startswith(PUBLIC_PREFIXES):
            return await call_next(request)

        ctx = await self._resolve_context(request)
        token = set_context(ctx) if ctx else None
        try:
            return await call_next(request)
        finally:
            if token is not None:
                reset_context(token)

    async def _resolve_context(self, request: Request) -> RequestContext | None:
        ip = getattr(request.state, "client_ip", None) or (
            request.client.host if request.client else None
        )
        ua = request.headers.get("user-agent")
        request_id = getattr(request.state, "request_id", None)

        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:]
            try:
                principal = self._validator.validate(token)
            except TokenValidationError as exc:
                logger.warning(
                    "auth.bearer_token_rejected",
                    reason=exc.reason,
                    request_id=request_id,
                    path=request.url.path,
                )
                return None
            return RequestContext(
                tenant_id=principal.tenant_id,
                user_id=derive_user_id(principal.sub),
                sub=principal.sub,
                roles=principal.roles,
                acr=principal.acr,
                ip_address=ip,
                user_agent=ua,
                request_id=request_id,
            )

        session_id = request.cookies.get(SESSION_COOKIE)
        if not session_id:
            return None
        data = await self._store.get(session_id)
        if data is None:
            return None
        try:
            principal, _ = await resolve_principal_with_refresh(self._oidc, self._store, session_id, data)
        except TokenValidationError as exc:
            logger.warning(
                "auth.session_rejected",
                reason=exc.reason,
                request_id=request_id,
                path=request.url.path,
            )
            await self._store.revoke(session_id)
            return None
        return RequestContext(
            tenant_id=principal.tenant_id,
            user_id=derive_user_id(principal.sub),
            sub=principal.sub,
            roles=principal.roles,
            acr=principal.acr,
            ip_address=ip,
            user_agent=ua,
            request_id=request_id,
        )
