"""Phase 3 gap-fill (docs/ui-qa-brief.md): GET /projects/{id}/members --
app/services/projects.py::list_members. An add-member form with no way to
see who's already on a project isn't a usable screen, so this was added
alongside the add-member UI."""

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


def _ctx(roles: frozenset[str], *, tenant_id: uuid.UUID, is_system: bool = False, user_id: uuid.UUID | None = None) -> RequestContext:
    user_id = user_id or uuid.uuid4()
    return RequestContext(tenant_id=tenant_id, user_id=user_id, sub=str(user_id), roles=roles, is_system=is_system)


async def _seed_tenant_and_project(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    tenant_id = uuid.uuid4()
    await session.execute(
        text("INSERT INTO tenants (id, slug, name) VALUES (:id, :slug, :name)"),
        {"id": str(tenant_id), "slug": f"pm-{uuid.uuid4().hex[:8]}", "name": "PM Test"},
    )
    await set_rls_context(session, _ctx(frozenset(), tenant_id=tenant_id, is_system=True))
    project_id = (
        await session.execute(
            text("INSERT INTO projects (tenant_id, code, name) VALUES (:t, :c, 'A') RETURNING id"),
            {"t": str(tenant_id), "c": f"PM-{uuid.uuid4().hex[:8]}"},
        )
    ).scalar_one()
    return tenant_id, project_id


async def test_lists_every_member_of_the_project(rls_session: AsyncSession):
    tenant_id, project_id = await _seed_tenant_and_project(rls_session)
    user_a, user_b = uuid.uuid4(), uuid.uuid4()
    await rls_session.execute(
        text(
            "INSERT INTO project_members (project_id, user_id, tenant_id, project_role) "
            "VALUES (:p, :u, :t, :r)"
        ),
        [
            {"p": str(project_id), "u": str(user_a), "t": str(tenant_id), "r": "lead"},
            {"p": str(project_id), "u": str(user_b), "t": str(tenant_id), "r": None},
        ],
    )

    md_ctx = _ctx(frozenset({"managing_director"}), tenant_id=tenant_id, is_system=True)
    await set_rls_context(rls_session, md_ctx)

    members = await projects_service.list_members(rls_session, project_id)

    assert {(m.user_id, m.project_role) for m in members} == {(user_a, "lead"), (user_b, None)}


async def test_a_project_with_no_members_returns_empty_list(rls_session: AsyncSession):
    tenant_id, project_id = await _seed_tenant_and_project(rls_session)
    md_ctx = _ctx(frozenset({"managing_director"}), tenant_id=tenant_id, is_system=True)
    await set_rls_context(rls_session, md_ctx)

    assert await projects_service.list_members(rls_session, project_id) == []


async def test_a_nonexistent_project_id_404s(rls_session: AsyncSession):
    tenant_id, _project_id = await _seed_tenant_and_project(rls_session)
    md_ctx = _ctx(frozenset({"managing_director"}), tenant_id=tenant_id, is_system=True)
    await set_rls_context(rls_session, md_ctx)

    with pytest.raises(NotFoundError):
        await projects_service.list_members(rls_session, uuid.uuid4())
