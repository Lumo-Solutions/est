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
