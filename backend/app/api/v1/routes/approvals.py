from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_session
from app.core.context import RequestContext
from app.schemas.approvals import ApprovalDecision, ApprovalRequestCreate, ApprovalRequestOut, ApprovalStepOut
from app.services import approvals as approvals_service

router = APIRouter(prefix="/approvals", tags=["approvals"])


def _to_out(request, steps) -> ApprovalRequestOut:
    out = ApprovalRequestOut.model_validate(request)
    out.steps = [ApprovalStepOut.model_validate(s) for s in steps]
    return out


@router.post("", response_model=ApprovalRequestOut, status_code=201)
async def create_request_endpoint(
    data: ApprovalRequestCreate,
    ctx: RequestContext = CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> ApprovalRequestOut:
    request = await approvals_service.create_request(session, ctx, data)
    _, steps = await approvals_service.get_request(session, request.id)
    return _to_out(request, steps)


@router.get("/{request_id}", response_model=ApprovalRequestOut)
async def get_request_endpoint(
    request_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> ApprovalRequestOut:
    request, steps = await approvals_service.get_request(session, request_id)
    return _to_out(request, steps)


@router.post("/{request_id}/decide", response_model=ApprovalRequestOut)
async def decide_endpoint(
    request_id: UUID,
    data: ApprovalDecision,
    ctx: RequestContext = CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> ApprovalRequestOut:
    request = await approvals_service.decide(session, ctx, request_id, approve=data.approve, note=data.note)
    _, steps = await approvals_service.get_request(session, request.id)
    return _to_out(request, steps)
