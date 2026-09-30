from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_session, require_roles
from app.core.context import RequestContext
from app.core.enums import Role
from app.models.boq import BoqLineItem
from app.models.pricing_ai import SettlementAiProposal
from app.models.settlement import BidSettlementLineItem
from app.pricing import engine as pe
from app.schemas.pricing_ai import (
    BulkAcceptIn,
    BulkAcceptOut,
    CandidateOut,
    CostRunCreate,
    DecisionIn,
    MarkupRunCreate,
    ProposalOut,
    ProposalPage,
    SettlementAiRunOut,
)
from app.services import pricing_ai as svc

router = APIRouter(tags=["pricing-ai"])

# Starting a run spends AI budget: lead_estimator and above (the brief). Working the proposals is
# ordinary line costing (estimator+), exactly like set_line_cost; bulk-accepting is a lead action.
_RUN_ROLES = (Role.LEAD_ESTIMATOR.value, Role.PROCUREMENT_HEAD.value, Role.BD_DIRECTOR.value, Role.MANAGING_DIRECTOR.value)
_WORK_ROLES = (Role.ESTIMATOR.value, *_RUN_ROLES)


def _dispatch(ctx: RequestContext, run_id: UUID) -> None:
    from app.workers.tasks.ai_reading import run_settlement_ai

    run_settlement_ai.apply_async(
        args=(str(run_id), str(ctx.tenant_id), str(ctx.user_id) if ctx.user_id else None, list(ctx.roles)), countdown=2
    )


@router.post("/bid-settlements/{settlement_id}/ai/cost-proposals", response_model=SettlementAiRunOut, status_code=202)
async def create_cost_run_endpoint(
    settlement_id: UUID,
    body: CostRunCreate | None = None,
    ctx: RequestContext = Depends(require_roles(*_RUN_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> SettlementAiRunOut:
    run = await svc.create_run(session, ctx, settlement_id, kind="costs", use_ai=(body.use_ai if body else True))
    _dispatch(ctx, run.id)
    return SettlementAiRunOut.model_validate(run)


@router.post("/bid-settlements/{settlement_id}/ai/markup-advice", response_model=SettlementAiRunOut, status_code=202)
async def create_markup_run_endpoint(
    settlement_id: UUID,
    body: MarkupRunCreate | None = None,
    ctx: RequestContext = Depends(require_roles(*_RUN_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> SettlementAiRunOut:
    run = await svc.create_run(session, ctx, settlement_id, kind="markup", use_ai=(body.use_ai if body else True))
    _dispatch(ctx, run.id)
    return SettlementAiRunOut.model_validate(run)


@router.get("/bid-settlements/{settlement_id}/ai/runs", response_model=list[SettlementAiRunOut])
async def list_runs_endpoint(
    settlement_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> list[SettlementAiRunOut]:
    return [SettlementAiRunOut.model_validate(r) for r in await svc.list_runs(session, settlement_id)]


@router.get("/settlement-ai-runs/{run_id}", response_model=SettlementAiRunOut)
async def get_run_endpoint(
    run_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> SettlementAiRunOut:
    return SettlementAiRunOut.model_validate(await svc.get_run(session, run_id))


async def _out(session: AsyncSession, rows: list[SettlementAiProposal]) -> list[ProposalOut]:
    items = {
        i.id: i for i in (await session.execute(select(BoqLineItem).where(BoqLineItem.id.in_({r.boq_line_item_id for r in rows} or {UUID(int=0)})))).scalars().all()
    }
    lines = {
        l.id: l for l in (await session.execute(select(BidSettlementLineItem).where(BidSettlementLineItem.id.in_({r.settlement_line_id for r in rows} or {UUID(int=0)})))).scalars().all()
    }
    out: list[ProposalOut] = []
    for r in rows:
        item, line = items.get(r.boq_line_item_id), lines.get(r.settlement_line_id)
        flags = list(r.flags or [])
        blocked = pe.is_blocked(flags)
        out.append(
            ProposalOut(
                id=r.id, run_id=r.run_id, settlement_id=r.settlement_id, settlement_line_id=r.settlement_line_id,
                boq_line_item_id=r.boq_line_item_id, item_no=item.item_no if item else None,
                description=item.description if item else None, uom=item.uom if item else None,
                quantity=line.quantity if line else None, status=r.status, source=r.source,
                chosen=CandidateOut(**_c(r.chosen)) if r.chosen else None, candidates=[CandidateOut(**_c(c)) for c in r.candidates],
                rationale=r.rationale, flags=flags, blocked=blocked,
                bulk_acceptable=bool(r.chosen) and not blocked and float(r.confidence) >= pe.BULK_ACCEPT_MIN_CONFIDENCE and r.status == "proposed",
                no_source=r.chosen is None, confidence=r.confidence, decided_by=r.decided_by, decided_at=r.decided_at,
                decision_note=r.decision_note, created_at=r.created_at,
            )
        )
    return out


def _c(d: dict) -> dict:
    return {k: d.get(k) for k in ("ref", "type", "label", "rate", "currency", "uom", "vendor", "as_of", "samples", "match_score", "score", "reason", "selected", "flags", "detail") if k in d}


@router.get("/bid-settlements/{settlement_id}/ai/proposals", response_model=ProposalPage)
async def list_proposals_endpoint(
    settlement_id: UUID,
    status: str | None = None,
    flagged: bool | None = None,
    no_source: bool | None = None,
    min_confidence: float | None = Query(default=None, ge=0, le=1),
    max_confidence: float | None = Query(default=None, ge=0, le=1),
    limit: int = Query(default=500, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    ctx: RequestContext = CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> ProposalPage:
    rows, total = await svc.list_proposals(
        session, settlement_id, status=status, flagged=flagged, no_source=no_source, min_confidence=min_confidence,
        max_confidence=max_confidence, limit=limit, offset=offset,
    )
    return ProposalPage(items=await _out(session, rows), total=total, limit=limit, offset=offset)


@router.post("/settlement-ai-proposals/{proposal_id}/decision", response_model=ProposalOut)
async def decide_endpoint(
    proposal_id: UUID,
    body: DecisionIn,
    ctx: RequestContext = Depends(require_roles(*_WORK_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> ProposalOut:
    p = await svc.decide(
        session, ctx, proposal_id, action=body.action, candidate_ref=body.candidate_ref,
        manual_unit_cost=body.manual_unit_cost, manual_currency=body.manual_currency, note=body.note,
    )
    return (await _out(session, [p]))[0]


@router.post("/bid-settlements/{settlement_id}/ai/proposals:bulk-accept", response_model=BulkAcceptOut)
async def bulk_accept_endpoint(
    settlement_id: UUID,
    body: BulkAcceptIn | None = None,
    ctx: RequestContext = Depends(require_roles(*_RUN_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> BulkAcceptOut:
    res = await svc.bulk_accept(session, ctx, settlement_id, min_confidence=(body.min_confidence if body else pe.BULK_ACCEPT_MIN_CONFIDENCE))
    return BulkAcceptOut(**res)
