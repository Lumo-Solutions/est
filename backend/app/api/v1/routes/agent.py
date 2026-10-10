from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session, require_roles
from app.core.context import RequestContext
from app.core.enums import Role
from app.schemas.agent import (
    AgentLineConfirm,
    AgentLineOut,
    AgentProposalOut,
    AgentRunCreate,
    AgentRunDetail,
    AgentRunOut,
    AgentSectionOut,
    AgentStepOut,
    AgentSummaryOut,
    BulkConfirmResult,
    ChatMessageOut,
    ChatPost,
    ChatPostOut,
    ConversationOut,
)
from app.services import agent as svc
from app.services.projects import assert_can_see_project

router = APIRouter(tags=["agent"])

# Starting a run, chatting and confirming spend budget and put numbers in a bid: lead_estimator and above.
# Estimators can look at runs, traces and proposals.
_RUN_ROLES = (Role.LEAD_ESTIMATOR.value, Role.PROCUREMENT_HEAD.value, Role.BD_DIRECTOR.value, Role.MANAGING_DIRECTOR.value)
_VIEW_ROLES = (Role.ESTIMATOR.value, *_RUN_ROLES)


async def _detail(session: AsyncSession, run) -> AgentRunDetail:
    sections = await svc.list_sections(session, run.id)
    return AgentRunDetail(**AgentRunOut.model_validate(run).model_dump(), sections=[AgentSectionOut.model_validate(s) for s in sections])


