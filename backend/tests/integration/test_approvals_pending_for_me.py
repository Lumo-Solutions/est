"""Phase 3 gap-fill (docs/ui-qa-brief.md): home dashboard's "approvals
waiting for me" tile -- app/services/approvals.py::list_pending_for_caller.
No list endpoint existed before this, only get-by-id. Mirrors decide()'s
own "is this actually mine to act on" check exactly (current step's
required_role in the caller's roles, requester excluded per the same SoD
rule decide() enforces)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import RequestContext
from app.db.rls import set_rls_context
from app.services import approvals as approvals_service

pytestmark = pytest.mark.asyncio


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


async def _seed_request(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    requested_by: uuid.UUID,
    current_seq: int,
    step_roles: list[str],
    status: str = "pending",
) -> str:
    # One policy per tenant, reused across calls in the same test -- the
    # (tenant_id, entity_type, version) unique constraint means a second
    # INSERT with the same entity_type in the same tenant collides.
    existing_policy_id = (
        await session.execute(
            text("SELECT id FROM approval_policies WHERE tenant_id = :t AND entity_type = 'cost_rate_change'"),
            {"t": str(tenant_id)},
        )
    ).scalar_one_or_none()
    policy_id = str(
        existing_policy_id
        or (
            await session.execute(
                text(
                    "INSERT INTO approval_policies (tenant_id, entity_type, name) "
                    "VALUES (:t, 'cost_rate_change', 'Test policy') RETURNING id"
                ),
                {"t": str(tenant_id)},
            )
        ).scalar_one()
    )
    request_id = str(
        (
            await session.execute(
                text(
                    "INSERT INTO approval_requests (tenant_id, entity_type, entity_id, amount, currency, "
                    "policy_id, policy_version, status, current_seq, requested_by, requested_at) "
                    "VALUES (:t, 'cost_rate_change', :e, 1000, 'AED', :p, 1, :status, :seq, :rb, :now) RETURNING id"
                ),
                {
                    "t": str(tenant_id),
                    "e": str(uuid.uuid4()),
                    "p": policy_id,
                    "status": status,
                    "seq": current_seq,
                    "rb": str(requested_by),
                    "now": datetime.now(timezone.utc),
                },
            )
        ).scalar_one()
    )
    for seq, role in enumerate(step_roles, start=1):
        await session.execute(
            text(
                "INSERT INTO approval_steps (tenant_id, request_id, seq, required_role, status) "
                "VALUES (:t, :r, :seq, :role, :status)"
            ),
            {
                "t": str(tenant_id),
                "r": request_id,
                "seq": seq,
                "role": role,
                "status": "pending" if seq >= current_seq else "approved",
            },
        )
    return request_id


async def test_lists_only_requests_where_the_current_step_matches_my_role(rls_session):
    tenant_id = await _seed_tenant(rls_session)
    requester = uuid.uuid4()
    caller = uuid.uuid4()
    waiting_on_bd = await _seed_request(
        rls_session, tenant_id, requested_by=requester, current_seq=1, step_roles=["bd_director"]
    )
    waiting_on_md = await _seed_request(
        rls_session, tenant_id, requested_by=requester, current_seq=1, step_roles=["managing_director"]
    )

    bd_ctx = _ctx(frozenset({"bd_director"}), tenant_id=tenant_id, user_id=caller)
    await set_rls_context(rls_session, bd_ctx)
    results = await approvals_service.list_pending_for_caller(rls_session, bd_ctx)

    ids = {str(r.id) for r in results}
    assert waiting_on_bd in ids
    assert waiting_on_md not in ids


async def test_excludes_a_request_the_caller_themself_submitted(rls_session):
    tenant_id = await _seed_tenant(rls_session)
    caller = uuid.uuid4()
    own_request = await _seed_request(
        rls_session, tenant_id, requested_by=caller, current_seq=1, step_roles=["bd_director"]
    )

    bd_ctx = _ctx(frozenset({"bd_director"}), tenant_id=tenant_id, user_id=caller)
    await set_rls_context(rls_session, bd_ctx)
    results = await approvals_service.list_pending_for_caller(rls_session, bd_ctx)

    assert own_request not in {str(r.id) for r in results}


async def test_excludes_a_step_that_is_not_the_current_one_yet(rls_session):
    tenant_id = await _seed_tenant(rls_session)
    requester = uuid.uuid4()
    caller = uuid.uuid4()
    # current_seq=1 (bd_director), so the managing_director step at seq 2
    # isn't reachable yet -- md shouldn't see this in their queue.
    request_id = await _seed_request(
        rls_session,
        tenant_id,
        requested_by=requester,
        current_seq=1,
        step_roles=["bd_director", "managing_director"],
    )

    md_ctx = _ctx(frozenset({"managing_director"}), tenant_id=tenant_id, user_id=caller)
    await set_rls_context(rls_session, md_ctx)
    results = await approvals_service.list_pending_for_caller(rls_session, md_ctx)

    assert request_id not in {str(r.id) for r in results}
