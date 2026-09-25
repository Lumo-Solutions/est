"""Celery/async bridge helpers.

Design simplification vs. the original sketch: rather than a custom
ContextTask pulling tenant/user/roles from Celery task headers, tasks in
this slice take `tenant_id` (and `actor_user_id`/`actor_roles` where an
audit trail needs an attributable actor) as explicit arguments. This is more
verbose per call site but trivial to reason about, log, and retry
correctly -- Celery header propagation across retries/chains is an easy
place to silently lose context.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import ParamSpec, TypeVar
from uuid import UUID

from app.core.context import RequestContext, reset_context, set_context, system_context
from app.db.session import worker_session_scope

P = ParamSpec("P")
T = TypeVar("T")


def run_async(coro_fn: Callable[P, Awaitable[T]]) -> Callable[P, T]:
    """Wraps an async function so a plain (sync) Celery task body can call
    it with `asyncio.run(...)` semantics, one event loop per task
    invocation -- Celery workers are process-per-worker, not
    coroutine-concurrent, so this is not a bottleneck."""

    def _wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
        return asyncio.run(coro_fn(*args, **kwargs))

    return _wrapped


def build_worker_context(
    tenant_id: str, actor_user_id: str | None = None, actor_roles: list[str] | None = None
) -> RequestContext:
    return RequestContext(
        tenant_id=UUID(tenant_id),
        user_id=UUID(actor_user_id) if actor_user_id else None,
        sub=actor_user_id,
        roles=frozenset(actor_roles or []),
        is_system=actor_user_id is None,
    )


async def with_worker_session(ctx: RequestContext, body: Callable[..., Awaitable[T]], *args: object) -> T:
    """Opens one RLS-context'd DB session for the duration of `body`,
    mirroring app/db/session.py::get_session() for request code. Uses
    worker_session_scope() (NullPool), not session_scope() -- see that
    function's docstring: run_async() wraps every task body in its own
    asyncio.run(), and a *pooled* engine's connections, bound to the event
    loop that created them, don't survive across that boundary in a
    long-lived (many-tasks-per-process) Celery worker."""
    token = set_context(ctx)
    try:
        async with worker_session_scope(ctx) as session:
            return await body(session, *args)
    finally:
        reset_context(token)


def system_ctx(tenant_id: str) -> RequestContext:
    return system_context(UUID(tenant_id))
