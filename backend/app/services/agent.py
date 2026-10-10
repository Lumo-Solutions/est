"""BOQ agent: starting, confirming, pausing and cancelling runs; the trace; confirming agent-filled settlement lines; chat
(docs/boq-agent/plan.md sections 3.5-3.6, brief 2.4 and 2.8).

The agent only ever *proposes*. What changes a settlement is the applier (app/agent/applier.py, as the person who started the
run), and what lets an agent line count toward a submitted bid is a person's confirmation here.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import applier, boq_view
from app.agent.runner import default_limits
from app.ai.pricing import estimate_cost_usd, is_unverified
from app.ai.provider import EXTRACT, TIER_REASONING
from app.ai.registry import resolve_model
from app.core.config import get_settings
from app.core.context import RequestContext
from app.core.enums import AuditAction, BidSettlementStatus
from app.core.errors import ConflictError, ForbiddenError, NotFoundError, ValidationAppError
from app.models.agent import AgentConversation, AgentLineProposal, AgentMessage, AgentRun, AgentRunSection, AgentStep
from app.models.boq import BoqLineItem
from app.models.settlement import BidSettlement, BidSettlementLineItem
from app.pricing import engine as pe
from app.services import audit
from app.services import settlement as settlement_service
from app.services.projects import assert_can_see_project

RUN_ROLES = ("lead_estimator", "procurement_head", "bd_director", "managing_director")
VIEW_ROLES = ("estimator", *RUN_ROLES)
ACTIVE = ("awaiting_confirm", "queued", "planning", "running", "paused")
CEILING = {"max_steps": 100, "max_page_views": 300, "max_usd": 50.0}
# Rough per-step size of a section loop (system prompt + bounded context in; one small JSON object out).
STEP_TOKENS_IN, STEP_TOKENS_OUT = 5_000, 350
PLAN_TOKENS_IN, PLAN_TOKENS_OUT = 4_000, 800
VISION_TOKENS_IN, VISION_TOKENS_OUT = 1_800, 300


Enqueue = Callable[[str, UUID, UUID], None]


def _default_enqueue(kind: str, run_id: UUID, tenant_id: UUID) -> None:
    from app.workers.tasks import agent as agent_tasks

    agent_tasks.enqueue(kind, run_id, tenant_id, countdown=3)


def _require(ctx: RequestContext, roles: tuple[str, ...], action: str) -> None:
    if not ctx.has_role(*roles):
        raise ForbiddenError(f"{action} requires one of roles: {', '.join(roles)}")


# ------------------------------------------------------------------------------------------------ estimate
def estimate_run(sections: list[boq_view.SectionSpec], limits: dict, *, provider: str, model: str, external: bool) -> dict:
    """An upper-ish estimate shown before an external provider is used. Local and mock providers cost nothing."""
    steps = sum(min(int(limits["max_steps"]), 8 + math.ceil(len(s.line_ids) * 0.7)) for s in sections)
    views = min(int(limits["max_page_views"]), max(1, steps // 4))
    usd = (
        estimate_cost_usd(provider, model, STEP_TOKENS_IN * steps + PLAN_TOKENS_IN, STEP_TOKENS_OUT * steps + PLAN_TOKENS_OUT)
        + estimate_cost_usd(provider, model, VISION_TOKENS_IN * views, VISION_TOKENS_OUT * views)
    )
    cap = Decimal(str(limits["max_usd"]))
    return {
        "provider": provider, "model": model, "external": external, "sections": len(sections),
        "steps": steps, "page_views": views, "usd": float(min(usd, cap)), "usd_uncapped": float(usd), "usd_cap": float(cap),
        "unverified_price": bool(external and is_unverified(model)),
        "note": None if external else "Local or mock provider: no external cost.",
    }


def _clamp_limits(raw: dict | None) -> dict:
    out = default_limits()
    for k, v in (raw or {}).items():
        if k in out and v is not None:
            floor = 0.000001 if k == "max_usd" else 1
            out[k] = max(floor, min(float(v), CEILING[k]))
            if k != "max_usd":
                out[k] = int(out[k])
    return out


# ------------------------------------------------------------------------------------------------ runs
async def _active_run(session: AsyncSession, project_id: UUID) -> AgentRun | None:
    return (
        await session.execute(
            select(AgentRun).where(AgentRun.project_id == project_id, AgentRun.kind == "run", AgentRun.status.in_(ACTIVE)).limit(1)
        )
    ).scalar_one_or_none()


async def create_run(
    session: AsyncSession, ctx: RequestContext, project_id: UUID, *, sections: list[str] | None = None, line_ids: list[UUID] | None = None,
    notes: dict[str, str] | None = None, limits: dict | None = None, create_draft: bool = False, enqueue: Enqueue | None = None,
    from_chat: bool = False,
) -> AgentRun:
    from app.ai.factory import default_gateway

    _require(ctx, RUN_ROLES, "Starting an estimation agent run")
    await assert_can_see_project(session, ctx, project_id)
    if await _active_run(session, project_id) is not None:
        raise ConflictError("An agent run is already in progress for this project: pause or cancel it first")
    items = list((await session.execute(select(BoqLineItem).where(BoqLineItem.project_id == project_id).order_by(BoqLineItem.path))).scalars())
    specs = boq_view.build_sections(items)
    if not specs:
        raise ValidationAppError("This project has no BOQ lines with quantities yet: import the BOQ first")
    scope: dict = {"mode": "all", "notes": notes or {}}
    if sections:
        chosen = [boq_view.find_section(specs, key) for key in sections]
        missing = [k for k, c in zip(sections, chosen) if c is None]
        if missing:
            raise ValidationAppError(f"Unknown BOQ section: {', '.join(missing)}")
        specs = [s for s in {id(c): c for c in chosen if c}.values()]
        scope.update(mode="sections", sections=[str(s.section_item_id) for s in specs])
    if line_ids:
        wanted = set(line_ids)
        narrowed = []
        for s in specs:
            keep = [i for i in s.line_ids if i in wanted]
            if keep:
                s.line_ids = keep
                narrowed.append(s)
        if not narrowed:
            raise ValidationAppError("None of those lines belong to this project's BOQ")
        specs = narrowed
        scope.update(mode="lines", line_ids=[str(i) for i in line_ids])

    current = await applier.current_settlement(session, project_id)
    if current is None or (current.status != BidSettlementStatus.DRAFT.value and create_draft):
        current = await settlement_service.build_settlement_draft(session, ctx, project_id)
    elif current.status != BidSettlementStatus.DRAFT.value:
        raise ConflictError(
            f"The current settlement is {current.status}; the agent fills only a draft. Start a new draft version (create_draft) or leave it as it is"
        )

    settings = get_settings()
    gw = default_gateway(settings)
    status = gw.status()
    model = resolve_model(settings, gw.provider.name, EXTRACT, TIER_REASONING)
    lim = _clamp_limits(limits)
    est = estimate_run(specs, lim, provider=status["provider"], model=model, external=bool(status["external"]))
    run = AgentRun(
        tenant_id=ctx.tenant_id, project_id=project_id, kind="run", settlement_id=current.id,
        status="awaiting_confirm" if status["external"] else "queued", scope=scope, limits=lim, estimate=est, provider=status["provider"],
        started_by=ctx.user_id, started_by_roles=sorted(ctx.roles), created_by=ctx.user_id,
    )
    session.add(run)
    await session.flush()
    for seq, s in enumerate(specs):
        session.add(
            AgentRunSection(
                tenant_id=ctx.tenant_id, project_id=project_id, run_id=run.id, section_item_id=s.section_item_id, label=s.label[:255], seq=seq,
                line_count=len(s.line_ids), line_ids=[str(i) for i in s.line_ids],
            )
        )
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.CREATE, entity_type="agent_run", entity_id=run.id, project_id=project_id,
        payload={"scope": scope["mode"], "sections": len(specs), "limits": lim, "estimate_usd": est["usd"], "provider": status["provider"],
                 "external": est["external"], "from_chat": from_chat, "settlement_id": str(current.id)},
    )
    if run.status == "queued":
        (enqueue or _default_enqueue)("plan", run.id, ctx.tenant_id)
    return run


async def get_run(session: AsyncSession, run_id: UUID) -> AgentRun:
    run = (await session.execute(select(AgentRun).where(AgentRun.id == run_id))).scalar_one_or_none()
    if run is None:
        raise NotFoundError(f"Agent run {run_id} not found")
    return run


async def list_runs(session: AsyncSession, project_id: UUID, limit: int = 20) -> list[AgentRun]:
    return list(
        (await session.execute(select(AgentRun).where(AgentRun.project_id == project_id, AgentRun.kind == "run").order_by(AgentRun.created_at.desc()).limit(limit))).scalars()
    )


async def list_sections(session: AsyncSession, run_id: UUID) -> list[AgentRunSection]:
    return list((await session.execute(select(AgentRunSection).where(AgentRunSection.run_id == run_id).order_by(AgentRunSection.seq))).scalars())


async def list_steps(session: AsyncSession, run_id: UUID, *, after_seq: int = 0, section_id: UUID | None = None, limit: int = 200) -> list[AgentStep]:
    stmt = select(AgentStep).where(AgentStep.run_id == run_id, AgentStep.seq > after_seq)
    if section_id is not None:
        stmt = stmt.where(AgentStep.section_id == section_id)
    return list((await session.execute(stmt.order_by(AgentStep.seq).limit(min(limit, 500)))).scalars())


async def confirm_run(session: AsyncSession, ctx: RequestContext, run_id: UUID, *, enqueue: Enqueue | None = None) -> AgentRun:
    """The cost confirmation for a run on an external provider (reuses the idea of the intake cost confirm: nothing is spent
    until a lead estimator has seen the estimate)."""
    _require(ctx, RUN_ROLES, "Confirming an agent run")
    run = await get_run(session, run_id)
    if run.status != "awaiting_confirm":
        raise ConflictError(f"This run is {run.status}; only a run waiting for confirmation can be confirmed")
    run.status, run.confirmed_by, run.confirmed_at = "queued", ctx.user_id, datetime.now(timezone.utc)
    # The person who confirms is the one the applier acts as: they saw the estimate and own what lands in the draft.
    run.started_by, run.started_by_roles = ctx.user_id, sorted(ctx.roles)
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.UPDATE, entity_type="agent_run", entity_id=run.id, project_id=run.project_id,
        payload={"event": "confirm_cost", "estimate_usd": (run.estimate or {}).get("usd"), "limits": run.limits},
    )
    (enqueue or _default_enqueue)("plan", run.id, ctx.tenant_id)
    return run


async def pause_run(session: AsyncSession, ctx: RequestContext, run_id: UUID) -> AgentRun:
    _require(ctx, RUN_ROLES, "Pausing an agent run")
    run = await get_run(session, run_id)
    if run.status not in ("running", "planning", "queued"):
        raise ConflictError(f"A {run.status} run cannot be paused")
    run.status = "paused"
    await session.flush()
    await audit.record(session, ctx, action=AuditAction.UPDATE, entity_type="agent_run", entity_id=run.id, project_id=run.project_id, payload={"event": "pause"})
    return run


async def resume_run(session: AsyncSession, ctx: RequestContext, run_id: UUID, *, enqueue: Enqueue | None = None) -> AgentRun:
    _require(ctx, RUN_ROLES, "Resuming an agent run")
    run = await get_run(session, run_id)
    if run.status != "paused":
        raise ConflictError(f"A {run.status} run cannot be resumed")
    run.status = "running" if run.plan is not None else "queued"
    await session.flush()
    await audit.record(session, ctx, action=AuditAction.UPDATE, entity_type="agent_run", entity_id=run.id, project_id=run.project_id, payload={"event": "resume"})
    (enqueue or _default_enqueue)("section" if run.status == "running" else "plan", run.id, ctx.tenant_id)
    return run


async def cancel_run(session: AsyncSession, ctx: RequestContext, run_id: UUID) -> AgentRun:
    _require(ctx, RUN_ROLES, "Cancelling an agent run")
    run = await get_run(session, run_id)
    if run.status not in ACTIVE:
        raise ConflictError(f"A {run.status} run cannot be cancelled")
    run.status = "cancelled"
    await session.execute(
        update(AgentRunSection).where(AgentRunSection.run_id == run.id, AgentRunSection.status.in_(("pending", "paused"))).values(status="cancelled")
    )
    reading = (await session.execute(select(func.count()).select_from(AgentRunSection).where(AgentRunSection.run_id == run.id, AgentRunSection.status == "reading"))).scalar_one()
    if not reading:
        run.finished_at = datetime.now(timezone.utc)
    await session.flush()
    await audit.record(session, ctx, action=AuditAction.UPDATE, entity_type="agent_run", entity_id=run.id, project_id=run.project_id, payload={"event": "cancel"})
    return run


# ------------------------------------------------------------------------------------------------ proposals / confirmation
async def get_proposal(session: AsyncSession, proposal_id: UUID) -> AgentLineProposal:
    p = (await session.execute(select(AgentLineProposal).where(AgentLineProposal.id == proposal_id))).scalar_one_or_none()
    if p is None:
        raise NotFoundError(f"Agent proposal {proposal_id} not found")
    return p


async def list_agent_lines(session: AsyncSession, settlement_id: UUID) -> list[tuple[BidSettlementLineItem, AgentLineProposal | None]]:
    """The settlement's agent-filled lines with the proposal behind each (for the evidence drawer)."""
    lines = list(
        (
            await session.execute(
                select(BidSettlementLineItem).where(
                    BidSettlementLineItem.settlement_id == settlement_id,
                    BidSettlementLineItem.cost_source.in_(applier.AGENT_SOURCES),
                )
            )
        ).scalars()
    )
    props = {
        p.id: p
        for p in (await session.execute(select(AgentLineProposal).where(AgentLineProposal.id.in_([l.agent_proposal_id for l in lines if l.agent_proposal_id] or [UUID(int=0)])))).scalars()
    }
    return [(l, props.get(l.agent_proposal_id)) for l in lines]


