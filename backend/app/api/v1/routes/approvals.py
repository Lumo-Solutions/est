from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_session, require_roles
from app.core.context import RequestContext
from app.core.enums import Role
from app.schemas.approvals import (
    ApprovalDecision,
    ApprovalPolicyCreate,
    ApprovalPolicyOut,
    ApprovalPolicySetActive,
    ApprovalRequestCreate,
    ApprovalRequestOut,
    ApprovalStepOut,
    ApprovalPolicyTierOut,
)
from app.services import approvals as approvals_service

router = APIRouter(prefix="/approvals", tags=["approvals"])

# Approval policies govern who has authority to approve what -- a
# governance control, deliberately restricted to a single senior tier
# rather than the usual three-role "structure" set used for other
# admin-config tables (taxonomy, tolerances, layer-trade mappings) in
# this build.
_POLICY_ADMIN_ROLES = (Role.MANAGING_DIRECTOR.value,)


def _policy_to_out(policy, tiers) -> ApprovalPolicyOut:
    out = ApprovalPolicyOut.model_validate(policy)
    out.tiers = [ApprovalPolicyTierOut.model_validate(t) for t in tiers]
    return out


@router.get("/policies", response_model=list[ApprovalPolicyOut])
async def list_policies_endpoint(
    ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> list[ApprovalPolicyOut]:
    policies = await approvals_service.list_policies(session)
    return [_policy_to_out(policy, tiers) for policy, tiers in policies]


@router.post("/policies", response_model=ApprovalPolicyOut, status_code=201)
async def create_policy_endpoint(
    data: ApprovalPolicyCreate,
    ctx: RequestContext = Depends(require_roles(*_POLICY_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> ApprovalPolicyOut:
    policy, tiers = await approvals_service.create_policy(session, ctx, data)
    return _policy_to_out(policy, tiers)


@router.patch("/policies/{policy_id}", response_model=ApprovalPolicyOut)
async def set_policy_active_endpoint(
    policy_id: UUID,
    data: ApprovalPolicySetActive,
    ctx: RequestContext = Depends(require_roles(*_POLICY_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> ApprovalPolicyOut:
    policy, tiers = await approvals_service.set_policy_active(session, ctx, policy_id, data.is_active)
    return _policy_to_out(policy, tiers)


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
