"""GET /projects pagination -- app/services/projects.py::list_projects_page.

Design pin-down (see app/api/v1/routes/projects.py for the full rationale):
called with NEITHER `limit` nor `offset`, the route must return the exact
same bare, unbounded `list[ProjectOut]` JSON array it always has --
LayerTradeMappingAdmin.tsx and TolerancesAdmin.tsx's project-picker
dropdowns rely on that (via useProjects(), no args) to populate a <select>
with every project, and neither file can be touched to work around a
regression here. Passing `limit`/`offset` (ProjectsListPage's
useProjectsPage()) switches to a `Page` envelope
({items, total, limit, offset}), mirroring GET /vendors and GET /cost-items
(app/services/{vendors,costlib}.py) -- the only pagination convention
already in use in this codebase.

These tests exercise the service layer directly (list_projects /
list_projects_page), matching this directory's existing style for
project-scoped reads -- see test_project_members_list.py and
test_costlib_list.py -- rather than going through FastAPI's TestClient
(that's tests/api/test_projects_api.py's job, and its `authed_client`
fixture isn't available outside tests/api)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import RequestContext
from app.db.rls import set_rls_context
from app.services import projects as projects_service

pytestmark = pytest.mark.asyncio


def _ctx(roles: frozenset[str], *, tenant_id: uuid.UUID, is_system: bool = False, user_id: uuid.UUID | None = None) -> RequestContext:
    user_id = user_id or uuid.uuid4()
    return RequestContext(tenant_id=tenant_id, user_id=user_id, sub=str(user_id), roles=roles, is_system=is_system)


async def _seed_tenant(session: AsyncSession) -> uuid.UUID:
    tenant_id = uuid.uuid4()
    await session.execute(
        text("INSERT INTO tenants (id, slug, name) VALUES (:id, :slug, :name)"),
        {"id": str(tenant_id), "slug": f"pg-{uuid.uuid4().hex[:8]}", "name": "Pagination Test"},
    )
    await set_rls_context(session, _ctx(frozenset(), tenant_id=tenant_id, is_system=True))
    return tenant_id


async def _seed_projects(session: AsyncSession, tenant_id: uuid.UUID, count: int) -> list[uuid.UUID]:
    """Explicit, strictly increasing created_at per row. Rows inserted
    within the same test's transaction would otherwise all get the exact
    same server_default `now()` (Postgres's now() is the transaction start
    time, not the statement time -- app/db/base.py::TimestampMixin), which
    would make created_at-desc ordering ambiguous across rows and this
    test's page-boundary assertions flaky."""
    base = datetime(2025, 1, 1, tzinfo=UTC)
    ids: list[uuid.UUID] = []
    for i in range(count):
        row_id = (
            await session.execute(
                text(
                    "INSERT INTO projects (tenant_id, code, name, created_at) "
                    "VALUES (:t, :c, :n, :ts) RETURNING id"
                ),
                {
                    "t": str(tenant_id),
                    "c": f"PAGE-{uuid.uuid4().hex[:8]}",
                    "n": f"Project {i}",
                    "ts": base + timedelta(seconds=i),
                },
            )
        ).scalar_one()
        ids.append(row_id)
    return ids  # ids[0] is oldest (inserted first) -> last in created_at-desc order


async def test_no_params_call_still_returns_every_project_unbounded(rls_session: AsyncSession):
    """Pins the backward-compat contract: list_projects() -- what the route
    calls when neither `limit` nor `offset` is given -- must keep returning
    every row as a plain list, not a page."""
    tenant_id = await _seed_tenant(rls_session)
    ids = await _seed_projects(rls_session, tenant_id, 5)
    await set_rls_context(rls_session, _ctx(frozenset({"managing_director"}), tenant_id=tenant_id, is_system=True))

    rows = await projects_service.list_projects(rls_session)

    assert {r.id for r in rows} == set(ids)
    assert len(rows) == 5


async def test_pagination_page_boundaries_and_total_count(rls_session: AsyncSession):
    tenant_id = await _seed_tenant(rls_session)
    ids = await _seed_projects(rls_session, tenant_id, 5)
    await set_rls_context(rls_session, _ctx(frozenset({"managing_director"}), tenant_id=tenant_id, is_system=True))
    newest_to_oldest = list(reversed(ids))  # created_at desc ordering

    page1, total1 = await projects_service.list_projects_page(rls_session, limit=2, offset=0)
    page2, total2 = await projects_service.list_projects_page(rls_session, limit=2, offset=2)
    page3, total3 = await projects_service.list_projects_page(rls_session, limit=2, offset=4)

    assert total1 == 5
    assert total2 == 5
    assert total3 == 5  # total is stable across pages, not just "however many this page has"
    assert [p.id for p in page1] == newest_to_oldest[0:2]
    assert [p.id for p in page2] == newest_to_oldest[2:4]
    assert [p.id for p in page3] == newest_to_oldest[4:5]  # last page, partial (1 of 5)
    # Every project appears exactly once, in stable created_at-desc order,
    # across consecutive pages -- no gaps, no duplicates.
    assert [p.id for p in (page1 + page2 + page3)] == newest_to_oldest


async def test_page_past_the_end_is_empty_but_total_is_still_correct(rls_session: AsyncSession):
    tenant_id = await _seed_tenant(rls_session)
    await _seed_projects(rls_session, tenant_id, 5)
    await set_rls_context(rls_session, _ctx(frozenset({"managing_director"}), tenant_id=tenant_id, is_system=True))

    rows, total = await projects_service.list_projects_page(rls_session, limit=2, offset=10)

    assert rows == []
    assert total == 5


async def test_a_tenant_with_no_projects_returns_an_empty_page(rls_session: AsyncSession):
    tenant_id = await _seed_tenant(rls_session)
    await set_rls_context(rls_session, _ctx(frozenset({"managing_director"}), tenant_id=tenant_id, is_system=True))

    rows, total = await projects_service.list_projects_page(rls_session, limit=20, offset=0)

    assert rows == []
    assert total == 0
