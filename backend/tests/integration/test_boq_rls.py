from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.core.context import RequestContext
from app.core.errors import NotFoundError, ValidationAppError
from app.db.rls import set_rls_context
from app.schemas.boq import BoqLineItemCreate
from app.services import boq as boq_service

pytestmark = pytest.mark.asyncio

TENANT = uuid.UUID("8f14e45f-ceea-4e97-8d0c-3d3b3f3c1a00")


def _ctx(roles: frozenset[str], is_system: bool = False, user_id: uuid.UUID | None = None) -> RequestContext:
    user_id = user_id or uuid.uuid4()
    return RequestContext(tenant_id=TENANT, user_id=user_id, sub=str(user_id), roles=roles, is_system=is_system)


async def _seed_two_projects_with_membership(session, member_user_id: uuid.UUID) -> tuple[str, str]:
    """Seeds two projects as system, with `member_user_id` a member of only
    the first -- so a role like estimator (which needs project_members for
    visibility) can act on project A but not B."""
    system_ctx = _ctx(frozenset(), is_system=True)
    await set_rls_context(session, system_ctx)
    project_a = (
        await session.execute(
            text("INSERT INTO projects (tenant_id, code, name) VALUES (:t, :c, 'A') RETURNING id"),
            {"t": str(TENANT), "c": f"BOQ-A-{uuid.uuid4().hex[:8]}"},
        )
    ).scalar_one()
    project_b = (
        await session.execute(
            text("INSERT INTO projects (tenant_id, code, name) VALUES (:t, :c, 'B') RETURNING id"),
            {"t": str(TENANT), "c": f"BOQ-B-{uuid.uuid4().hex[:8]}"},
        )
    ).scalar_one()
    await session.execute(
        text("INSERT INTO project_members (project_id, user_id, tenant_id, project_role) VALUES (:p, :u, :t, 'estimator')"),
        {"p": project_a, "u": str(member_user_id), "t": str(TENANT)},
    )
    return str(project_a), str(project_b)


async def test_estimator_cannot_create_boq_structure_lead_estimator_can(rls_session):
    # WRITE_ROLES for boq_line_items (migration 0011) is lead_estimator+,
    # deliberately excluding plain "estimator" -- structural tender-BOQ
    # edits are more senior than day-to-day reconciliation.
    user_id = uuid.uuid4()
    project_a, _project_b = await _seed_two_projects_with_membership(rls_session, user_id)

    estimator_ctx = _ctx(frozenset({"estimator"}), user_id=user_id)
    await set_rls_context(rls_session, estimator_ctx)
    with pytest.raises(Exception, match=r"(?i)row-level security"):
        async with rls_session.begin_nested():
            await boq_service.create_line_item(
                rls_session, estimator_ctx, uuid.UUID(project_a),
                BoqLineItemCreate(item_no="1.0", description="Excavation", uom="m3", boq_quantity=100.0),
            )

    lead_ctx = _ctx(frozenset({"lead_estimator"}), user_id=user_id)
    await set_rls_context(rls_session, lead_ctx)
    item = await boq_service.create_line_item(
        rls_session, lead_ctx, uuid.UUID(project_a),
        BoqLineItemCreate(item_no="1.0", description="Excavation", uom="m3", boq_quantity=100.0),
    )
    assert item.item_no == "1.0"
    assert item.path  # trigger populated it (not the "placeholder" literal)
    assert item.path != "placeholder"
    assert item.level == 0


async def test_estimator_can_link_and_reconcile_but_not_create_structure(rls_session):
    # Reconciliation (link/reconcile) uses a looser role set (estimator+,
    # matching the rest of Module B) than structural edits -- create the
    # item as lead_estimator, then link/reconcile it as a plain estimator.
    user_id = uuid.uuid4()
    project_a, _project_b = await _seed_two_projects_with_membership(rls_session, user_id)

    lead_ctx = _ctx(frozenset({"lead_estimator"}), user_id=user_id)
    await set_rls_context(rls_session, lead_ctx)
    item = await boq_service.create_line_item(
        rls_session, lead_ctx, uuid.UUID(project_a),
        BoqLineItemCreate(item_no="2.0", description="Trench excavation", uom="m3", boq_quantity=100.0),
    )

    measurement_id = (
        await rls_session.execute(
            text(
                "INSERT INTO drawings (tenant_id, project_id, original_filename, kind, bucket, object_key, "
                "size_bytes, sha256, status) VALUES (:t, :p, 'x.dxf', 'dxf', 'b', 'k', 1, "
                "'3333333333333333333333333333333333333333333333333333333333333333', 'uploaded') RETURNING id"
            ),
            {"t": str(TENANT), "p": project_a},
        )
    )
    drawing_id = measurement_id.scalar_one()
    sheet_id = (
        await rls_session.execute(
            text("INSERT INTO drawing_sheets (tenant_id, drawing_id, project_id, sheet_index) VALUES (:t, :d, :p, 0) RETURNING id"),
            {"t": str(TENANT), "d": drawing_id, "p": project_a},
        )
    ).scalar_one()
    measurement_row_id = (
        await rls_session.execute(
            text(
                "INSERT INTO drawing_measurements (tenant_id, drawing_id, sheet_id, project_id, capability, kind, "
                "value, unit, confidence, source_entity_ids) VALUES "
                "(:t, :d, :s, :p, 'trench_prismoidal_volume', 'trench_volume_m3', 101.0, 'm3', 0.6, '[]'::jsonb) RETURNING id"
            ),
            {"t": str(TENANT), "d": drawing_id, "s": sheet_id, "p": project_a},
        )
    ).scalar_one()

    estimator_ctx = _ctx(frozenset({"estimator"}), user_id=user_id)
    await set_rls_context(rls_session, estimator_ctx)
    linked = await boq_service.add_measurement_link(rls_session, estimator_ctx, item.id, measurement_row_id)
    # 100 tendered vs 101 measured -> 1% variance, within the 2% default
    # tolerance -> MATCH (see test_boq_reconciliation.py for the pure math).
    assert linked.discrepancy_class == "match"
    assert linked.variance == pytest.approx(1.0)


