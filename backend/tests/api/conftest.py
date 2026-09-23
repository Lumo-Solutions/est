from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture
async def client(app_engine, postgres_container, redis_container) -> AsyncIterator[AsyncClient]:
    """httpx client driving the real FastAPI app over ASGI (no real network
    socket). The OIDC handshake itself is exercised for real in
    tests/unit/test_jwt_validation.py and was manually verified end-to-end
    against a live Keycloak during development (see docs/keycloak-setup.md);
    these API tests go through the REAL AuthContextMiddleware with
    TokenValidator.validate() patched (see authed_client below) rather than
    overriding a route dependency, because get_session() reads the
    RequestContext ContextVar directly rather than via Depends(...) --
    overriding just the get_current_context dependency doesn't reach it."""
    import os

    os.environ.setdefault("KEYCLOAK_CLIENT_SECRET", "test")
    os.environ.setdefault("SESSION_SECRET", "test-session-secret")
    os.environ.setdefault("AUDIT_CHECKPOINT_HMAC_KEY", "test-hmac-key")
    os.environ.setdefault("S3_ENDPOINT", "http://s3.invalid")
    os.environ.setdefault("VLLM_API_BASE", "http://vllm.invalid/v1")
    os.environ["REDIS_URL"] = redis_container

    import app.db.session as db_session_module
    from app.core.config import get_settings
    from app.main import create_app

    # get_settings()/get_app_engine() are @lru_cache'd, and _session_factory()
    # lazily caches an async_sessionmaker bound to whatever engine existed
    # the first time it ran. postgres_container just set APP_DATABASE_URL/
    # MIGRATOR_DATABASE_URL in os.environ, so all three must be reset or the
    # app under test would silently reuse a stale engine/DSN from an earlier
    # test module.
    get_settings.cache_clear()
    db_session_module.get_app_engine.cache_clear()
    db_session_module._app_session_factory = None
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.fixture
def authed_client(client, monkeypatch):
    """Patches TokenValidator.validate so any `Authorization: Bearer ...`
    header is accepted and resolves to a canned Principal for the given
    roles -- this runs through the real AuthContextMiddleware, so both
    CurrentUser-based routes and get_session()'s direct ContextVar read see
    a consistent RequestContext, unlike overriding the FastAPI dependency
    alone."""
    import uuid

    from app.security.jwt import Principal, TokenValidator

    def _as(roles: frozenset[str], *, acr: str | None = None):
        tenant_id = uuid.UUID("8f14e45f-ceea-4e97-8d0c-3d3b3f3c1a00")
        sub = str(uuid.uuid4())
        principal = Principal(
            sub=sub, tenant_id=tenant_id, email=None, roles=roles, acr=acr, amr=[], sid=None, exp=0
        )
        monkeypatch.setattr(TokenValidator, "validate", lambda self, token: principal)
        client.headers["Authorization"] = "Bearer test-token"
        return client

    return _as