async def confirm_agent_line(session: AsyncSession, ctx: RequestContext, settlement_id: UUID, line_id: UUID, proposal_id: UUID) -> BidSettlementLineItem:
    """A lead estimator confirms one agent line. `proposal_id` is the proposal they looked at: if the line has moved on since
    (a re-run replaced it) the confirmation is refused, so nobody confirms something they have not seen."""
    _require(ctx, RUN_ROLES, "Confirming an agent-filled line")
    settlement = await settlement_service._get_settlement(session, settlement_id)
    settlement_service._require_draft(settlement)
    line = await settlement_service._get_line(session, settlement_id, line_id)
    if line.cost_source not in applier.AGENT_SOURCES or line.agent_proposal_id is None:
        raise ConflictError("This line was not filled by the agent")
    if line.agent_proposal_id != proposal_id:
        raise ConflictError("The agent changed this line after you opened it: reload and look at it again")
    if line.agent_confirmed_by is not None:
        return line
    p = await get_proposal(session, proposal_id)
    line.agent_confirmed_by, line.agent_confirmed_at = ctx.user_id, datetime.now(timezone.utc)
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.UPDATE, entity_type="bid_settlement_line_item", entity_id=line.id, project_id=settlement.project_id,
        payload={"event": "agent_confirm", "proposal_id": str(p.id), "kind": p.kind, "rate": str(p.rate), "currency": p.currency, "confidence": str(p.confidence), "flags": p.flags},
    )
    return line


