from __future__ import annotations

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


def require_mfa_step_up(
    settings: Settings = Depends(get_settings),
) -> Callable[[RequestContext], RequestContext]:
    def _check(ctx: RequestContext = CurrentUser) -> RequestContext:
        required = settings.required_acr_for_approval
        current_rank = _ACR_RANK.get(ctx.acr or "", 0)
        required_rank = _ACR_RANK.get(required, 2)
        if current_rank < required_rank:
            raise StepUpRequiredError(
                "This action requires a recent MFA step-up authentication",
                required_acr=required,
            )
        return ctx

    return _check
