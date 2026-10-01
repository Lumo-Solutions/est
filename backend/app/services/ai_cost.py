"""What reading a tender pack with an external AI provider is expected to cost, and the confirmation a lead estimator
gives before it starts (docs/intake-scale/report.md).

The estimate is files still needing the AI x the average tokens per call seen in `ai_calls` (split by the model the
calls used: text goes to the classify model, page images to the vision model), priced with `app.ai.pricing`. It is an
upper-leaning estimate for budgeting: it cannot know which files the AI cache will answer for free, and it counts a
file's one classification call, nothing else. The provider's invoice is authoritative. The per-project and monthly
budgets remain hard stops in the gateway whatever was confirmed here."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.pricing import estimate_cost_usd, is_unverified
from app.ai.store import DbStore
from app.core.config import Settings
from app.core.context import RequestContext
from app.core.enums import AuditAction
from app.core.errors import ConflictError, NotFoundError
from app.intake.constants import DocStatus
from app.models.ai import AiCall
from app.models.tender_intake import ProjectDocument, TenderPackage
from app.services import ai_admin, audit
from app.services.projects import assert_can_see_project

_TASK = "intake_classify"
# Used when ai_calls has no history for a model yet: text classification on the flash tier, page images on the plus tier.
_DEFAULTS = {"text": (2_500, 0, 250), "image": (6_000, 0, 300)}
_DEFAULT_IMAGE_SHARE = 0.15


class ModelEstimate(BaseModel):
    model: str
    tier: str  # classify | vision
    calls: int
    avg_tokens_in: int
    avg_tokens_cached: int
    avg_tokens_out: int
    est_usd: float
    # False: the rate is a published or default price, not yet checked against an invoice.
    rate_verified: bool
    basis: str  # history | default


class CostEstimateOut(BaseModel):
    package_id: UUID
    provider: str
    external: bool
    ai_available: bool
    files_needing_ai: int
    models: list[ModelEstimate]
    total_usd: float
    any_unverified: bool
    monthly_remaining_usd: float | None
    project_remaining_usd: float | None
    within_budget: bool
    # True: this pack will not start until a lead estimator confirms the estimate.
    confirmation_required: bool
    confirmed_at: datetime | None
    confirmed_usd: float | None
    note: str


class CostConfirmationRequired(ConflictError):
    error_type = "urn:installtec:cost-confirmation-required"
    title = "Cost confirmation required"


async def external_ai_in_use(session: AsyncSession, ctx: RequestContext, settings: Settings) -> bool:
    """True when this tenant's files would be sent to an external provider that is configured, allowed and in budget."""
    status = await ai_admin.get_status(session, ctx, settings)
    return bool(status.external and status.available)


async def _history(session: AsyncSession) -> dict[str, tuple[int, int, int, int]]:
    """model -> (calls, avg tokens in, avg cached, avg out) over the last 90 days of successful intake calls."""
    since = datetime.now(timezone.utc) - timedelta(days=90)
    rows = (
        await session.execute(
            select(
                AiCall.model, func.count(), func.avg(AiCall.tokens_in), func.avg(AiCall.tokens_cached), func.avg(AiCall.tokens_out)
            )
            .where(AiCall.task == _TASK, AiCall.status == "ok", AiCall.external.is_(True), AiCall.created_at >= since)
            .group_by(AiCall.model)
        )
    ).all()
    return {m: (int(n), int(a or 0), int(c or 0), int(o or 0)) for m, n, a, c, o in rows}


async def files_needing_ai(session: AsyncSession, package_id: UUID, max_process_bytes: int) -> int:
    """Files of the pack not read yet that will get an AI call: not a copy of another file (it copies the answer), not
    too large to read, not an archive (its members are counted when it is opened)."""
    return int(
        (
            await session.execute(
                select(func.count()).select_from(ProjectDocument).where(
                    ProjectDocument.package_id == package_id,
                    ProjectDocument.status.in_([DocStatus.RECEIVED.value, DocStatus.PROCESSING.value, DocStatus.PENDING_UPLOAD.value]),
                    ProjectDocument.duplicate_of_id.is_(None),
                    ProjectDocument.size_bytes <= max_process_bytes,
                    ProjectDocument.ext != "zip",
                )
            )
        ).scalar_one()
    )