async def bulk_confirm_agent_lines(session: AsyncSession, ctx: RequestContext, settlement_id: UUID) -> dict:
    """Confirms every unconfirmed `agent_candidate` line that passes the bulk-accept test (confidence at or above the
    threshold, no blocking flag). Estimates are never bulk-confirmed."""
    _require(ctx, RUN_ROLES, "Confirming agent-filled lines")
    settlement = await settlement_service._get_settlement(session, settlement_id)
    settlement_service._require_draft(settlement)
    confirmed, skipped = 0, {"estimate": 0, "blocked_or_low_confidence": 0}
    now = datetime.now(timezone.utc)
    for line, p in await list_agent_lines(session, settlement_id):
        if line.agent_confirmed_by is not None or p is None:
            continue
        if p.kind != "candidate":
            skipped["estimate"] += 1
            continue
        if float(p.confidence) < pe.BULK_ACCEPT_MIN_CONFIDENCE or pe.is_blocked(list(p.flags or [])):
            skipped["blocked_or_low_confidence"] += 1
            continue
        line.agent_confirmed_by, line.agent_confirmed_at = ctx.user_id, now
        confirmed += 1
        await audit.record(
            session, ctx, action=AuditAction.UPDATE, entity_type="bid_settlement_line_item", entity_id=line.id, project_id=settlement.project_id,
            payload={"event": "agent_confirm", "bulk": True, "proposal_id": str(p.id), "rate": str(p.rate), "currency": p.currency},
        )
    await session.flush()
    return {"confirmed": confirmed, "skipped": skipped}


