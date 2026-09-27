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

from app.core.config import Settings
from app.core.context import RequestContext
from app.security.deps import has_recent_step_up

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
