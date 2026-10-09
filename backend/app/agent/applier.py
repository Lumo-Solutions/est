"""The deterministic applier: agent proposals into the project's current settlement, only while it is a draft
(docs/boq-agent/plan.md section 3.4; brief 2.8).

Money rules, all enforced here in code:
* only a `draft` settlement is written; a submitted or approved one is never touched;
* a line a person set (a person's name on its cost source) is never overwritten; the agent may replace only its own earlier line;
* the rate, currency, unit and as-of date come from the proposal row, which took them from the database record of the chosen
  candidate (or, for an estimate, from the validated estimate) -- never from free model text;
* percentages, FX rates and quantities are not touched; a line stays `needs_fx` exactly as the existing flow leaves it;
* every written line is unconfirmed (`agent_confirmed_by` NULL) and blocks submit until a person confirms it.
The applier runs as the person who started the run, so project visibility, audit attribution and role checks are theirs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import RequestContext
from app.core.enums import AuditAction, BidSettlementStatus, SettlementCostSource
from app.core.errors import ForbiddenError
from app.models.agent import AgentLineProposal
from app.models.settlement import BidSettlement, BidSettlementLineItem
from app.services import audit

AGENT_SOURCES = (SettlementCostSource.AGENT_CANDIDATE.value, SettlementCostSource.AGENT_ESTIMATE.value)
APPLY_ROLES = ("lead_estimator", "procurement_head", "bd_director", "managing_director")


@dataclass(slots=True)
class ApplyResult:
    settlement_id: UUID | None = None
    applied: int = 0
    skipped: dict[str, int] = field(default_factory=dict)
    reason: str | None = None

    def skip(self, why: str) -> None:
        self.skipped[why] = self.skipped.get(why, 0) + 1


def is_person_set(line: BidSettlementLineItem) -> bool:
    """A cost a person put on the line (directly, or by accepting a quote / library rate / manual entry)."""
    return line.cost_source not in AGENT_SOURCES and line.source_set_by is not None


def user_context(tenant_id: UUID, user_id: UUID | None, roles: list[str] | frozenset[str]) -> RequestContext:
    return RequestContext(tenant_id=tenant_id, user_id=user_id, sub=str(user_id) if user_id else None, roles=frozenset(roles), is_system=False)


async def current_settlement(session: AsyncSession, project_id: UUID) -> BidSettlement | None:
    return (
        await session.execute(select(BidSettlement).where(BidSettlement.project_id == project_id, BidSettlement.is_current.is_(True)))
    ).scalar_one_or_none()


def _line_values(p: AgentLineProposal) -> dict:
    a = (p.apply or {}).get("apply") or {}
    detail = (p.apply or {}).get("detail") or {}
    q_id = a.get("source_quotation_line_item_id") if a.get("cost_source") == "quotation_line" else None
    rate_id = detail.get("rate_id") if a.get("cost_source") == "cost_library_rate" else None
    as_of = date.fromisoformat(a["valid_on"]) if a.get("cost_source") == "cost_library_rate" and a.get("valid_on") else None
    return dict(
        direct_unit_cost=p.rate, source_currency=p.currency,
        cost_source=SettlementCostSource.AGENT_CANDIDATE.value if p.kind == "candidate" else SettlementCostSource.AGENT_ESTIMATE.value,
        source_quotation_line_item_id=UUID(q_id) if q_id else None,
        source_cost_item_rate_id=UUID(rate_id) if rate_id else None,
        source_rate_as_of_date=as_of,
    )


async def apply_proposals(session: AsyncSession, ctx: RequestContext, project_id: UUID, run_id: UUID) -> ApplyResult:
    """Applies this run's `proposed` rows. Safe to call again: applied rows are not touched twice."""
    if not ctx.has_role(*APPLY_ROLES):
        raise ForbiddenError("Applying agent proposals requires lead_estimator or above")
    out = ApplyResult()
    settlement = await current_settlement(session, project_id)
    if settlement is None:
        out.reason = "no_settlement"
        return out
    out.settlement_id = settlement.id
    if settlement.status != BidSettlementStatus.DRAFT.value:
        out.reason = f"settlement_{settlement.status}"
        return out
    proposals = list(
        (
            await session.execute(
                select(AgentLineProposal).where(AgentLineProposal.run_id == run_id, AgentLineProposal.status == "proposed").order_by(AgentLineProposal.created_at)
            )
        ).scalars()
    )
    lines = {
        l.boq_line_item_id: l
        for l in (await session.execute(select(BidSettlementLineItem).where(BidSettlementLineItem.settlement_id == settlement.id))).scalars()
    }
    now = datetime.now(timezone.utc)
    for p in proposals:
        line = lines.get(p.boq_line_item_id)
        if line is None:
            out.skip("no_settlement_line")
            continue
        if is_person_set(line):
            out.skip("person_set")
            continue
        if p.rate is None or p.currency is None:
            out.skip("incomplete")
            continue
        if line.agent_proposal_id and line.agent_proposal_id != p.id:
            old = (await session.execute(select(AgentLineProposal).where(AgentLineProposal.id == line.agent_proposal_id))).scalar_one_or_none()
            if old is not None and old.status == "applied":
                old.status = "superseded"
        for k, v in _line_values(p).items():
            setattr(line, k, v)
        line.source_set_by = None  # an agent line is never "set by" a person until one confirms or replaces it
        line.source_set_at = now
        line.source_note = f"Agent {p.kind} (run {str(run_id)[:8]}): {(p.rationale or '')[:240]}"
        line.agent_proposal_id = p.id
        line.agent_confirmed_by = None
        line.agent_confirmed_at = None
        p.status, p.applied_at = "applied", now
        out.applied += 1
        await audit.record(
            session, ctx, action=AuditAction.UPDATE, entity_type="bid_settlement_line_item", entity_id=line.id, project_id=project_id,
            payload={"event": "agent_apply", "proposal_id": str(p.id), "run_id": str(run_id), "kind": p.kind, "rate": str(p.rate),
                     "currency": p.currency, "candidate_ref": p.candidate_ref, "flags": p.flags, "confidence": str(p.confidence)},
        )
    await session.flush()
    return out
