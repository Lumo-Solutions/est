"""Persistence behind the gateway: governance flags, cache, spend, ai_calls.

Every operation opens its OWN short transaction (worker_session_scope, a
NullPool engine that is safe under any event loop) so the audit row of a
failed or blocked call is committed even when the caller's transaction later
rolls back -- an AI call's record must never vanish with a caller's failure.
Spend and governance reads run as the system actor scoped by an explicit
tenant_id filter: ai_calls is readable only by lead_estimator+, but the
budget must count every role's calls.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Protocol

from sqlalchemy import func, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.context import RequestContext, system_context
from app.db.session import worker_session_scope
from app.models.ai import AiCacheEntry, AiCall, TenantAiSettings
from app.models.tenancy import Project


@dataclass(slots=True)
class CallRecord:
    task: str
    provider: str
    model: str
    prompt_version: str
    input_sha256: str
    status: str  # ok | cached | error | blocked
    external: bool
    project_id: uuid.UUID | None = None
    entity_type: str | None = None
    entity_id: str | None = None
    prompt: str | None = None
    response: Any = None
    tokens_in: int = 0
    tokens_cached: int = 0
    tokens_out: int = 0
    cost_usd: Decimal = Decimal("0")
    latency_ms: int = 0
    error: str | None = None


@dataclass(slots=True)
class CacheHit:
    response: Any
    tokens_in: int
    tokens_out: int


class AIStore(Protocol):
    async def external_allowed(self, ctx: RequestContext, project_id: uuid.UUID | None) -> bool: ...

    async def cache_get(
        self, ctx: RequestContext, task: str, input_sha256: str, model: str, prompt_version: str
    ) -> CacheHit | None: ...

    async def cache_put(
        self, ctx: RequestContext, task: str, input_sha256: str, model: str, prompt_version: str, hit: CacheHit
    ) -> None: ...

    async def spend(self, ctx: RequestContext, project_id: uuid.UUID | None) -> tuple[Decimal, Decimal]:
        """(month-to-date tenant spend, project-to-date spend) in USD."""
        ...

    async def record(self, ctx: RequestContext, rec: CallRecord) -> uuid.UUID: ...


def _month_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


class DbStore:
    async def external_allowed(self, ctx: RequestContext, project_id: uuid.UUID | None) -> bool:
        sys_ctx = system_context(ctx.tenant_id)
        async with worker_session_scope(sys_ctx) as session:
            allowed = (
                await session.execute(
                    select(TenantAiSettings.external_ai_allowed).where(TenantAiSettings.tenant_id == ctx.tenant_id)
                )
            ).scalar_one_or_none()
            if not allowed:
                return False
            if project_id is not None:
                override = (
                    await session.execute(
                        select(Project.external_ai_override).where(
                            Project.id == project_id, Project.tenant_id == ctx.tenant_id
                        )
                    )
                ).scalar_one_or_none()
                if override is False:
                    return False
            return True

    async def cache_get(
        self, ctx: RequestContext, task: str, input_sha256: str, model: str, prompt_version: str
    ) -> CacheHit | None:
        async with worker_session_scope(ctx) as session:
            row = (
                await session.execute(
                    select(AiCacheEntry).where(
                        AiCacheEntry.tenant_id == ctx.tenant_id,
                        AiCacheEntry.task == task,
                        AiCacheEntry.input_sha256 == input_sha256,
                        AiCacheEntry.model == model,
                        AiCacheEntry.prompt_version == prompt_version,
                    )
                )
            ).scalar_one_or_none()
            return CacheHit(row.response, row.tokens_in, row.tokens_out) if row else None

    async def cache_put(
        self, ctx: RequestContext, task: str, input_sha256: str, model: str, prompt_version: str, hit: CacheHit
    ) -> None:
        async with worker_session_scope(ctx) as session:
            stmt = (
                pg_insert(AiCacheEntry.__table__)
                .values(
                    id=uuid.uuid4(),
                    tenant_id=ctx.tenant_id,
                    created_by=ctx.user_id,
                    task=task,
                    input_sha256=input_sha256,
                    model=model,
                    prompt_version=prompt_version,
                    response=hit.response,
                    tokens_in=hit.tokens_in,
                    tokens_out=hit.tokens_out,
                )
                .on_conflict_do_nothing(constraint="uq_ai_cache_key")
            )
            await session.execute(stmt)

    async def spend(self, ctx: RequestContext, project_id: uuid.UUID | None) -> tuple[Decimal, Decimal]:
        sys_ctx = system_context(ctx.tenant_id)
        async with worker_session_scope(sys_ctx) as session:
            base = select(func.coalesce(func.sum(AiCall.cost_usd), 0)).where(
                AiCall.tenant_id == ctx.tenant_id, AiCall.status == "ok"
            )
            month = (await session.execute(base.where(AiCall.created_at >= _month_start()))).scalar_one()
            project = Decimal("0")
            if project_id is not None:
                project = (await session.execute(base.where(AiCall.project_id == project_id))).scalar_one()
            return Decimal(month), Decimal(project)

    async def record(self, ctx: RequestContext, rec: CallRecord) -> uuid.UUID:
        call_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        # Core INSERT without RETURNING: the SELECT policy on ai_calls is
        # lead_estimator+, and RETURNING would evaluate it for an estimator.
        async with worker_session_scope(ctx) as session:
            await session.execute(
                insert(AiCall.__table__).values(
                    id=call_id,
                    tenant_id=ctx.tenant_id,
                    created_at=now,
                    updated_at=now,
                    created_by=ctx.user_id,
                    project_id=rec.project_id,
                    task=rec.task,
                    provider=rec.provider,
                    model=rec.model,
                    prompt_version=rec.prompt_version,
                    entity_type=rec.entity_type,
                    entity_id=rec.entity_id,
                    input_sha256=rec.input_sha256,
                    prompt=rec.prompt,
                    response=rec.response,
                    tokens_in=rec.tokens_in,
                    tokens_cached=rec.tokens_cached,
                    tokens_out=rec.tokens_out,
                    cost_usd=rec.cost_usd,
                    latency_ms=rec.latency_ms,
                    status=rec.status,
                    error=rec.error,
                    external=rec.external,
                )
            )
        return call_id


class MemoryStore:
    """In-process store for unit tests and offline tools."""

    def __init__(self, *, external_allowed: bool = False, project_blocked: bool = False) -> None:
        self.allowed = external_allowed
        self.project_blocked = project_blocked
        self.cache: dict[tuple, CacheHit] = {}
        self.calls: list[CallRecord] = []
        self.month_spend = Decimal("0")
        self.project_spend = Decimal("0")

    async def external_allowed(self, ctx: RequestContext, project_id: uuid.UUID | None) -> bool:
        return self.allowed and not (project_id is not None and self.project_blocked)

    async def cache_get(self, ctx, task, input_sha256, model, prompt_version):  # type: ignore[no-untyped-def]
        return self.cache.get((ctx.tenant_id, task, input_sha256, model, prompt_version))

    async def cache_put(self, ctx, task, input_sha256, model, prompt_version, hit):  # type: ignore[no-untyped-def]
        self.cache.setdefault((ctx.tenant_id, task, input_sha256, model, prompt_version), hit)

    async def spend(self, ctx, project_id):  # type: ignore[no-untyped-def]
        return self.month_spend, self.project_spend

    async def record(self, ctx, rec):  # type: ignore[no-untyped-def]
        self.calls.append(rec)
        if rec.status == "ok":
            self.month_spend += rec.cost_usd
            if rec.project_id is not None:
                self.project_spend += rec.cost_usd
        return uuid.uuid4()