async def estimate(session: AsyncSession, ctx: RequestContext, settings: Settings, package_id: UUID) -> CostEstimateOut:
    package = (await session.execute(select(TenderPackage).where(TenderPackage.id == package_id))).scalar_one_or_none()
    if package is None:
        raise NotFoundError(f"Tender package {package_id} not found")
    await assert_can_see_project(session, ctx, package.project_id)
    status = await ai_admin.get_status(session, ctx, settings)
    n = await files_needing_ai(session, package_id, settings.intake_max_process_bytes) if status.available else 0
    hist = await _history(session)

    classify_model = settings.ai_model_classify or settings.ai_model
    vision_model = settings.ai_model_vision or settings.ai_model
    plans: list[tuple[str, str, float]] = []  # (tier, model, share of calls)
    if classify_model == vision_model:
        plans = [("classify", classify_model, 1.0)]
    else:
        # The share of calls that carry page images, from what intake has actually sent (else a default).
        c_calls = hist.get(classify_model, (0, 0, 0, 0))[0]
        v_calls = hist.get(vision_model, (0, 0, 0, 0))[0]
        image_share = v_calls / (c_calls + v_calls) if (c_calls + v_calls) >= 20 else _DEFAULT_IMAGE_SHARE
        plans = [("classify", classify_model, 1.0 - image_share), ("vision", vision_model, image_share)]

    models: list[ModelEstimate] = []
    total = Decimal(0)
    for tier, model, share in plans:
        calls = round(n * share)
        h = hist.get(model)
        basis = "history" if h and h[0] >= 5 else "default"
        t_in, t_cached, t_out = (h[1], h[2], h[3]) if basis == "history" else _DEFAULTS["image" if tier == "vision" else "text"]
        per_call = estimate_cost_usd(status.provider, model, t_in, t_out, t_cached)
        if status.provider in ("local_vllm", "mock"):
            per_call = Decimal(0)
        cost = per_call * calls
        total += cost
        models.append(
            ModelEstimate(
                model=model, tier=tier, calls=calls, avg_tokens_in=t_in, avg_tokens_cached=t_cached, avg_tokens_out=t_out,
                est_usd=float(cost), rate_verified=status.provider in ("local_vllm", "mock") or not is_unverified(model), basis=basis,
            )
        )

    month_spent, project_spent = await DbStore().spend(ctx, package.project_id)
    monthly_remaining = (
        max(0.0, float(settings.ai_monthly_budget_usd) - float(month_spent)) if settings.ai_monthly_budget_usd is not None else None
    )
    project_remaining = (
        max(0.0, float(settings.ai_project_budget_usd) - float(project_spent)) if settings.ai_project_budget_usd is not None else None
    )
    within = all(r is None or float(total) <= r for r in (monthly_remaining, project_remaining))
    external_in_use = bool(status.external and status.available)
    confirmed = package.cost_confirmed_at is not None
    if not status.external:
        note = "The AI provider runs inside your deployment: no per-call cost."
    elif not status.available:
        note = status.message or "External AI is not available: files are classified by the built-in rules (no cost)."
    elif not within:
        note = "The estimate is above the remaining budget: the budget stops AI calls when it is reached, and the rest is read by the rules."
    else:
        note = "An estimate before the invoice: files the AI cache already answers cost nothing, and copies reuse their original's answer."
    return CostEstimateOut(
        package_id=package_id, provider=status.provider, external=status.external, ai_available=bool(status.available),
        files_needing_ai=n, models=models, total_usd=float(total), any_unverified=any(not m.rate_verified for m in models if m.calls),
        monthly_remaining_usd=monthly_remaining, project_remaining_usd=project_remaining, within_budget=within,
        confirmation_required=external_in_use and not confirmed, confirmed_at=package.cost_confirmed_at,
        confirmed_usd=float(package.cost_confirmed_usd) if package.cost_confirmed_usd is not None else None, note=note,
    )


async def confirm(
    session: AsyncSession, ctx: RequestContext, settings: Settings, package_id: UUID, accepted_usd: float
) -> CostEstimateOut:
    """A lead estimator accepts the estimate they were shown. If the estimate has grown by more than 10 % (and 1 cent)
    since they looked, they are asked to look again."""
    est = await estimate(session, ctx, settings, package_id)
    if est.confirmation_required and est.total_usd > accepted_usd * 1.10 + 0.01:
        raise CostConfirmationRequired(
            f"The estimate is now ${est.total_usd:.2f} (you saw ${accepted_usd:.2f}): look at it again before confirming.",
            estimate=est.model_dump(mode="json"),
        )
    package = (await session.execute(select(TenderPackage).where(TenderPackage.id == package_id))).scalar_one()
    package.cost_confirmed_at = datetime.now(timezone.utc)
    package.cost_confirmed_usd = Decimal(str(round(est.total_usd, 4)))
    package.cost_confirmed_by = ctx.user_id
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.UPDATE, entity_type="tender_package", entity_id=package.id, project_id=package.project_id,
        payload={
            "event": "confirm_cost", "estimated_usd": est.total_usd, "accepted_usd": accepted_usd, "files_needing_ai": est.files_needing_ai,
            "provider": est.provider, "models": [m.model for m in est.models], "any_unverified": est.any_unverified,
        },
    )
    return await estimate(session, ctx, settings, package_id)


async def require_confirmed(session: AsyncSession, ctx: RequestContext, settings: Settings, package_id: UUID) -> None:
    """Raises `CostConfirmationRequired` (with the estimate) when this pack would spend money and nobody confirmed it."""
    est = await estimate(session, ctx, settings, package_id)
    if est.confirmation_required:
        raise CostConfirmationRequired(
            f"Confirm the estimated cost first: about ${est.total_usd:.2f} for {est.files_needing_ai} files.",
            estimate=est.model_dump(mode="json"),
        )


__all__ = [
    "CostConfirmationRequired",
    "CostEstimateOut",
    "confirm",
    "estimate",
    "external_ai_in_use",
    "require_confirmed",
]
