from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import RequestContext
from app.core.enums import AuditAction
from app.core.errors import ConflictError, ForbiddenError, NotFoundError, StepUpRequiredError
from app.models.approvals import ApprovalPolicy, ApprovalPolicyTier, ApprovalRequest, ApprovalStep
from app.schemas.approvals import ApprovalRequestCreate
from app.services import audit

_ACR_RANK = {"bronze": 1, "silver": 2}


async def _active_policy(session: AsyncSession, entity_type: str) -> tuple[ApprovalPolicy, list[ApprovalPolicyTier]]:
    result = await session.execute(
        select(ApprovalPolicy)
        .where(ApprovalPolicy.entity_type == entity_type, ApprovalPolicy.is_active.is_(True))
        .order_by(ApprovalPolicy.version.desc())
    )
    policy = result.scalars().first()
    if policy is None:
        raise NotFoundError(f"No active approval policy for entity_type={entity_type}")
    tiers_result = await session.execute(
        select(ApprovalPolicyTier)
        .where(ApprovalPolicyTier.policy_id == policy.id)
        .order_by(ApprovalPolicyTier.seq)
    )
    return policy, list(tiers_result.scalars().all())


def route_tiers(tiers: list[ApprovalPolicyTier], amount: float, mode: str) -> list[ApprovalPolicyTier]:
    """sequential_up_to_tier: every tier whose min_amount <= amount, in
    order (e.g. a 300k request needs lead_estimator AND procurement_head).
    highest_tier_only: just the single tier that actually brackets amount."""
    matching = [t for t in tiers if float(t.min_amount) <= amount and (t.max_amount is None or amount <= float(t.max_amount))]
    if mode == "highest_tier_only":
        return matching[-1:] if matching else []
    return [t for t in tiers if float(t.min_amount) <= amount]


async def create_request(session: AsyncSession, ctx: RequestContext, data: ApprovalRequestCreate) -> ApprovalRequest:
    policy, tiers = await _active_policy(session, data.entity_type)
    routed = route_tiers(tiers, data.amount, policy.mode)
    if not routed:
        raise ConflictError(f"No approval tier matches amount {data.amount} for policy {policy.name}")

    request = ApprovalRequest(
        tenant_id=ctx.tenant_id,
        project_id=data.project_id,
        entity_type=data.entity_type,
        entity_id=data.entity_id,
        amount=data.amount,
        currency=data.currency,
        policy_id=policy.id,
        policy_version=policy.version,
        status="pending",
        current_seq=1,
        payload_snapshot=data.payload_snapshot,
        requested_by=ctx.user_id,
        requested_at=datetime.now(timezone.utc),
    )
    session.add(request)
    await session.flush()

    for i, tier in enumerate(routed, start=1):
        session.add(
            ApprovalStep(
                tenant_id=ctx.tenant_id,
                request_id=request.id,
                project_id=data.project_id,
                seq=i,
                required_role=tier.required_role,
                status="pending",
            )
        )
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.CREATE, entity_type="approval_request", entity_id=request.id,
        project_id=data.project_id,
        payload={"entity_type": data.entity_type, "entity_id": str(data.entity_id), "amount": data.amount},
    )
    return request


async def get_request(session: AsyncSession, request_id: UUID) -> tuple[ApprovalRequest, list[ApprovalStep]]:
    result = await session.execute(select(ApprovalRequest).where(ApprovalRequest.id == request_id))
    request = result.scalar_one_or_none()
    if request is None:
        raise NotFoundError(f"Approval request {request_id} not found")
    steps_result = await session.execute(
        select(ApprovalStep).where(ApprovalStep.request_id == request.id).order_by(ApprovalStep.seq)
    )
    return request, list(steps_result.scalars().all())


async def decide(
    session: AsyncSession, ctx: RequestContext, request_id: UUID, *, approve: bool, note: str | None
) -> ApprovalRequest:
    request, steps = await get_request(session, request_id)
    if request.status != "pending":
        raise ConflictError(f"Approval request is already {request.status}")

    current_step = next((s for s in steps if s.seq == request.current_seq), None)
    if current_step is None or current_step.status != "pending":
        raise ConflictError("No pending step at the current sequence")

    if current_step.required_role not in ctx.roles:
        raise ForbiddenError(f"This step requires role {current_step.required_role}")

    # Tier's requires_mfa is checked against the caller's token acr claim --
    # policy tiers default requires_mfa=true (migration 0008 seed).
    if (_ACR_RANK.get(ctx.acr or "", 0)) < _ACR_RANK.get("silver", 2):
        raise StepUpRequiredError("This approval decision requires a recent MFA step-up")

    current_step.status = "approved" if approve else "rejected"
    current_step.decided_by = ctx.user_id
    current_step.decided_at = datetime.now(timezone.utc)
    current_step.decision_note = note
    current_step.decided_ip = ctx.ip_address
    current_step.decided_acr = ctx.acr

    if not approve:
        request.status = "rejected"
        request.completed_at = datetime.now(timezone.utc)
    elif request.current_seq >= max(s.seq for s in steps):
        request.status = "approved"
        request.completed_at = datetime.now(timezone.utc)
    else:
        request.current_seq += 1

    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.APPROVE if approve else AuditAction.REJECT,
        entity_type="approval_request", entity_id=request.id, project_id=request.project_id,
        payload={"step_seq": current_step.seq, "note": note},
    )
    return request
