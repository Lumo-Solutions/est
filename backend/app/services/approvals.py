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


def _tier_matches(tier: ApprovalPolicyTier, amount: float, margin_pct: float | None) -> bool:
    bracket_match = float(tier.min_amount) <= amount and (tier.max_amount is None or amount <= float(tier.max_amount))
    # Escalates regardless of amount when the tier defines a margin floor
    # and the caller is below it (strictly less-than) -- e.g. Module D1's
    # bid_submission policy: managing_director if margin-on-sell < 8%, no
    # matter how small the deal. NULL max_margin_pct (every tier before
    # this feature existed) makes this clause always false, so amount-only
    # routing is unchanged for every pre-existing policy.
    margin_match = tier.max_margin_pct is not None and margin_pct is not None and margin_pct < float(tier.max_margin_pct)
    return bracket_match or margin_match


def route_tiers(
    tiers: list[ApprovalPolicyTier], amount: float, mode: str, margin_pct: float | None = None
) -> list[ApprovalPolicyTier]:
    """sequential_up_to_tier: every tier whose min_amount <= amount, in
    order (e.g. a 300k request needs lead_estimator AND procurement_head).
    highest_tier_only: just the single tier that actually brackets amount,
    or is escalated to by margin_pct (see _tier_matches) -- the highest-seq
    tier wins when more than one matches, so any escalation reason
    correctly promotes to the more senior tier."""
    if mode == "highest_tier_only":
        matching = [t for t in tiers if _tier_matches(t, amount, margin_pct)]
        return matching[-1:] if matching else []
    return [t for t in tiers if float(t.min_amount) <= amount]


async def preview_required_role(
    session: AsyncSession, entity_type: str, amount: float, margin_pct: float | None = None
) -> str | None:
    """Read-only preview of which role create_request() would route to for
    this entity_type/amount/margin_pct, without creating anything -- used by
    Module D1's settlement simulate() to show live routing. Returns None if
    there's no active policy or no tier matches."""
    try:
        policy, tiers = await _active_policy(session, entity_type)
    except NotFoundError:
        return None
    routed = route_tiers(tiers, amount, policy.mode, margin_pct=margin_pct)
    return routed[-1].required_role if routed else None


async def create_request(session: AsyncSession, ctx: RequestContext, data: ApprovalRequestCreate) -> ApprovalRequest:
    policy, tiers = await _active_policy(session, data.entity_type)
    routed = route_tiers(tiers, data.amount, policy.mode, margin_pct=data.margin_pct)
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

    # Segregation of duties: whoever created this request (called
    # create_request -- typically by submitting the thing being approved)
    # can never also decide it, regardless of role. Pre-existing gap in
    # this generic engine, found and fixed under Module D1 -- covers every
    # entity_type that uses it (cost_rate_change included), not just
    # bid_submission. See docs/build-log.md's Phase 1 section.
    if request.requested_by == ctx.user_id:
        raise ForbiddenError("The requester cannot decide their own approval request")

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
