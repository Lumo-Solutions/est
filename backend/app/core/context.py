from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from uuid import UUID


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Everything downstream code (RLS GUCs, audit events, service checks)
    needs about the authenticated caller. Built once by AuthContextMiddleware
    (or workers/base.py for Celery tasks) and read via ContextVar everywhere
    else so services never have to thread it through every call."""

    tenant_id: UUID
    user_id: UUID | None
    sub: str | None
    roles: frozenset[str] = field(default_factory=frozenset)
    acr: str | None = None
    # Epoch seconds of the underlying authentication EVENT (OIDC's
    # standard auth_time claim), not when the current token was issued --
    # see app/security/deps.py::has_recent_step_up for why this, not acr
    # alone, is what a step-up check must verify recency against.
    auth_time: int | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    request_id: str | None = None
    is_system: bool = False

    def has_role(self, *roles: str) -> bool:
        return bool(self.roles.intersection(roles))


_current_context: ContextVar[RequestContext | None] = ContextVar("_current_context", default=None)


def set_context(ctx: RequestContext) -> Token[RequestContext | None]:
    return _current_context.set(ctx)


def reset_context(token: Token[RequestContext | None]) -> None:
    _current_context.reset(token)


def current_context() -> RequestContext:
    ctx = _current_context.get()
    if ctx is None:
        raise LookupError(
            "No RequestContext bound. This code path must run behind AuthContextMiddleware "
            "or inside a Celery ContextTask."
        )
    return ctx


def try_current_context() -> RequestContext | None:
    return _current_context.get()


def system_context(tenant_id: UUID, request_id: str | None = None) -> RequestContext:
    """Context for maintenance/beat tasks that act with no authenticated user.
    Grants app_is_system() in RLS policies; audit events record actor_sub='system'."""
    return RequestContext(
        tenant_id=tenant_id,
        user_id=None,
        sub="system",
        roles=frozenset(),
        request_id=request_id,
        is_system=True,
    )
