"""AI governance settings and the usage/cost view (docs/ai-plan.md §2)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.gateway import AIGateway
from app.ai.pricing import is_unverified
from app.ai.store import DbStore, _month_start
from app.core.config import Settings
from app.core.context import RequestContext
from app.core.enums import AuditAction
from app.core.errors import NotFoundError
from app.models.ai import AiCall, TenantAiSettings
from app.models.tenancy import Project
from app.schemas.ai import (
    AiCallOut,
    AiSettingsOut,
    AiStatusOut,
    AiUsageOut,
    AiUsageRow,
    ProjectAiOverrideOut,
)
from app.services import audit


async def _allowed(session: AsyncSession, ctx: RequestContext) -> bool:
    row = (
        await session.execute(
            select(TenantAiSettings.external_ai_allowed).where(TenantAiSettings.tenant_id == ctx.tenant_id)
        )
    ).scalar_one_or_none()
    return bool(row)


def _gateway_status(settings: Settings) -> dict:
    return AIGateway(settings=settings, store=None).status()  # type: ignore[arg-type]


async def get_status(session: AsyncSession, ctx: RequestContext, settings: Settings) -> AiStatusOut:
    gw = _gateway_status(settings)
    allowed = await _allowed(session, ctx)
    budget_exceeded = False
    if gw["external"] and settings.ai_monthly_budget_usd is not None:
        # ai_calls is readable by lead_estimator+ only; the budget must count every role's calls, so use the
        # store's system-scoped sum (the same one the gateway enforces the cap with).
        month_spent, _project = await DbStore().spend(ctx, None)
        budget_exceeded = float(month_spent) >= float(settings.ai_monthly_budget_usd)
    available = gw["configured"] and (allowed or not gw["external"]) and not budget_exceeded
    message = None
    if gw["external"] and not gw["configured"]:
        message = "AI not configured"
    elif gw["external"] and not allowed:
        message = "External AI is not allowed for this organisation"
    elif budget_exceeded:
        message = "The monthly AI budget has been reached; AI features are paused until next month or the cap is raised"
    return AiStatusOut(
        provider=gw["provider"],
        external=gw["external"],
        configured=gw["configured"],
        external_ai_allowed=allowed,
        available=available,
        message=message,
        budget_exceeded=budget_exceeded,
    )


async def set_external_allowed(
    session: AsyncSession, ctx: RequestContext, settings: Settings, allowed: bool
) -> AiSettingsOut:
    row = (
        await session.execute(select(TenantAiSettings).where(TenantAiSettings.tenant_id == ctx.tenant_id))
    ).scalar_one_or_none()
    before = bool(row.external_ai_allowed) if row else False
    if row is None:
        session.add(
            TenantAiSettings(tenant_id=ctx.tenant_id, external_ai_allowed=allowed, created_by=ctx.user_id, updated_by=ctx.user_id)
        )
    else:
        row.external_ai_allowed = allowed
        row.updated_by = ctx.user_id
    await session.flush()
    await audit.record(
        session,
        ctx,
        action=AuditAction.UPDATE,
        entity_type="tenant_ai_settings",
        entity_id=str(ctx.tenant_id),
        payload={"external_ai_allowed": {"before": before, "after": allowed}},
    )
    gw = _gateway_status(settings)
    return AiSettingsOut(
        external_ai_allowed=allowed, provider=gw["provider"], external=gw["external"], configured=gw["configured"]
    )


async def set_project_override(
    session: AsyncSession, ctx: RequestContext, project_id: UUID, override: bool | None
) -> ProjectAiOverrideOut:
    project = (await session.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if project is None:
        raise NotFoundError("Project not found")
    before = project.external_ai_override
    project.external_ai_override = override
    project.updated_by = ctx.user_id
    await session.flush()
    await audit.record(
        session,
        ctx,
        action=AuditAction.UPDATE,
        entity_type="project_ai_override",
        entity_id=str(project_id),
        project_id=project_id,
        payload={"external_ai_override": {"before": before, "after": override}},
    )
    return ProjectAiOverrideOut(project_id=project_id, external_ai_override=override)


async def usage(session: AsyncSession, ctx: RequestContext, settings: Settings, *, days: int = 30) -> AiUsageOut:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        await session.execute(
            select(
                AiCall.task,
                AiCall.provider,
                AiCall.model,
                func.count(),
                func.sum(case((AiCall.status == "cached", 1), else_=0)),
                func.sum(case((AiCall.status == "error", 1), else_=0)),
                func.sum(case((AiCall.status == "blocked", 1), else_=0)),
                func.coalesce(func.sum(AiCall.tokens_in), 0),
                func.coalesce(func.sum(AiCall.tokens_cached), 0),
                func.coalesce(func.sum(AiCall.tokens_out), 0),
                func.coalesce(func.sum(case((AiCall.status == "ok", AiCall.cost_usd), else_=0)), 0),
            )
            .where(AiCall.created_at >= since)
            .group_by(AiCall.task, AiCall.provider, AiCall.model)
            .order_by(AiCall.task)
        )
    ).all()
    month = (
        await session.execute(
            select(func.coalesce(func.sum(AiCall.cost_usd), 0)).where(
                AiCall.status == "ok", AiCall.created_at >= _month_start()
            )
        )
    ).scalar_one()
    recent = (await session.execute(select(AiCall).order_by(AiCall.created_at.desc()).limit(50))).scalars().all()
    return AiUsageOut(
        month_to_date_usd=float(month),
        monthly_budget_usd=settings.ai_monthly_budget_usd,
        project_budget_usd=settings.ai_project_budget_usd,
        rows=[
            AiUsageRow(
                task=r[0], provider=r[1], model=r[2], calls=r[3], cached=int(r[4] or 0), errors=int(r[5] or 0),
                blocked=int(r[6] or 0), tokens_in=int(r[7]), tokens_cached=int(r[8]), tokens_out=int(r[9]), cost_usd=float(r[10]),
                rate_verified=r[1] in ("local_vllm", "mock") or not is_unverified(r[2]),
            )
            for r in rows
        ],
        recent=[AiCallOut.model_validate(c) for c in recent],
    )