@router.post("/projects/{project_id}/agent/runs", response_model=AgentRunDetail, status_code=202)
async def create_run_endpoint(
    project_id: UUID, body: AgentRunCreate | None = None, ctx: RequestContext = Depends(require_roles(*_RUN_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> AgentRunDetail:
    body = body or AgentRunCreate()
    run = await svc.create_run(
        session, ctx, project_id, sections=body.sections, line_ids=body.line_ids, notes=body.notes, limits=body.limits, create_draft=body.create_draft
    )
    return await _detail(session, run)


@router.get("/projects/{project_id}/agent/runs", response_model=list[AgentRunOut])
async def list_runs_endpoint(
    project_id: UUID, ctx: RequestContext = Depends(require_roles(*_VIEW_ROLES)), session: AsyncSession = Depends(get_session)
) -> list[AgentRunOut]:
    await assert_can_see_project(session, ctx, project_id)
    return [AgentRunOut.model_validate(r) for r in await svc.list_runs(session, project_id)]


@router.get("/agent/runs/{run_id}", response_model=AgentRunDetail)
async def get_run_endpoint(
    run_id: UUID, ctx: RequestContext = Depends(require_roles(*_VIEW_ROLES)), session: AsyncSession = Depends(get_session)
) -> AgentRunDetail:
    return await _detail(session, await svc.get_run(session, run_id))


@router.post("/agent/runs/{run_id}/confirm", response_model=AgentRunDetail, status_code=202)
async def confirm_run_endpoint(
    run_id: UUID, ctx: RequestContext = Depends(require_roles(*_RUN_ROLES)), session: AsyncSession = Depends(get_session)
) -> AgentRunDetail:
    return await _detail(session, await svc.confirm_run(session, ctx, run_id))


@router.post("/agent/runs/{run_id}/pause", response_model=AgentRunDetail)
async def pause_run_endpoint(
    run_id: UUID, ctx: RequestContext = Depends(require_roles(*_RUN_ROLES)), session: AsyncSession = Depends(get_session)
) -> AgentRunDetail:
    return await _detail(session, await svc.pause_run(session, ctx, run_id))


@router.post("/agent/runs/{run_id}/resume", response_model=AgentRunDetail, status_code=202)
async def resume_run_endpoint(
    run_id: UUID, ctx: RequestContext = Depends(require_roles(*_RUN_ROLES)), session: AsyncSession = Depends(get_session)
) -> AgentRunDetail:
    return await _detail(session, await svc.resume_run(session, ctx, run_id))


@router.post("/agent/runs/{run_id}/cancel", response_model=AgentRunDetail)
async def cancel_run_endpoint(
    run_id: UUID, ctx: RequestContext = Depends(require_roles(*_RUN_ROLES)), session: AsyncSession = Depends(get_session)
) -> AgentRunDetail:
    return await _detail(session, await svc.cancel_run(session, ctx, run_id))


@router.get("/agent/runs/{run_id}/steps", response_model=list[AgentStepOut])
async def list_steps_endpoint(
    run_id: UUID, after_seq: int = Query(default=0, ge=0), section_id: UUID | None = None, limit: int = Query(default=200, ge=1, le=500),
    ctx: RequestContext = Depends(require_roles(*_VIEW_ROLES)), session: AsyncSession = Depends(get_session),
) -> list[AgentStepOut]:
    await svc.get_run(session, run_id)
    return [AgentStepOut.model_validate(s) for s in await svc.list_steps(session, run_id, after_seq=after_seq, section_id=section_id, limit=limit)]


@router.get("/agent/proposals/{proposal_id}", response_model=AgentProposalOut)
async def get_proposal_endpoint(
    proposal_id: UUID, ctx: RequestContext = Depends(require_roles(*_VIEW_ROLES)), session: AsyncSession = Depends(get_session)
) -> AgentProposalOut:
    return AgentProposalOut.model_validate(await svc.get_proposal(session, proposal_id))


@router.get("/bid-settlements/{settlement_id}/agent-lines", response_model=list[AgentLineOut])
async def agent_lines_endpoint(
    settlement_id: UUID, ctx: RequestContext = Depends(require_roles(*_VIEW_ROLES)), session: AsyncSession = Depends(get_session)
) -> list[AgentLineOut]:
    return [
        AgentLineOut(
            line_id=l.id, boq_line_item_id=l.boq_line_item_id, cost_source=l.cost_source, direct_unit_cost=l.direct_unit_cost,
            source_currency=l.source_currency, agent_proposal_id=l.agent_proposal_id, agent_confirmed_by=l.agent_confirmed_by,
            agent_confirmed_at=l.agent_confirmed_at, proposal=AgentProposalOut.model_validate(p) if p else None,
        )
        for l, p in await svc.list_agent_lines(session, settlement_id)
    ]


@router.get("/bid-settlements/{settlement_id}/agent-summary", response_model=AgentSummaryOut)
async def agent_summary_endpoint(
    settlement_id: UUID, ctx: RequestContext = Depends(require_roles(*_VIEW_ROLES)), session: AsyncSession = Depends(get_session)
) -> AgentSummaryOut:
    return AgentSummaryOut(**await svc.settlement_agent_summary(session, settlement_id))


@router.post("/bid-settlements/{settlement_id}/lines/{line_id}/agent-confirm", response_model=AgentLineOut)
async def confirm_agent_line_endpoint(
    settlement_id: UUID, line_id: UUID, body: AgentLineConfirm, ctx: RequestContext = Depends(require_roles(*_RUN_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> AgentLineOut:
    line = await svc.confirm_agent_line(session, ctx, settlement_id, line_id, body.proposal_id)
    p = await svc.get_proposal(session, line.agent_proposal_id) if line.agent_proposal_id else None
    return AgentLineOut(
        line_id=line.id, boq_line_item_id=line.boq_line_item_id, cost_source=line.cost_source, direct_unit_cost=line.direct_unit_cost,
        source_currency=line.source_currency, agent_proposal_id=line.agent_proposal_id, agent_confirmed_by=line.agent_confirmed_by,
        agent_confirmed_at=line.agent_confirmed_at, proposal=AgentProposalOut.model_validate(p) if p else None,
    )


@router.post("/bid-settlements/{settlement_id}/agent-confirm-bulk", response_model=BulkConfirmResult)
async def bulk_confirm_endpoint(
    settlement_id: UUID, ctx: RequestContext = Depends(require_roles(*_RUN_ROLES)), session: AsyncSession = Depends(get_session)
) -> BulkConfirmResult:
    return BulkConfirmResult(**await svc.bulk_confirm_agent_lines(session, ctx, settlement_id))


@router.post("/projects/{project_id}/agent/chat", response_model=ChatPostOut, status_code=202)
async def chat_post_endpoint(
    project_id: UUID, body: ChatPost, ctx: RequestContext = Depends(require_roles(*_RUN_ROLES)), session: AsyncSession = Depends(get_session)
) -> ChatPostOut:
    conv, msg, run = await svc.post_chat_message(session, ctx, project_id, body.message, conversation_id=body.conversation_id)
    return ChatPostOut(conversation_id=conv.id, message=ChatMessageOut.model_validate(msg), run_id=run.id)


@router.get("/projects/{project_id}/agent/conversations", response_model=list[ConversationOut])
async def list_conversations_endpoint(
    project_id: UUID, ctx: RequestContext = Depends(require_roles(*_VIEW_ROLES)), session: AsyncSession = Depends(get_session)
) -> list[ConversationOut]:
    await assert_can_see_project(session, ctx, project_id)
    return [ConversationOut.model_validate(c) for c in await svc.list_conversations(session, project_id)]


@router.get("/agent/conversations/{conversation_id}/messages", response_model=list[ChatMessageOut])
async def list_messages_endpoint(
    conversation_id: UUID, after: datetime | None = None, ctx: RequestContext = Depends(require_roles(*_VIEW_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> list[ChatMessageOut]:
    await svc.get_conversation(session, conversation_id)
    return [ChatMessageOut.model_validate(m) for m in await svc.list_messages(session, conversation_id, after=after)]
