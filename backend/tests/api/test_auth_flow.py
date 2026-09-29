"""These hit the real AuthContextMiddleware/CsrfMiddleware/exception-handler
chain with no dependency overrides -- exactly the 401 paths manually
verified against a live container during development (see the "unauthorized
GET /vendors" and "/auth/me" checks in the session history). Route business
logic with an authenticated context is covered in test_vendors_api.py etc.
via the authed_client override.
"""

from __future__ import annotations

import pytest
import structlog.testing

pytestmark = pytest.mark.asyncio


async def test_healthz_is_public(client):
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_protected_route_without_token_returns_401_problem_json(client):
    resp = await client.get("/api/v1/vendors")
    assert resp.status_code == 401
    body = resp.json()
    assert body["type"] == "urn:installtec:unauthorized"
    assert body["status"] == 401


async def test_auth_me_without_token_returns_401(client):
    """Regression test: /auth/me previously fell under a blanket
    `/api/v1/auth/` public-prefix exemption that also (incorrectly) skipped
    authentication for this endpoint, which actually needs it."""
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401


async def test_auth_me_returns_the_login_name_for_display(authed_client):
    """The header shows a name, not the Keycloak subject UUID."""
    client = authed_client(frozenset({"estimator"}), username="estimator1")
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] == "estimator1"
    assert body["sub"] != "estimator1"


async def test_auth_me_username_is_null_when_the_token_has_none(authed_client):
    client = authed_client(frozenset({"estimator"}))
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 200
    assert resp.json()["username"] is None


