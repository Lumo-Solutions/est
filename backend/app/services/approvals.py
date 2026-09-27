from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.context import RequestContext
from app.core.enums import AuditAction
from app.core.errors import ConflictError, ForbiddenError, NotFoundError, StepUpRequiredError
from app.models.approvals import ApprovalPolicy, ApprovalPolicyTier, ApprovalRequest, ApprovalStep
from app.schemas.approvals import ApprovalPolicyCreate, ApprovalRequestCreate
from app.security.deps import has_recent_step_up
from app.services import audit


async def list_policies(session: AsyncSession) -> list[tuple[ApprovalPolicy, list[ApprovalPolicyTier]]]:
    """Every policy version (active or not) -- the admin screen needs to
    see history, unlike _active_policy's live-routing lookup below, which
    only ever wants the one currently in effect."""
    result = await session.execute(select(ApprovalPolicy).order_by(ApprovalPolicy.entity_type, ApprovalPolicy.version))
    policies = list(result.scalars().all())
    out = []
    for policy in policies:
        tiers_result = await session.execute(
            select(ApprovalPolicyTier).where(ApprovalPolicyTier.policy_id == policy.id).order_by(ApprovalPolicyTier.seq)
        )
        out.append((policy, list(tiers_result.scalars().all())))
    return out


async def create_policy(
    session: AsyncSession, ctx: RequestContext, data: ApprovalPolicyCreate
) -> tuple[ApprovalPolicy, list[ApprovalPolicyTier]]:
    """New version for entity_type (max existing version + 1), created
    active. Does NOT deactivate prior versions -- _active_policy() always
    picks the highest-version active row for the entity_type, so an old
    version left active is harmless (never selected) but still visible in
    list_policies() for audit history; deactivate it explicitly via
    set_policy_active() if you want it gone from the admin list's
    "active" filter."""
    if not ctx.has_role("managing_director"):
        raise ForbiddenError("Only managing_director may create an approval policy")

    existing = await session.execute(
        select(ApprovalPolicy.version).where(ApprovalPolicy.entity_type == data.entity_type).order_by(ApprovalPolicy.version.desc())
    )
    next_version = (existing.scalars().first() or 0) + 1

    policy = ApprovalPolicy(
        tenant_id=ctx.tenant_id, entity_type=data.entity_type, name=data.name, version=next_version, mode=data.mode,
    )
    session.add(policy)
    await session.flush()

    tiers = [
        ApprovalPolicyTier(
            tenant_id=ctx.tenant_id, policy_id=policy.id, seq=t.seq, min_amount=t.min_amount, max_amount=t.max_amount,
            max_margin_pct=t.max_margin_pct, required_role=t.required_role, quorum=t.quorum, sla_hours=t.sla_hours,
            requires_mfa=t.requires_mfa,
        )
        for t in data.tiers
    ]
    session.add_all(tiers)
    await session.flush()

    await audit.record(
        session, ctx, action=AuditAction.CREATE, entity_type="approval_policy", entity_id=policy.id,
        payload={"entity_type": data.entity_type, "version": next_version},
    )
    return policy, tiers


async def set_policy_active(
    session: AsyncSession, ctx: RequestContext, policy_id: UUID, is_active: bool
) -> tuple[ApprovalPolicy, list[ApprovalPolicyTier]]:
    if not ctx.has_role("managing_director"):
        raise ForbiddenError("Only managing_director may change an approval policy's active status")

    result = await session.execute(select(ApprovalPolicy).where(ApprovalPolicy.id == policy_id))
    policy = result.scalar_one_or_none()
    if policy is None:
        raise NotFoundError(f"Approval policy {policy_id} not found")
    policy.is_active = is_active
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.UPDATE, entity_type="approval_policy", entity_id=policy.id,
        payload={"is_active": is_active},
    )
    tiers_result = await session.execute(
        select(ApprovalPolicyTier).where(ApprovalPolicyTier.policy_id == policy.id).order_by(ApprovalPolicyTier.seq)
    )
    return policy, list(tiers_result.scalars().all())


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


def _tier_matches(tier: ApprovalPolicyTier, amount: Decimal, margin_pct: Decimal | None) -> bool:
    # Decimal end to end -- min_amount/max_amount/max_margin_pct already
    # come back from Postgres as Decimal (Numeric columns, asdecimal=True
    # by default), and amount/margin_pct are Decimal all the way from
    # app/services/settlement.py's Decimal-only math. No float() here: a
    # 3dp-quantized margin like 7.995 must stay exactly 7.995 through this
    # comparison rather than round-tripping through a binary float.
    bracket_match = tier.min_amount <= amount and (tier.max_amount is None or amount <= tier.max_amount)
    # Escalates regardless of amount when the tier defines a margin floor
    # and the caller is below it (strictly less-than) -- e.g. Module D1's
    # bid_submission policy: managing_director if margin-on-sell < 8%, no
    # matter how small the deal. NULL max_margin_pct (every tier before
    # this feature existed) makes this clause always false, so amount-only
    # routing is unchanged for every pre-existing policy.
    margin_match = tier.max_margin_pct is not None and margin_pct is not None and margin_pct < tier.max_margin_pct
    return bracket_match or margin_match


def route_tiers(
    tiers: list[ApprovalPolicyTier], amount: Decimal, mode: str, margin_pct: Decimal | None = None
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
    return [t for t in tiers if t.min_amount <= amount]


async def preview_required_role(
    session: AsyncSession, entity_type: str, amount: Decimal, margin_pct: Decimal | None = None
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
        # str(), not the Decimal itself -- audit payloads go through
        # JSONB's plain json.dumps (app/services/audit.py), which can't
        # serialize Decimal (found by tests/api/test_approvals_api.py
        # while making this path Decimal end to end; see the settlement
        # audit call a few lines below in app/services/settlement.py,
        # which already stringifies its Decimal totals the same way).
        payload={"entity_type": data.entity_type, "entity_id": str(data.entity_id), "amount": str(data.amount)},
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
    # has_recent_step_up (app/security/deps.py) checks acr AND that the
    # underlying auth_time is actually recent -- acr=silver alone can
    # persist on a still-valid session/token long after the OTP entry that
    # earned it. See fix/keycloak-step-up.
    if not has_recent_step_up(ctx, get_settings()):
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
