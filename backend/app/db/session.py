from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

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
    FastAPI's own dependency injection (Celery tasks via workers/base.py,
    the OIDC callback route, beat jobs): `async with session_scope(ctx) as
    session: ...`.

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
