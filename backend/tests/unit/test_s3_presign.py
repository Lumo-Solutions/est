"""Phase 8b: presign_get_url must be built against s3_public_endpoint, not
s3_endpoint -- a presigned URL handed to a real browser is only reachable
if built against a host the browser can resolve (s3_endpoint, e.g.
"http://seaweedfs:8333", only resolves inside the compose network). The
client's endpoint_url is baked into both the URL's host and its signature,
so this can't be fixed by rewriting the URL after signing.
generate_presigned_url is a pure local computation (no network call), so
no real S3/SeaweedFS service is needed to test it. See
docs/module-frontend-phase8b-plan.md and app/integrations/s3.py."""

from __future__ import annotations

from urllib.parse import urlparse

import pytest

from app.core.config import Settings
from app.integrations.s3 import presign_get_url

pytestmark = pytest.mark.asyncio


def _settings(**overrides) -> Settings:
    defaults = dict(
        DATABASE_URL="postgresql://x/y",
        APP_DATABASE_URL="postgresql+asyncpg://x/y",
        MIGRATOR_DATABASE_URL="postgresql+asyncpg://x/y",
        S3_ENDPOINT="http://seaweedfs:8333",
        S3_PUBLIC_ENDPOINT="http://localhost:8333",
        S3_ACCESS_KEY="test",
        S3_SECRET_KEY="test",
        VLLM_API_BASE="http://vllm.invalid/v1",
        KEYCLOAK_CLIENT_SECRET="test",
        SESSION_SECRET="test-session-secret",
        AUDIT_CHECKPOINT_HMAC_KEY="test-hmac-key",
        **overrides,
    )
    return Settings(**defaults)


async def test_presigned_url_is_signed_against_the_public_endpoint_not_the_internal_one():
    settings = _settings()
    url = await presign_get_url("projects/x/drawings/y.pdf", settings=settings)
    assert urlparse(url).netloc == "localhost:8333"


async def test_presigned_url_carries_a_signature_query_string():
    settings = _settings()
    url = await presign_get_url("projects/x/drawings/y.pdf", settings=settings)
    query = urlparse(url).query
    assert "Signature=" in query
    assert "Expires=" in query
