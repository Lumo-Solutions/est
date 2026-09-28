"""Phase 3 gap-fill (docs/ui-qa-brief.md) final tally's flagged systemic
risk, confirmed here: app/services/boq.py's set_tolerance updates an
existing BoqTolerance row (setattr + flush) without refreshing updated_at
afterward, on the same root cause as taxonomy.py's update_node/move_node
(migration-free this time -- boq_tolerances' RLS already covers UPDATE,
this is purely the ORM-attribute-expiry issue, not a missing RLS policy).
BoqToleranceOut.model_validate(row) reading the expired updated_at crashes
with MissingGreenlet under the async driver. Only the UPDATE branch
(setting a tolerance that already exists) is affected -- the CREATE branch
(session.add on a brand new row) gets its server defaults populated via
flush()'s own INSERT...RETURNING, which UPDATE does not do automatically
for onupdate-computed columns."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.core.context import RequestContext
from app.db.rls import set_rls_context
from app.schemas.boq import BoqToleranceOut
from app.services import boq as boq_service

pytestmark = pytest.mark.asyncio

TENANT = uuid.UUID("8f14e45f-ceea-4e97-8d0c-3d3b3f3c1a00")


def _ctx() -> RequestContext:
    # procurement_head, not lead_estimator: assert_can_see_project
    # (app/services/projects.py's _PROJECT_VISIBLE_WITHOUT_MEMBERSHIP_ROLES)
    # only exempts managing_director/bd_director/procurement_head from
    # needing an explicit project_members row -- lead_estimator does need
    # one, which this test doesn't seed (not what it's testing).
    user_id = uuid.uuid4()
    return RequestContext(tenant_id=TENANT, user_id=user_id, sub=str(user_id), roles=frozenset({"procurement_head"}))


async def _seed_project(session) -> str:
    system_ctx = RequestContext(tenant_id=TENANT, user_id=uuid.uuid4(), sub="sys", roles=frozenset(), is_system=True)
    await set_rls_context(session, system_ctx)
    return str(
        (
            await session.execute(
                text("INSERT INTO projects (tenant_id, code, name) VALUES (:t, :c, 'Tolerance test') RETURNING id"),
                {"t": str(TENANT), "c": f"TOL-{uuid.uuid4().hex[:8]}"},
            )
        ).scalar_one()
    )


async def test_updating_an_existing_tolerance_serializes_without_a_missing_greenlet_crash(rls_session):
    ctx = _ctx()
    await set_rls_context(rls_session, ctx)
    project_id = await _seed_project(rls_session)

    # First call creates the row (session.add path -- always safe, no bug
    # possible there). Second call updates the SAME row (the setattr path
    # that crashed before the fix).
    created = await boq_service.set_tolerance(rls_session, ctx, uuid.UUID(project_id), None, 5.0)
    BoqToleranceOut.model_validate(created)

    updated = await boq_service.set_tolerance(rls_session, ctx, uuid.UUID(project_id), None, 7.5)

    out = BoqToleranceOut.model_validate(updated)
    assert out.tolerance_pct == 7.5
    assert out.updated_at is not None
    assert updated.id == created.id  # same row, updated in place, not a duplicate
