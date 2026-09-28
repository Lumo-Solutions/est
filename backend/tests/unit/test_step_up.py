"""has_recent_step_up (app/security/deps.py) is the single acr-AND-recency
check every step-up-guarded action (approvals.decide, procurement RFQ
dispatch) shares -- see fix/keycloak-step-up's build-log entry for why acr
alone isn't enough (a still-valid session/token can go on reporting
acr=silver long after the OTP entry that actually earned it).
"""

from __future__ import annotations

import time
import uuid

import pytest
from structlog.testing import capture_logs

from app.core.config import Settings, mfa_bypass_active
from app.core.context import RequestContext
from app.security.deps import has_recent_step_up, mfa_audit_payload, step_up_bypassed

TENANT_ID = uuid.uuid4()


@pytest.fixture
def settings() -> Settings:
    return Settings(
        APP_DATABASE_URL="postgresql://x/y",
        MIGRATOR_DATABASE_URL="postgresql://x/y",
        S3_ENDPOINT="http://s3.test",
        VLLM_API_BASE="http://vllm.internal:8000/v1",
    )


def _ctx(*, acr: str | None, auth_time: int | None) -> RequestContext:
    return RequestContext(tenant_id=TENANT_ID, user_id=uuid.uuid4(), sub="user-1", acr=acr, auth_time=auth_time)


def test_bronze_is_never_enough(settings: Settings):
    ctx = _ctx(acr="bronze", auth_time=int(time.time()))
    assert has_recent_step_up(ctx, settings) is False


def test_no_acr_at_all_is_never_enough(settings: Settings):
    ctx = _ctx(acr=None, auth_time=int(time.time()))
    assert has_recent_step_up(ctx, settings) is False


def test_silver_with_fresh_auth_time_is_enough(settings: Settings):
    ctx = _ctx(acr="silver", auth_time=int(time.time()) - 10)
    assert has_recent_step_up(ctx, settings) is True


def test_silver_just_inside_the_max_age_boundary_is_enough(settings: Settings):
    # max_age_s - 1, not exactly max_age_s: the check itself runs a moment
    # after auth_time is computed here, so asserting the razor's-edge exact
    # boundary would be flaky by a fraction of a second, not a real
    # difference in behaviour.
    ctx = _ctx(acr="silver", auth_time=int(time.time()) - settings.step_up_max_age_s + 1)
    assert has_recent_step_up(ctx, settings) is True


def test_silver_with_stale_auth_time_requires_step_up_again(settings: Settings):
    # A still-valid session/token can go on reporting acr=silver long after
    # the OTP entry that earned it (cookie reattachment, a refresh_token
    # grant) -- this is exactly the gap acr-only checking had.
    ctx = _ctx(acr="silver", auth_time=int(time.time()) - settings.step_up_max_age_s - 1)
    assert has_recent_step_up(ctx, settings) is False


def test_silver_with_no_auth_time_claim_requires_step_up(settings: Settings):
    # Defensive: a token somehow missing auth_time can't prove recency, so
    # this must fail closed, not treat "unknown" as "fine".
    ctx = _ctx(acr="silver", auth_time=None)
    assert has_recent_step_up(ctx, settings) is False


# --- DEV_DISABLE_MFA (dev/test-only bypass) ----------------------------------

_REQUIRED = {
    "APP_DATABASE_URL": "postgresql://x/y",
    "MIGRATOR_DATABASE_URL": "postgresql://x/y",
    "S3_ENDPOINT": "http://s3.test",
    "VLLM_API_BASE": "http://vllm.internal:8000/v1",
}


def _settings(**overrides) -> Settings:
    return Settings(**_REQUIRED, **overrides)


@pytest.mark.parametrize("env", ["dev", "test"])
def test_bypass_passes_without_a_step_up_in_dev_and_test(env: str):
    s = _settings(APP_ENV=env, DEV_DISABLE_MFA=True)
    assert mfa_bypass_active(s) is True
    assert has_recent_step_up(_ctx(acr="bronze", auth_time=None), s) is True
    assert step_up_bypassed(_ctx(acr="bronze", auth_time=None), s) is True
    assert mfa_audit_payload(_ctx(acr="bronze", auth_time=None), s) == {"mfa_bypassed_dev": True}


def test_bypass_is_logged_at_warning():
    s = _settings(APP_ENV="dev", DEV_DISABLE_MFA=True)
    with capture_logs() as logs:
        has_recent_step_up(_ctx(acr="bronze", auth_time=None), s)
    assert [(e["event"], e["log_level"]) for e in logs] == [("mfa_step_up_bypassed", "warning")]


def test_bypass_off_by_default_still_requires_a_real_step_up():
    s = _settings(APP_ENV="dev")
    assert s.dev_disable_mfa is False
    assert mfa_bypass_active(s) is False
    assert has_recent_step_up(_ctx(acr="bronze", auth_time=int(time.time())), s) is False
    assert mfa_audit_payload(_ctx(acr="bronze", auth_time=None), s) == {}


def test_genuine_step_up_is_not_marked_as_bypassed_even_with_the_switch_on():
    s = _settings(APP_ENV="dev", DEV_DISABLE_MFA=True)
    ctx = _ctx(acr="silver", auth_time=int(time.time()))
    with capture_logs() as logs:
        assert has_recent_step_up(ctx, s) is True
    assert logs == []
    assert step_up_bypassed(ctx, s) is False
    assert mfa_audit_payload(ctx, s) == {}


@pytest.mark.parametrize("env", ["production", "prod", "staging", "DEV", ""])
def test_backend_refuses_to_start_with_mfa_off_outside_dev_test(env: str):
    with pytest.raises(ValueError, match="DEV_DISABLE_MFA"):
        _settings(APP_ENV=env, DEV_DISABLE_MFA=True)


def test_backend_refuses_mfa_off_when_app_env_is_unset(monkeypatch: pytest.MonkeyPatch):
    # app_env defaults to "dev", but the bypass needs APP_ENV set explicitly.
    monkeypatch.delenv("APP_ENV", raising=False)
    with pytest.raises(ValueError, match="DEV_DISABLE_MFA"):
        _settings(DEV_DISABLE_MFA=True)


def test_mfa_off_env_var_alone_is_harmless_when_false_outside_dev_test():
    assert mfa_bypass_active(_settings(APP_ENV="production", DEV_DISABLE_MFA=False)) is False
