"""Phase 8f: admin CRUD for approval policies. Previously these were
DB-configurable in name only -- app/services/approvals.py::_active_policy()
already read them live, but no API existed to view or change them; only
app/cli.py's dev-seed ever wrote a row. RLS itself already restricts
writes on approval_policies/approval_policy_tiers to managing_director
(app/migrations/versions/0008_approvals.py) -- this phase's route-level
role gate matches that pre-existing DB-level restriction, not invents it.
See docs/module-frontend-phase8f-plan.md."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import RequestContext
from app.core.errors import ForbiddenError
from app.db.rls import set_rls_context
from app.schemas.approvals import ApprovalPolicyCreate, ApprovalPolicyTierIn
from app.services import approvals as approvals_service

pytestmark = pytest.mark.asyncio

MD = frozenset({"managing_director"})
BD = frozenset({"bd_director"})


def _ctx(
    roles: frozenset[str], *, tenant_id: uuid.UUID, user_id: uuid.UUID | None = None, is_system: bool = False
) -> RequestContext:
    user_id = user_id or uuid.uuid4()
    return RequestContext(tenant_id=tenant_id, user_id=user_id, sub=str(user_id), roles=roles, is_system=is_system)


async def _seed_tenant(session: AsyncSession) -> uuid.UUID:
    tenant_id = uuid.uuid4()
    sys_ctx = _ctx(frozenset(), tenant_id=tenant_id, is_system=True)
    await set_rls_context(session, sys_ctx)
    await session.execute(
        text("INSERT INTO tenants (id, slug, name) VALUES (:id, :slug, :name)"),
        {"id": str(tenant_id), "slug": f"acme-{uuid.uuid4().hex[:8]}", "name": "Acme"},
    )
    return tenant_id


async def test_create_policy_computes_next_version_and_is_listed(rls_session):
    tenant_id = await _seed_tenant(rls_session)
    md_ctx = _ctx(MD, tenant_id=tenant_id)
    await set_rls_context(rls_session, md_ctx)

    data = ApprovalPolicyCreate(
        entity_type="cost_rate_change",
        name="Cost rate change policy",
        mode="highest_tier_only",
        tiers=[ApprovalPolicyTierIn(seq=1, min_amount=0, required_role="procurement_head")],
    )
    v1, v1_tiers = await approvals_service.create_policy(rls_session, md_ctx, data)
    assert v1.version == 1
    assert v1.is_active is True
    assert len(v1_tiers) == 1

    v2, _ = await approvals_service.create_policy(rls_session, md_ctx, data)
    assert v2.version == 2

    listed = await approvals_service.list_policies(rls_session)
    versions = sorted(p.version for p, _ in listed if p.entity_type == "cost_rate_change")
    assert versions == [1, 2]


async def test_create_policy_denies_non_managing_director(rls_session):
    tenant_id = await _seed_tenant(rls_session)
    bd_ctx = _ctx(BD, tenant_id=tenant_id)
    await set_rls_context(rls_session, bd_ctx)

    data = ApprovalPolicyCreate(
        entity_type="cost_rate_change", name="x",
        tiers=[ApprovalPolicyTierIn(seq=1, required_role="procurement_head")],
    )
    with pytest.raises(ForbiddenError):
        await approvals_service.create_policy(rls_session, bd_ctx, data)


async def test_set_policy_active_toggles_and_deactivated_version_never_routes(rls_session):
    tenant_id = await _seed_tenant(rls_session)
    md_ctx = _ctx(MD, tenant_id=tenant_id)
    await set_rls_context(rls_session, md_ctx)

    data = ApprovalPolicyCreate(
        entity_type="cost_rate_change", name="x", mode="highest_tier_only",
        tiers=[ApprovalPolicyTierIn(seq=1, min_amount=0, required_role="procurement_head")],
    )
    policy, _ = await approvals_service.create_policy(rls_session, md_ctx, data)
    assert await approvals_service.preview_required_role(rls_session, "cost_rate_change", 100.0) == "procurement_head"

    await approvals_service.set_policy_active(rls_session, md_ctx, policy.id, False)
    assert await approvals_service.preview_required_role(rls_session, "cost_rate_change", 100.0) is None
