from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse

from app.core.config import Settings, get_settings
from app.core.context import RequestContext
from app.core.enums import AuditAction
from app.core.errors import UnauthorizedError
from app.db.session import session_scope
from app.security.cookies import SESSION_COOKIE, clear_session_cookies, set_session_cookies
from app.security.deps import CurrentUser
from app.security.identity import derive_user_id
from app.security.oidc import OidcClient, generate_pkce_pair, tokens_to_session_data
from app.security.sessions import SessionStore
from app.services import audit

router = APIRouter(prefix="/auth", tags=["auth"])


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
async def auth_logout(request: Request, settings: Settings = Depends(get_settings)) -> RedirectResponse:
    store = _store(request)
    session_id = request.cookies.get(SESSION_COOKIE)
    id_token = ""
    if session_id:
        data = await store.get(session_id)
        if data:
            id_token = data.id_token
        await store.revoke(session_id)

    oidc = OidcClient(settings)
    post_logout_uri = str(request.base_url)
    logout_url = oidc.rp_initiated_logout_url(id_token, post_logout_uri) if id_token else post_logout_uri
    response = RedirectResponse(logout_url)
    clear_session_cookies(response)
    return response


@router.get("/me")
async def auth_me(ctx: RequestContext = CurrentUser) -> dict:
    return {
        "sub": ctx.sub,
        "tenant_id": str(ctx.tenant_id),
        "roles": sorted(ctx.roles),
        "acr": ctx.acr,
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
