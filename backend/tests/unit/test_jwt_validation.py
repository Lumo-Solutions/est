"""Exercises TokenValidator.validate()'s real claim-checking logic (audience,
issuer, algorithm allowlist, tenant_id extraction, azp check, role mapping)
against tokens minted with a throwaway RSA keypair. JWKS network resolution
itself is monkeypatched out -- PyJWKClient's HTTP fetch is not what this
suite is testing; app/security/jwt.py's own claim logic is.
"""

from __future__ import annotations

import time
import uuid
from types import SimpleNamespace

import jwt
import pytest

from app.core.config import Settings
from app.security.jwt import TokenValidationError, TokenValidator

ISSUER = "http://keycloak.test/realms/installtec"
AUDIENCE = "installtec-backend"
TENANT_ID = "8f14e45f-ceea-4e97-8d0c-3d3b3f3c1a00"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        APP_DATABASE_URL="postgresql://x/y",
        MIGRATOR_DATABASE_URL="postgresql://x/y",
        S3_ENDPOINT="http://s3.test",
        VLLM_API_BASE="http://vllm.internal:8000/v1",
        KEYCLOAK_BASE_URL="http://keycloak.test",
        KEYCLOAK_PUBLIC_URL="http://keycloak.test",
        KEYCLOAK_REALM="installtec",
        KEYCLOAK_AUDIENCE=AUDIENCE,
    )


@pytest.fixture
def validator(settings, rsa_keypair, monkeypatch) -> TokenValidator:
    private_key, public_key = rsa_keypair
    v = TokenValidator(settings)
    monkeypatch.setattr(v, "_signing_key", lambda token: SimpleNamespace(key=public_key))
    return v


def _mint(private_key, *, claims_override: dict | None = None) -> str:
    now = int(time.time())
    claims = {
        "sub": str(uuid.uuid4()),
        "iss": ISSUER,
        "aud": AUDIENCE,
        "azp": "installtec-backend",
        "iat": now,
        "exp": now + 300,
        "tenant_id": TENANT_ID,
        "realm_access": {"roles": ["lead_estimator", "offline_access"]},
        "acr": "bronze",
    }
    claims.update(claims_override or {})
    return jwt.encode(claims, private_key, algorithm="RS256")


def test_valid_token_returns_principal(validator, rsa_keypair):
    private_key, _ = rsa_keypair
    token = _mint(private_key)
    principal = validator.validate(token)
    assert str(principal.tenant_id) == TENANT_ID
    assert principal.roles == frozenset({"lead_estimator"})
    assert principal.acr == "bronze"


def test_expired_token_rejected(validator, rsa_keypair):
    private_key, _ = rsa_keypair
    token = _mint(private_key, claims_override={"exp": int(time.time()) - 3600, "iat": int(time.time()) - 7200})
    with pytest.raises(TokenValidationError, match="expired"):
        validator.validate(token)


def test_wrong_audience_rejected(validator, rsa_keypair):
    private_key, _ = rsa_keypair
    token = _mint(private_key, claims_override={"aud": "some-other-client"})
    with pytest.raises(TokenValidationError):
        validator.validate(token)


def test_wrong_issuer_rejected(validator, rsa_keypair):
    private_key, _ = rsa_keypair
    token = _mint(private_key, claims_override={"iss": "http://evil.test/realms/installtec"})
    with pytest.raises(TokenValidationError):
        validator.validate(token)


def test_missing_tenant_id_rejected(validator, rsa_keypair):
    private_key, _ = rsa_keypair
    now = int(time.time())
    claims = {
        "sub": str(uuid.uuid4()), "iss": ISSUER, "aud": AUDIENCE, "azp": "installtec-backend",
        "iat": now, "exp": now + 300, "realm_access": {"roles": ["lead_estimator"]},
    }
    token = jwt.encode(claims, private_key, algorithm="RS256")
    with pytest.raises(TokenValidationError, match="tenant_id"):
        validator.validate(token)


def test_non_uuid_tenant_id_rejected(validator, rsa_keypair):
    private_key, _ = rsa_keypair
    token = _mint(private_key, claims_override={"tenant_id": "not-a-uuid"})
    with pytest.raises(TokenValidationError, match="tenant_id"):
        validator.validate(token)


def test_unexpected_azp_rejected(validator, rsa_keypair):
    private_key, _ = rsa_keypair
    token = _mint(private_key, claims_override={"azp": "some-random-client"})
    with pytest.raises(TokenValidationError, match="authorized party"):
        validator.validate(token)


def test_unknown_realm_roles_are_dropped(validator, rsa_keypair):
    private_key, _ = rsa_keypair
    token = _mint(private_key, claims_override={"realm_access": {"roles": ["platform_admin", "some_role"]}})
    principal = validator.validate(token)
    assert principal.roles == frozenset()


def test_alg_none_is_rejected(validator, rsa_keypair):
    """PyJWT itself refuses alg=none when the caller passes an explicit
    algorithms=["RS256"] allowlist -- this asserts that guarantee holds for
    the way TokenValidator actually calls jwt.decode()."""
    now = int(time.time())
    claims = {
        "sub": str(uuid.uuid4()), "iss": ISSUER, "aud": AUDIENCE, "azp": "installtec-backend",
        "iat": now, "exp": now + 300, "tenant_id": TENANT_ID, "realm_access": {"roles": []},
    }
    forged = jwt.encode(claims, key="", algorithm="none")
    with pytest.raises(TokenValidationError):
        validator.validate(forged)
