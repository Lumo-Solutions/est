"""Settings validators not already covered by their own dedicated test file
(test_step_up.py covers DEV_DISABLE_MFA/_refuse_mfa_bypass_outside_dev_test).

PRODUCTION_MODE (fix/prod-app-env): deploy/docker-compose.prod.yml sets both
APP_ENV=production and PRODUCTION_MODE=true (literal values) for every
backend-family service. This is the backend-side half of that hardening --
same fail-closed-at-construction pattern as DEV_DISABLE_MFA's own validator.
"""

from __future__ import annotations

import pytest

from app.core.config import Settings

_REQUIRED = {
    "APP_DATABASE_URL": "postgresql://x/y",
    "MIGRATOR_DATABASE_URL": "postgresql://x/y",
    "S3_ENDPOINT": "http://s3.test",
    "VLLM_API_BASE": "http://vllm.internal:8000/v1",
}


def _settings(**overrides) -> Settings:
    return Settings(**_REQUIRED, **overrides)


def test_production_mode_off_by_default_never_refuses_to_start():
    s = _settings()
    assert s.production_mode is False
    assert s.app_env == "dev"


@pytest.mark.parametrize("app_env", ["dev", "test", "staging", "", None])
def test_production_mode_refuses_to_start_without_app_env_production(app_env):
    overrides = {"PRODUCTION_MODE": True}
    if app_env is not None:
        overrides["APP_ENV"] = app_env
    with pytest.raises(ValueError, match="PRODUCTION_MODE"):
        _settings(**overrides)


def test_production_mode_true_with_app_env_production_starts_fine():
    s = _settings(PRODUCTION_MODE=True, APP_ENV="production")
    assert s.production_mode is True
    assert s.app_env == "production"


def test_app_env_production_alone_without_production_mode_is_untouched():
    """PRODUCTION_MODE defaults to False -- an operator running APP_ENV=
    production without the compose overlay's PRODUCTION_MODE flag (e.g. a
    bare `docker compose up` with APP_ENV set by hand) is unaffected by
    this validator; it only ever fires when PRODUCTION_MODE is explicitly
    true."""
    s = _settings(APP_ENV="production")
    assert s.production_mode is False