async def test_auth_login_is_public_and_redirects(client):
    resp = await client.get("/api/v1/auth/login", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert "location" in resp.headers


async def test_malformed_bearer_token_returns_401(client):
    resp = await client.get("/api/v1/vendors", headers={"Authorization": "Bearer not-a-real-jwt"})
    assert resp.status_code == 401


async def test_malformed_bearer_token_logs_rejection_without_token_value(client):
    """Regression test for the silently-swallowed TokenValidationError in
    AuthContextMiddleware._resolve_context, which previously hid a
    missing-`sub`-claim bug entirely. The rejection reason must be logged,
    but never the raw token or any claim values."""
    bad_token = "not-a-real-jwt"
    with structlog.testing.capture_logs() as captured:
        resp = await client.get(
            "/api/v1/vendors", headers={"Authorization": f"Bearer {bad_token}"}
        )

    assert resp.status_code == 401

    rejection_events = [e for e in captured if e.get("event") == "auth.bearer_token_rejected"]
    assert len(rejection_events) == 1
    event = rejection_events[0]
    assert event["log_level"] == "warning"
    assert "reason" in event
    assert "path" in event
    assert event["path"] == "/api/v1/vendors"

    serialized = repr(captured)
    assert bad_token not in serialized


async def test_openapi_schema_is_generated(client):
    resp = await client.get("/openapi.json")
    assert resp.status_code == 200
    schema = resp.json()
    assert schema["info"]["title"] == "INSTALLTEC AI Platform API"
    assert "/api/v1/vendors" in schema["paths"]


# --- POST /auth/logout ------------------------------------------------------
# The real Keycloak round trip (SSO session actually ended, next sign-in asks
# for a password again) is proven by frontend/e2e/real-backend/logout.spec.ts;
# these pin the server-side contract: 303 (not 307), back-channel call, session
# revoked, cookies cleared with Secure, CSRF enforced, id_token_hint present.

import time
from urllib.parse import parse_qs, urlparse

import httpx

from app.security.oidc import OidcClient
from app.security.sessions import SessionData


def _session(**overrides) -> SessionData:
    base = dict(
        sub="sub-1",
        tenant_id="8f14e45f-ceea-4e97-8d0c-3d3b3f3c1a00",
        access_token="access",
        refresh_token="refresh-tok",
        id_token="id-tok",
        access_expires_at=time.time() + 300,
        refresh_expires_at=time.time() + 1800,
        csrf_token="csrf-abc",
    )
    base.update(overrides)
    return SessionData(**base)


def _cookie(session_id: str, csrf: str = "csrf-abc") -> dict[str, str]:
    return {"Cookie": f"__Host-ins_sid={session_id}; __Host-ins_csrf={csrf}"}


def _store_of(client):
    return client._transport.app.state.session_store


async def test_logout_ends_the_session_and_303s_to_keycloak_end_session(client, monkeypatch):
    store = _store_of(client)
    session_id = await store.create(_session())
    calls: list[str] = []

    async def fake_backchannel(self, refresh_token: str) -> None:
        calls.append(refresh_token)

    monkeypatch.setattr(OidcClient, "backchannel_logout", fake_backchannel)

    resp = await client.post(
        "/api/v1/auth/logout", data={"csrf_token": "csrf-abc"}, headers=_cookie(session_id), follow_redirects=False
    )

    assert resp.status_code == 303  # NOT 307: a 307 would re-POST the form to Keycloak
    assert calls == ["refresh-tok"]  # back-channel logout used the stored refresh token
    assert await store.get(session_id) is None  # our own session is revoked

    url = urlparse(resp.headers["location"])
    assert url.path.endswith("/protocol/openid-connect/logout")
    q = parse_qs(url.query)
    assert q["id_token_hint"] == ["id-tok"]
    assert q["post_logout_redirect_uri"] == ["http://test/signed-out"]

    # Both __Host- cookies are expired, and with Secure (browsers ignore a
    # __Host- deletion that lacks it).
    set_cookies = resp.headers.get_list("set-cookie")
    for name in ("__Host-ins_sid", "__Host-ins_csrf"):
        line = next(c for c in set_cookies if c.startswith(name + "="))
        assert "Max-Age=0" in line or "expires=" in line.lower()
        assert "Secure" in line


async def test_logout_still_completes_when_the_keycloak_back_channel_call_fails(client, monkeypatch):
    store = _store_of(client)
    session_id = await store.create(_session())

    async def boom(self, refresh_token: str) -> None:
        raise httpx.ConnectError("keycloak unreachable")

    monkeypatch.setattr(OidcClient, "backchannel_logout", boom)

    resp = await client.post(
        "/api/v1/auth/logout", data={"csrf_token": "csrf-abc"}, headers=_cookie(session_id), follow_redirects=False
    )

    assert resp.status_code == 303
    assert await store.get(session_id) is None  # revoked regardless
    assert "id_token_hint=id-tok" in resp.headers["location"]  # front-channel still ends the SSO session


async def test_logout_rejects_a_missing_or_wrong_csrf_token_and_keeps_the_session(client, monkeypatch):
    store = _store_of(client)
    session_id = await store.create(_session())
    called = False

    async def fake_backchannel(self, refresh_token: str) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(OidcClient, "backchannel_logout", fake_backchannel)

    for form in ({}, {"csrf_token": "wrong"}):
        resp = await client.post(
            "/api/v1/auth/logout", data=form, headers=_cookie(session_id), follow_redirects=False
        )
        assert resp.status_code == 403

    assert called is False
    assert await store.get(session_id) is not None  # a forged cross-site POST cannot log the user out


async def test_logout_without_a_session_is_idempotent_and_lands_on_the_signed_out_page(client):
    resp = await client.post("/api/v1/auth/logout", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "http://test/signed-out"


async def test_logout_with_a_session_that_has_no_refresh_token_skips_the_back_channel(client, monkeypatch):
    store = _store_of(client)
    session_id = await store.create(_session(refresh_token=""))
    called = False

    async def fake_backchannel(self, refresh_token: str) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(OidcClient, "backchannel_logout", fake_backchannel)
    resp = await client.post(
        "/api/v1/auth/logout", data={"csrf_token": "csrf-abc"}, headers=_cookie(session_id), follow_redirects=False
    )
    assert resp.status_code == 303
    assert called is False
    assert await store.get(session_id) is None
