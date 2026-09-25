from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.core.context import RequestContext, current_context
from app.db.rls import set_rls_context


def _normalize(url: str) -> str:
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://") :]
    return url


@lru_cache
def get_app_engine() -> AsyncEngine:
    """Engine for the running app/workers, connected as the non-owner,
    NOBYPASSRLS `installtec_app` role. This is the ONLY engine business code
    should ever use -- see db/ddl.py and docs/security-rls.md for why."""
    settings = get_settings()
    return create_async_engine(_normalize(settings.app_database_url), pool_pre_ping=True)


@lru_cache
def get_migrator_engine() -> AsyncEngine:
    """Engine for Alembic only. Never import this from app/services or app/api."""
    settings = get_settings()
    return create_async_engine(_normalize(settings.migrator_database_url), pool_pre_ping=True)


@lru_cache
def get_worker_engine() -> AsyncEngine:
    """Separate engine for Celery task bodies only (via
    app/workers/base.py::with_worker_session) -- NullPool, not pooled like
    get_app_engine(). A worker task wraps its whole body in asyncio.run()
    (app/workers/base.py::run_async), a fresh event loop per task, in a
    long-lived prefork process that runs many tasks over its lifetime.
    asyncpg connections are bound to the event loop that created them, so a
    connection left idle in a *pooled* engine's pool by one task's
    asyncio.run() gets reused under a *different* loop by the next task's
    asyncio.run() -- SQLAlchemy's pool_pre_ping surfaces this immediately as
    'Future attached to a different loop' on that next checkout. NullPool
    means every checkout is a brand-new connection, so nothing ever
    survives across a run_async() boundary. Found running Module C2's
    `simulate-quotes` end to end against real Celery workers (never caught
    by tests, which call task *bodies* directly against one already-open
    session, or by the FastAPI web process's own use of get_app_engine(),
    which keeps one event loop for its whole lifetime and never hits this)."""
    settings = get_settings()
    return create_async_engine(_normalize(settings.app_database_url), poolclass=NullPool)


_app_session_factory: async_sessionmaker[AsyncSession] | None = None


def _session_factory() -> async_sessionmaker[AsyncSession]:
    global _app_session_factory
    if _app_session_factory is None:
        _app_session_factory = async_sessionmaker(
            bind=get_app_engine(), expire_on_commit=False, autoflush=False
        )
    return _app_session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one DB transaction per request, with RLS GUCs set
    from the authenticated RequestContext before any business query runs.
    This is the sanctioned way to get a session in request code -- do not
    call _session_factory()/get_app_engine() directly outside db/ or workers/."""
    ctx = current_context()
    async with _session_factory()() as session, session.begin():
        await set_rls_context(session, ctx)
        yield session


@asynccontextmanager
async def session_scope(ctx: RequestContext) -> AsyncIterator[AsyncSession]:
    """Same transaction/RLS setup as get_session(), for callers outside
    FastAPI's own dependency injection that share the caller's single,
    long-lived event loop (the OIDC callback route, `python -m app.cli`
    commands): `async with session_scope(ctx) as session: ...`. Celery task
    bodies use worker_session_scope() instead, below -- see its docstring
    for why a pooled engine isn't safe for something that wraps every call
    in its own asyncio.run().

    This MUST be its own @asynccontextmanager-decorated generator, not a
    wrapper that drives a second async generator via manual
    `__anext__()`/`aclose()` calls. An earlier version did that, calling
    `aclose()` in a `finally` block to "guarantee cleanup on early return"
    -- which is real advice for the *closing* half, but `aclose()` throws
    `GeneratorExit` into the wrapped generator at its `yield` point
    regardless of whether the `async with` block succeeded, so
    `session.begin()` always saw an exception and always rolled back, even
    on success. That silently discarded every write made through this
    function (Celery task results, the seed CLI, login audit events) while
    reporting success. @asynccontextmanager's own generator handling gets
    the success/failure distinction right, so let it do that job instead of
    reimplementing it.
    """
    async with _session_factory()() as session, session.begin():
        await set_rls_context(session, ctx)
        yield session


_worker_session_factory: async_sessionmaker[AsyncSession] | None = None


def _worker_session_factory_fn() -> async_sessionmaker[AsyncSession]:
    global _worker_session_factory
    if _worker_session_factory is None:
        _worker_session_factory = async_sessionmaker(bind=get_worker_engine(), expire_on_commit=False, autoflush=False)
    return _worker_session_factory


@asynccontextmanager
async def worker_session_scope(ctx: RequestContext) -> AsyncIterator[AsyncSession]:
    """Same shape as session_scope(), bound to get_worker_engine() (NullPool)
    instead of get_app_engine() -- see that function's docstring. Used only
    by app/workers/base.py::with_worker_session, i.e. every Celery task
    body."""
    async with _worker_session_factory_fn()() as session, session.begin():
        await set_rls_context(session, ctx)
        yield session