async def settlement_agent_summary(session: AsyncSession, settlement_id: UUID) -> dict:
    lines = await list_agent_lines(session, settlement_id)
    return {"agent_lines": len(lines), "unconfirmed": sum(1 for l, _ in lines if l.agent_confirmed_by is None)}


# ------------------------------------------------------------------------------------------------ chat
async def get_conversation(session: AsyncSession, conversation_id: UUID) -> AgentConversation:
    c = (await session.execute(select(AgentConversation).where(AgentConversation.id == conversation_id))).scalar_one_or_none()
    if c is None:
        raise NotFoundError(f"Conversation {conversation_id} not found")
    return c


async def post_chat_message(
    session: AsyncSession, ctx: RequestContext, project_id: UUID, message: str, *, conversation_id: UUID | None = None, enqueue: Enqueue | None = None
) -> tuple[AgentConversation, AgentMessage, AgentRun]:
    from app.ai.factory import default_gateway

    _require(ctx, RUN_ROLES, "Chatting with the estimation agent")
    await assert_can_see_project(session, ctx, project_id)
    message = message.strip()
    if not message:
        raise ValidationAppError("Write a message first")
    if conversation_id is None:
        conv = AgentConversation(tenant_id=ctx.tenant_id, project_id=project_id, title=message[:80], created_by=ctx.user_id)
        session.add(conv)
        await session.flush()
    else:
        conv = await get_conversation(session, conversation_id)
        if conv.project_id != project_id:
            raise NotFoundError(f"Conversation {conversation_id} not found")
        busy = (await session.execute(select(AgentRun.id).where(AgentRun.conversation_id == conv.id, AgentRun.status.in_(("queued", "running"))).limit(1))).scalar_one_or_none()
        if busy is not None:
            raise ConflictError("The agent is still answering your last message")
    current = await applier.current_settlement(session, project_id)
    settings = get_settings()
    status = default_gateway(settings).status()
    user_msg = AgentMessage(tenant_id=ctx.tenant_id, project_id=project_id, conversation_id=conv.id, role="user", content=message[:4000], created_by=ctx.user_id, created_at=datetime.now(timezone.utc))
    session.add(user_msg)
    run = AgentRun(
        tenant_id=ctx.tenant_id, project_id=project_id, kind="chat", conversation_id=conv.id, settlement_id=current.id if current else None,
        status="queued", scope={"mode": "chat"}, limits=default_limits(settings, chat=True), provider=status["provider"],
        started_by=ctx.user_id, started_by_roles=sorted(ctx.roles), created_by=ctx.user_id,
    )
    session.add(run)
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.CREATE, entity_type="agent_run", entity_id=run.id, project_id=project_id,
        payload={"kind": "chat", "conversation_id": str(conv.id), "limits": run.limits, "provider": status["provider"]},
    )
    (enqueue or _default_enqueue)("chat", run.id, ctx.tenant_id)
    return conv, user_msg, run


async def list_messages(session: AsyncSession, conversation_id: UUID, *, after: datetime | None = None) -> list[AgentMessage]:
    stmt = select(AgentMessage).where(AgentMessage.conversation_id == conversation_id)
    if after is not None:
        stmt = stmt.where(AgentMessage.created_at > after)
    return list((await session.execute(stmt.order_by(AgentMessage.created_at, AgentMessage.id).limit(200))).scalars())


async def list_conversations(session: AsyncSession, project_id: UUID) -> list[AgentConversation]:
    return list(
        (await session.execute(select(AgentConversation).where(AgentConversation.project_id == project_id).order_by(AgentConversation.created_at.desc()).limit(20))).scalars()
    )
