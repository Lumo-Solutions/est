from __future__ import annotations

import time
from collections.abc import Callable

from fastapi import Depends

from app.core.config import Settings, get_settings
from app.core.context import RequestContext, try_current_context
from app.core.errors import ForbiddenError, StepUpRequiredError, UnauthorizedError


def get_current_context() -> RequestContext:
    ctx = try_current_context()
    if ctx is None:
        raise UnauthorizedError("Authentication required")
    return ctx


CurrentUser = Depends(get_current_context)


def require_roles(*roles: str) -> Callable[[RequestContext], RequestContext]:
    def _check(ctx: RequestContext = CurrentUser) -> RequestContext:
        if not ctx.has_role(*roles):
            raise ForbiddenError(
                f"Requires one of roles: {', '.join(roles)}", required_roles=list(roles)
            )
        return ctx

    return _check


_ACR_RANK = {"bronze": 1, "silver": 2}


def has_recent_step_up(ctx: RequestContext, settings: Settings) -> bool:
    """acr alone isn't enough: a still-valid session/token can go on
    reporting acr=silver (via cookie reattachment or a refresh_token grant)
    long after the OTP entry that actually earned it -- see
    Settings.step_up_max_age_s's own comment. This also requires the
    underlying auth_time (the real authentication event, not this token's
    own issued-at) to be within that window. The single check every
    step-up-guarded action (approvals.decide, procurement's prequalification
    override, this module's own require_mfa_step_up dependency) should use,
    so there's one place to get the "acr AND recency" logic right instead of
    three copies that could quietly drift apart -- see fix/keycloak-step-up.
    """
    required = settings.required_acr_for_approval
    current_rank = _ACR_RANK.get(ctx.acr or "", 0)
    required_rank = _ACR_RANK.get(required, 2)
    if current_rank < required_rank:
        return False
    if ctx.auth_time is None:
        return False
    return (time.time() - ctx.auth_time) <= settings.step_up_max_age_s


def require_mfa_step_up(
    settings: Settings = Depends(get_settings),
) -> Callable[[RequestContext], RequestContext]:
    def _check(ctx: RequestContext = CurrentUser) -> RequestContext:
        if not has_recent_step_up(ctx, settings):
            raise StepUpRequiredError(
                "This action requires a recent MFA step-up authentication",
                required_acr=settings.required_acr_for_approval,
            )
        return ctx

    return _check
