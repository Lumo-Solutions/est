"""SRS Module C1 change #1: no non-production config may resolve an RFQ
email's recipient to a real vendor address. See
app/procurement/mailer.py::resolve_recipient and docs/procurement-rfq.md."""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.procurement.mailer import EmailMisconfiguredError, resolve_recipient

_REQUIRED = dict(
    APP_DATABASE_URL="postgresql://x/y",
    MIGRATOR_DATABASE_URL="postgresql://x/y",
    S3_ENDPOINT="http://s3.test",
    VLLM_API_BASE="http://vllm.internal:8000/v1",
)


def _settings(**overrides: object) -> Settings:
    return Settings(**_REQUIRED, **overrides)  # type: ignore[arg-type]


@pytest.mark.parametrize("app_env", ["dev", "staging", "test", "qa", "local", ""])
def test_every_non_production_env_redirects_to_the_safety_address(app_env: str) -> None:
    settings = _settings(APP_ENV=app_env, EMAIL_REDIRECT_ALL_TO="dev-catchall@installtec.local")
    resolved = resolve_recipient("real-vendor@example.com", settings)
    assert resolved.to_address == "dev-catchall@installtec.local"
    assert resolved.original_to == "real-vendor@example.com"
    assert resolved.to_address != "real-vendor@example.com"


@pytest.mark.parametrize("app_env", ["dev", "staging", "test", "", "PRODUCTION", "Production"])
def test_missing_redirect_address_fails_closed_never_falls_through_to_vendor(app_env: str) -> None:
    """Only the exact literal 'production' bypasses the redirect requirement
    -- anything else (including a near-miss like 'PRODUCTION') must either
    redirect or refuse outright, never silently email the vendor."""
    settings = _settings(APP_ENV=app_env, EMAIL_REDIRECT_ALL_TO="")
    with pytest.raises(EmailMisconfiguredError):
        resolve_recipient("real-vendor@example.com", settings)


def test_production_sends_directly_to_the_vendor() -> None:
    settings = _settings(APP_ENV="production", EMAIL_REDIRECT_ALL_TO="")
    resolved = resolve_recipient("real-vendor@example.com", settings)
    assert resolved.to_address == "real-vendor@example.com"
    assert resolved.original_to is None


def test_production_ignores_a_leftover_redirect_setting() -> None:
    settings = _settings(APP_ENV="production", EMAIL_REDIRECT_ALL_TO="dev-catchall@installtec.local")
    resolved = resolve_recipient("real-vendor@example.com", settings)
    assert resolved.to_address == "real-vendor@example.com"
    assert resolved.original_to is None