async def test_cannot_link_measurement_from_a_different_project(rls_session):
    user_id = uuid.uuid4()
    project_a, project_b = await _seed_two_projects_with_membership(rls_session, user_id)

    lead_ctx = _ctx(frozenset({"lead_estimator"}), user_id=user_id)
    await set_rls_context(rls_session, lead_ctx)
    item = await boq_service.create_line_item(
        rls_session, lead_ctx, uuid.UUID(project_a),
        BoqLineItemCreate(item_no="3.0", description="Item in A", uom="m", boq_quantity=10.0),
    )

    # A measurement that belongs to project B, seeded as system (bypasses
    # the project_members check that would otherwise block a plain
    # estimator from touching project B at all) -- proving this rejection
    # is app.services.boq's own project-match check, not just RLS
    # visibility.
    system_ctx = _ctx(frozenset(), is_system=True)
    await set_rls_context(rls_session, system_ctx)
    drawing_id = (
        await rls_session.execute(
            text(
                "INSERT INTO drawings (tenant_id, project_id, original_filename, kind, bucket, object_key, "
                "size_bytes, sha256, status) VALUES (:t, :p, 'y.dxf', 'dxf', 'b', 'k', 1, "
                "'4444444444444444444444444444444444444444444444444444444444444444', 'uploaded') RETURNING id"
            ),
            {"t": str(TENANT), "p": project_b},
        )
    ).scalar_one()
    sheet_id = (
        await rls_session.execute(
            text("INSERT INTO drawing_sheets (tenant_id, drawing_id, project_id, sheet_index) VALUES (:t, :d, :p, 0) RETURNING id"),
            {"t": str(TENANT), "d": drawing_id, "p": project_b},
        )
    ).scalar_one()
    measurement_id = (
        await rls_session.execute(
            text(
                "INSERT INTO drawing_measurements (tenant_id, drawing_id, sheet_id, project_id, capability, kind, "
                "value, unit, confidence, source_entity_ids) VALUES "
                "(:t, :d, :s, :p, 'alignment', 'alignment_length_m', 10.0, 'm', 1.0, '[]'::jsonb) RETURNING id"
            ),
            {"t": str(TENANT), "d": drawing_id, "s": sheet_id, "p": project_b},
        )
    ).scalar_one()

    # bd_director bypasses project_members entirely (app_can_see_project()
    # exempts it), so its SELECT of the project-B measurement is NOT
    # RLS-filtered -- this is the actor that actually exercises
    # app.services.boq's own project-match check, proving it's a real
    # app-level guard and not just an artifact of RLS visibility.
    bd_ctx = _ctx(frozenset({"bd_director"}), user_id=user_id)
    await set_rls_context(rls_session, bd_ctx)
    with pytest.raises(ValidationAppError):
        await boq_service.add_measurement_link(rls_session, bd_ctx, item.id, measurement_id)

    # lead_estimator, by contrast, is not a member of project B, so the
    # RLS-scoped SELECT for the measurement returns zero rows before the
    # app-level check is ever reached -- a clean 404, not a 422. Both
    # actors are blocked, but via different layers; this asserts each
    # layer independently instead of conflating them.
    await set_rls_context(rls_session, lead_ctx)
    with pytest.raises(NotFoundError):
        await boq_service.add_measurement_link(rls_session, lead_ctx, item.id, measurement_id)


async def test_reparenting_under_own_subtree_is_rejected(rls_session):
    # Same class of bug test_taxonomy_ltree.py guards against for
    # trade_nodes, adapted for boq_line_items_path_trg (migration 0011).
    user_id = uuid.uuid4()
    project_a, _project_b = await _seed_two_projects_with_membership(rls_session, user_id)
    lead_ctx = _ctx(frozenset({"lead_estimator"}), user_id=user_id)
    await set_rls_context(rls_session, lead_ctx)

    parent = await boq_service.create_line_item(
        rls_session, lead_ctx, uuid.UUID(project_a),
        BoqLineItemCreate(item_no="4.0", description="Section", uom=None, boq_quantity=None),
    )
    child = await boq_service.create_line_item(
        rls_session, lead_ctx, uuid.UUID(project_a),
        BoqLineItemCreate(parent_id=parent.id, item_no="4.1", description="Sub-item", uom="m", boq_quantity=5.0),
    )
    assert child.path.startswith(parent.path)

    with pytest.raises(Exception, match=r"(?i)cannot reparent"):
        async with rls_session.begin_nested():
            await rls_session.execute(
                text("UPDATE boq_line_items SET parent_id = :child WHERE id = :parent"),
                {"child": str(child.id), "parent": str(parent.id)},
            )
