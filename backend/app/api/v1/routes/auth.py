from __future__ import annotations

import hmac
import secrets

import httpx
from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import RedirectResponse

from app.core.config import Settings, get_settings, mfa_bypass_active
from app.core.context import RequestContext
from app.core.enums import AuditAction
from app.core.errors import ForbiddenError, UnauthorizedError
from app.core.logging import get_logger
from app.db.session import session_scope
from app.security.cookies import CSRF_COOKIE, SESSION_COOKIE, clear_session_cookies, set_session_cookies
from app.security.deps import CurrentUser
from app.security.identity import derive_user_id
from app.security.oidc import OidcClient, generate_pkce_pair, tokens_to_session_data
from app.security.sessions import SessionStore
from app.services import audit

router = APIRouter(prefix="/auth", tags=["auth"])
logger = get_logger(__name__)

# SPA route the browser lands on after Keycloak's end-session redirect. Must be
# in the client's post.logout.redirect.uris (deploy/keycloak/bootstrap.sh).
SIGNED_OUT_PATH = "signed-out"


def _store(request: Request) -> SessionStore:
    return request.app.state.session_store


@router.get("/login")
async def auth_login(
    request: Request,
    next: str = Query(default="/"),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    oidc = OidcClient(settings)
    store = _store(request)

    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    verifier, challenge = generate_pkce_pair()
    redirect_uri = str(request.url_for("auth_callback"))

    await store.store_oauth_state(
        state, {"nonce": nonce, "verifier": verifier, "next": next, "redirect_uri": redirect_uri}
    )
    return RedirectResponse(oidc.build_authorize_url(redirect_uri, state, nonce, challenge))


@router.get("/callback", name="auth_callback")
async def auth_callback(
    request: Request,
    code: str,
    state: str,
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    store = _store(request)
    oidc = OidcClient(settings)

    saved = await store.pop_oauth_state(state)
    if saved is None:
        raise UnauthorizedError("Invalid or expired OAuth state")

    token_response = await oidc.exchange_code(code, saved["redirect_uri"], saved["verifier"])
    session_data = await tokens_to_session_data(token_response)
    principal = oidc.validate_access_token(session_data.access_token)
    session_data.sub = principal.sub
    session_data.tenant_id = str(principal.tenant_id)

    session_id = await store.create(session_data)

    response = RedirectResponse(saved.get("next") or "/")
    set_session_cookies(response, settings, session_id, session_data.csrf_token)

    # auth_callback runs before AuthContextMiddleware has anything to bind
    # (this IS what establishes the session), so it opens a DB session
    # against an explicit context rather than the normal get_session() dep.
    login_ctx = RequestContext(
        tenant_id=principal.tenant_id,
        user_id=derive_user_id(principal.sub),
        sub=principal.sub,
        roles=principal.roles,
        acr=principal.acr,
        auth_time=principal.auth_time,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        request_id=getattr(request.state, "request_id", None),
    )
    async with session_scope(login_ctx) as db_session:
        await audit.record(
            db_session, login_ctx, action=AuditAction.LOGIN, entity_type="user", entity_id=principal.sub
        )
    return response


@router.post("/logout")
async def auth_logout(
    request: Request,
    # Sent as a form field, not the X-CSRF-Token header: sign-out is a
    # top-level browser form POST (so the browser itself follows the redirect
    # chain through Keycloak's end-session endpoint), and a form cannot set
    # request headers. This route is in PUBLIC_PREFIXES so the CSRF
    # middleware skips it -- the double-submit check is done here instead,
    # whenever a session cookie is present.
    csrf_token: str = Form(default=""),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    """Ends the session everywhere: (1) back-channel POST to Keycloak's logout
    endpoint with the stored refresh token + client credentials, which ends
    the user's SSO session server-side; (2) revokes our own Redis session and
    clears both cookies; (3) 303s the browser (303, NOT 307 -- a 307 would
    re-POST the body to Keycloak's GET-style end-session endpoint) to
    Keycloak's end-session URL with id_token_hint + post_logout_redirect_uri,
    so the browser's own SSO cookies are cleared too and it lands on the SPA's
    signed-out page. The next sign-in therefore asks for username + password
    again instead of silently reusing the SSO session."""
    store = _store(request)
    oidc = OidcClient(settings)
    session_id = request.cookies.get(SESSION_COOKIE)
    post_logout_uri = f"{request.base_url}{SIGNED_OUT_PATH}"
    id_token = ""

    if session_id:
        cookie_csrf = request.cookies.get(CSRF_COOKIE, "")
        if not cookie_csrf or not hmac.compare_digest(cookie_csrf, csrf_token):
            raise ForbiddenError("CSRF token missing or invalid")
        data = await store.get(session_id)
        if data:
            id_token = data.id_token
            if data.refresh_token:
                try:
                    await oidc.backchannel_logout(data.refresh_token)
                except httpx.HTTPError as exc:
                    # Best-effort: the front-channel redirect below ends the
                    # same SSO session via id_token_hint, and our own session
                    # is revoked regardless.
                    logger.warning("keycloak_backchannel_logout_failed", error=str(exc))
        await store.revoke(session_id)

    logout_url = oidc.rp_initiated_logout_url(id_token, post_logout_uri) if id_token else post_logout_uri
    response = RedirectResponse(logout_url, status_code=303)
    clear_session_cookies(response, settings)
    return response


@router.get("/me")
async def auth_me(ctx: RequestContext = CurrentUser, settings: Settings = Depends(get_settings)) -> dict:
    return {
        "sub": ctx.sub,
        "username": ctx.username,
        "tenant_id": str(ctx.tenant_id),
        "roles": sorted(ctx.roles),
        "acr": ctx.acr,
        # Drives the frontend's "DEV: MFA disabled" banner; only ever true in
        # dev/test (config.mfa_bypass_active).
        "mfa_disabled_dev": mfa_bypass_active(settings),
    }


@router.get("/step-up")
async def auth_step_up(
    request: Request,
    next: str = Query(default="/"),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    """Redirects to Keycloak with acr_values=silver + prompt=login so the
    user re-authenticates (TOTP) immediately before a sensitive action, e.g.
    an approval decision. See security/deps.py::require_mfa_step_up."""
    oidc = OidcClient(settings)
    store = _store(request)

    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    verifier, challenge = generate_pkce_pair()
    redirect_uri = str(request.url_for("auth_callback"))

    await store.store_oauth_state(
        state, {"nonce": nonce, "verifier": verifier, "next": next, "redirect_uri": redirect_uri}
    )
    url = oidc.build_authorize_url(
        redirect_uri, state, nonce, challenge, acr_values=settings.required_acr_for_approval
    )
    return RedirectResponse(url)
