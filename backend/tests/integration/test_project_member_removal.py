"""DELETE /projects/{id}/members/{user_id} -- app/services/projects.py::remove_member.

Runs under real RLS as a non-system lead_estimator (the lowest role the route
allows), so it also proves project_members' DELETE policy actually lets that
role delete -- the 0028-style failure where RLS silently deletes 0 rows."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import RequestContext
from app.core.errors import NotFoundError
from app.db.rls import set_rls_context
from app.services import projects as projects_service

pytestmark = pytest.mark.asyncio


def _ctx(roles: frozenset[str], *, tenant_id: uuid.UUID, user_id: uuid.UUID, is_system: bool = False) -> RequestContext:
    return RequestContext(tenant_id=tenant_id, user_id=user_id, sub=str(user_id), roles=roles, is_system=is_system)


async def _seed(session: AsyncSession, member_ids: list[uuid.UUID]) -> tuple[uuid.UUID, uuid.UUID]:
    tenant_id = uuid.uuid4()
    await session.execute(
        text("INSERT INTO tenants (id, slug, name) VALUES (:id, :slug, :name)"),
        {"id": str(tenant_id), "slug": f"pmr-{uuid.uuid4().hex[:8]}", "name": "PM Removal Test"},
    )
    await set_rls_context(session, _ctx(frozenset(), tenant_id=tenant_id, user_id=uuid.uuid4(), is_system=True))
    project_id = (
        await session.execute(
            text("INSERT INTO projects (tenant_id, code, name) VALUES (:t, :c, 'A') RETURNING id"),
            {"t": str(tenant_id), "c": f"PMR-{uuid.uuid4().hex[:8]}"},
        )
    ).scalar_one()
    for uid in member_ids:
        await session.execute(
            text("INSERT INTO project_members (project_id, user_id, tenant_id, project_role) VALUES (:p, :u, :t, 'estimator')"),
            {"p": str(project_id), "u": str(uid), "t": str(tenant_id)},
        )
    return tenant_id, project_id


async def test_lead_estimator_removes_a_member_and_the_removal_is_audited(rls_session: AsyncSession):
    lead_id, victim_id, bystander_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    tenant_id, project_id = await _seed(rls_session, [lead_id, victim_id, bystander_id])
    lead_ctx = _ctx(frozenset({"lead_estimator"}), tenant_id=tenant_id, user_id=lead_id)
    await set_rls_context(rls_session, lead_ctx)

    await projects_service.remove_member(rls_session, lead_ctx, project_id, victim_id)

    remaining = {m.user_id for m in await projects_service.list_members(rls_session, project_id)}
    assert remaining == {lead_id, bystander_id}

    await set_rls_context(rls_session, _ctx(frozenset(), tenant_id=tenant_id, user_id=uuid.uuid4(), is_system=True))
    payload = (
        await rls_session.execute(
            text(
                "SELECT payload FROM audit_events WHERE tenant_id = :t AND entity_type = 'project' "
                "AND action = 'delete' ORDER BY seq DESC LIMIT 1"
            ),
            {"t": str(tenant_id)},
        )
    ).scalar_one()
    assert payload == {"member_removed": str(victim_id), "role": "estimator"}


async def test_removing_a_non_member_404s(rls_session: AsyncSession):
    lead_id = uuid.uuid4()
    tenant_id, project_id = await _seed(rls_session, [lead_id])
    lead_ctx = _ctx(frozenset({"lead_estimator"}), tenant_id=tenant_id, user_id=lead_id)
    await set_rls_context(rls_session, lead_ctx)

    with pytest.raises(NotFoundError):
        await projects_service.remove_member(rls_session, lead_ctx, project_id, uuid.uuid4())
