"""Covers the three "Phase 3 fixes" plus 3b(a) many-to-one aggregation,
against a real Postgres (RLS, triggers, FK cascades) rather than just the
pure-math tests in test_boq_reconciliation.py:

1. Variance staleness self-heals on read when a linked measurement is
   deleted, and writes an audit event.
2. Unit-dimension mismatch is rejected at link time with a 422
   (ValidationAppError).
3. Reconciliation tolerance is configurable per project.
3b(a). A BOQ line can aggregate several linked measurements (summed).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.core.context import RequestContext
from app.core.errors import ValidationAppError
from app.db.rls import set_rls_context
from app.schemas.boq import BoqLineItemCreate
from app.services import boq as boq_service

pytestmark = pytest.mark.asyncio

TENANT = uuid.UUID("8f14e45f-ceea-4e97-8d0c-3d3b3f3c1a00")


def _ctx(roles: frozenset[str], is_system: bool = False, user_id: uuid.UUID | None = None) -> RequestContext:
    user_id = user_id or uuid.uuid4()
    return RequestContext(tenant_id=TENANT, user_id=user_id, sub=str(user_id), roles=roles, is_system=is_system)


async def _seed_project(session, member_user_id: uuid.UUID) -> str:
    system_ctx = _ctx(frozenset(), is_system=True)
    await set_rls_context(session, system_ctx)
    project_id = (
        await session.execute(
            text("INSERT INTO projects (tenant_id, code, name) VALUES (:t, :c, 'P') RETURNING id"),
            {"t": str(TENANT), "c": f"BOQ-FIX-{uuid.uuid4().hex[:8]}"},
        )
    ).scalar_one()
    await session.execute(
        text("INSERT INTO project_members (project_id, user_id, tenant_id, project_role) VALUES (:p, :u, :t, 'estimator')"),
        {"p": project_id, "u": str(member_user_id), "t": str(TENANT)},
    )
    return str(project_id)


async def _seed_measurement(session, project_id: str, value: float, unit: str, sha_suffix: str) -> str:
    system_ctx = _ctx(frozenset(), is_system=True)
    await set_rls_context(session, system_ctx)
    drawing_id = (
        await session.execute(
            text(
                "INSERT INTO drawings (tenant_id, project_id, original_filename, kind, bucket, object_key, "
                "size_bytes, sha256, status) VALUES (:t, :p, 'x.dxf', 'dxf', 'b', 'k', 1, :sha, 'uploaded') "
                "RETURNING id"
            ),
            {"t": str(TENANT), "p": project_id, "sha": ("5" * 64 + sha_suffix)[-64:]},
        )
    ).scalar_one()
    sheet_id = (
        await session.execute(
            text("INSERT INTO drawing_sheets (tenant_id, drawing_id, project_id, sheet_index) VALUES (:t, :d, :p, 0) RETURNING id"),
            {"t": str(TENANT), "d": drawing_id, "p": project_id},
        )
    ).scalar_one()
    measurement_id = (
        await session.execute(
            text(
                "INSERT INTO drawing_measurements (tenant_id, drawing_id, sheet_id, project_id, capability, kind, "
                "value, unit, confidence, source_entity_ids) VALUES "
                "(:t, :d, :s, :p, 'alignment', 'alignment_length_m', :v, :u, 1.0, '[]'::jsonb) RETURNING id"
            ),
            {"t": str(TENANT), "d": drawing_id, "s": sheet_id, "p": project_id, "v": value, "u": unit},
        )
    ).scalar_one()
    return str(measurement_id)


# ---------------------------------------------------------------------------
# Fix 1: variance staleness self-heals + audits
# ---------------------------------------------------------------------------


async def test_deleted_measurement_unlinks_and_marks_unmatched_with_audit(rls_session):
    user_id = uuid.uuid4()
    project_id = await _seed_project(rls_session, user_id)
    measurement_id = await _seed_measurement(rls_session, project_id, 10.0, "m", "aaaa")

    ctx = _ctx(frozenset({"lead_estimator"}), user_id=user_id)
    await set_rls_context(rls_session, ctx)
    item = await boq_service.create_line_item(
        rls_session, ctx, uuid.UUID(project_id),
        BoqLineItemCreate(item_no="1.0", description="Pipe run", uom="m", boq_quantity=10.0),
    )
    linked = await boq_service.add_measurement_link(rls_session, ctx, item.id, uuid.UUID(measurement_id))
    assert linked.discrepancy_class == "match"

    # Delete the measurement directly (as system -- simulating whatever
    # future path removes a drawing_measurements row; the FK is
    # ON DELETE CASCADE on boq_line_item_measurements, same as
    # drawing_measurements' own ON DELETE SET NULL did for the old
    # single-link model).
    system_ctx = _ctx(frozenset(), is_system=True)
    await set_rls_context(rls_session, system_ctx)
    await rls_session.execute(text("DELETE FROM drawing_measurements WHERE id = :id"), {"id": measurement_id})

    # Read as the estimator again -- self-heals on read.
    await set_rls_context(rls_session, ctx)
    refreshed = await boq_service.get_line_item(rls_session, ctx, item.id)
    assert refreshed.discrepancy_class == "unmatched"
    assert refreshed.variance is None
    assert refreshed.reconciliation_note == "No linked takeoff measurement"

    audit_rows = (
        await rls_session.execute(
            text(
                "SELECT payload FROM audit_events WHERE entity_id = :id AND action = 'update' "
                "ORDER BY occurred_at DESC LIMIT 1"
            ),
            {"id": str(item.id)},
        )
    ).scalar_one()
    assert audit_rows["auto_reconciled"] is True
    assert audit_rows["discrepancy_class"] == "unmatched"


# ---------------------------------------------------------------------------
# Fix 2: unit-dimension mismatch rejected at link time (422)
# ---------------------------------------------------------------------------


async def test_linking_incompatible_dimension_raises_422(rls_session):
    user_id = uuid.uuid4()
    project_id = await _seed_project(rls_session, user_id)
    # A volume measurement, but the BOQ item is tendered in metres (length).
    measurement_id = await _seed_measurement(rls_session, project_id, 10.0, "m3", "bbbb")

    ctx = _ctx(frozenset({"lead_estimator"}), user_id=user_id)
    await set_rls_context(rls_session, ctx)
    item = await boq_service.create_line_item(
        rls_session, ctx, uuid.UUID(project_id),
        BoqLineItemCreate(item_no="2.0", description="Fence run", uom="m", boq_quantity=50.0),
    )

    with pytest.raises(ValidationAppError, match="not compatible"):
        await boq_service.add_measurement_link(rls_session, ctx, item.id, uuid.UUID(measurement_id))

    # Must not have been linked or reconciled at all.
    unchanged = await boq_service.get_line_item(rls_session, ctx, item.id)
    assert unchanged.discrepancy_class is None
    assert unchanged.reconciled_at is None


# ---------------------------------------------------------------------------
# Fix 3: configurable tolerance per project
# ---------------------------------------------------------------------------


async def test_project_tolerance_override_changes_classification(rls_session):
    user_id = uuid.uuid4()
    project_id = await _seed_project(rls_session, user_id)
    # 10.0 tendered vs 10.6 measured = 6% variance -- VARIANCE under the
    # 2% global default, MATCH once the project's own tolerance is raised
    # to 10%.
    measurement_id = await _seed_measurement(rls_session, project_id, 10.6, "m", "cccc")

    ctx = _ctx(frozenset({"lead_estimator"}), user_id=user_id)
    await set_rls_context(rls_session, ctx)
    item = await boq_service.create_line_item(
        rls_session, ctx, uuid.UUID(project_id),
        BoqLineItemCreate(item_no="3.0", description="Kerb run", uom="m", boq_quantity=10.0),
    )
    linked = await boq_service.add_measurement_link(rls_session, ctx, item.id, uuid.UUID(measurement_id))
    assert linked.discrepancy_class == "variance"

    await boq_service.set_tolerance(rls_session, ctx, uuid.UUID(project_id), None, 10.0)
    reconciled = await boq_service.reconcile_item(rls_session, ctx, item.id)
    assert reconciled.discrepancy_class == "match"
    assert reconciled.variance_pct == pytest.approx(6.0)


# ---------------------------------------------------------------------------
# 3b(a): many-to-one aggregation
# ---------------------------------------------------------------------------


async def test_multiple_linked_measurements_are_summed(rls_session):
    user_id = uuid.uuid4()
    project_id = await _seed_project(rls_session, user_id)
    # A pipe run split across two sheets: 6.0 + 4.2 = 10.2 m, tendered 10.0
    # -> 2% variance -> exactly at the default tolerance boundary -> MATCH.
    m1 = await _seed_measurement(rls_session, project_id, 6.0, "m", "dddd")
    m2 = await _seed_measurement(rls_session, project_id, 4.2, "m", "eeee")

    ctx = _ctx(frozenset({"lead_estimator"}), user_id=user_id)
    await set_rls_context(rls_session, ctx)
    item = await boq_service.create_line_item(
        rls_session, ctx, uuid.UUID(project_id),
        BoqLineItemCreate(item_no="4.0", description="Pipe run across two sheets", uom="m", boq_quantity=10.0),
    )
    await boq_service.add_measurement_link(rls_session, ctx, item.id, uuid.UUID(m1))
    linked = await boq_service.add_measurement_link(rls_session, ctx, item.id, uuid.UUID(m2))

    assert linked.variance == pytest.approx(0.2)
    assert linked.variance_pct == pytest.approx(2.0)
    assert linked.discrepancy_class == "match"

    links = await boq_service.list_measurement_links(rls_session, item.id)
    assert {str(m.id) for m in links} == {m1, m2}


async def test_removing_one_of_several_links_recomputes_the_sum(rls_session):
    user_id = uuid.uuid4()
    project_id = await _seed_project(rls_session, user_id)
    m1 = await _seed_measurement(rls_session, project_id, 6.0, "m", "ffff")
    m2 = await _seed_measurement(rls_session, project_id, 4.2, "m", "0000")

    ctx = _ctx(frozenset({"lead_estimator"}), user_id=user_id)
    await set_rls_context(rls_session, ctx)
    item = await boq_service.create_line_item(
        rls_session, ctx, uuid.UUID(project_id),
        BoqLineItemCreate(item_no="5.0", description="Pipe run", uom="m", boq_quantity=10.0),
    )
    await boq_service.add_measurement_link(rls_session, ctx, item.id, uuid.UUID(m1))
    await boq_service.add_measurement_link(rls_session, ctx, item.id, uuid.UUID(m2))

    # Remove m2 -- only 6.0 m remains linked against a 10.0 m tender ->
    # variance = -4.0, -40% -> VARIANCE.
    after_removal = await boq_service.remove_measurement_link(rls_session, ctx, item.id, uuid.UUID(m2))
    assert after_removal.variance == pytest.approx(-4.0)
    assert after_removal.discrepancy_class == "variance"


# ---------------------------------------------------------------------------
# 3b(b): reverse direction -- unlinked measurements ("possible missed scope")
# ---------------------------------------------------------------------------


async def test_list_unlinked_measurements_excludes_linked_ones(rls_session):
    user_id = uuid.uuid4()
    project_id = await _seed_project(rls_session, user_id)
    linked_measurement = await _seed_measurement(rls_session, project_id, 10.0, "m", "1111")
    unlinked_measurement = await _seed_measurement(rls_session, project_id, 20.0, "m", "2222")

    ctx = _ctx(frozenset({"lead_estimator"}), user_id=user_id)
    await set_rls_context(rls_session, ctx)
    item = await boq_service.create_line_item(
        rls_session, ctx, uuid.UUID(project_id),
        BoqLineItemCreate(item_no="6.0", description="Pipe run", uom="m", boq_quantity=10.0),
    )
    await boq_service.add_measurement_link(rls_session, ctx, item.id, uuid.UUID(linked_measurement))

    unlinked = await boq_service.list_unlinked_measurements(rls_session, uuid.UUID(project_id))
    unlinked_ids = {str(m.id) for m in unlinked}
    assert unlinked_measurement in unlinked_ids
    assert linked_measurement not in unlinked_ids


async def test_list_unlinked_measurements_filters_by_drawing(rls_session):
    user_id = uuid.uuid4()
    project_id = await _seed_project(rls_session, user_id)
    m_drawing_a = await _seed_measurement(rls_session, project_id, 10.0, "m", "3333")
    m_drawing_b = await _seed_measurement(rls_session, project_id, 20.0, "m", "4444")

    system_ctx = _ctx(frozenset(), is_system=True)
    await set_rls_context(rls_session, system_ctx)
    drawing_a_id = (
        await rls_session.execute(
            text("SELECT drawing_id FROM drawing_measurements WHERE id = :id"), {"id": m_drawing_a}
        )
    ).scalar_one()

    unlinked_for_a = await boq_service.list_unlinked_measurements(rls_session, uuid.UUID(project_id), drawing_a_id)
    ids = {str(m.id) for m in unlinked_for_a}
    assert m_drawing_a in ids
    assert m_drawing_b not in ids
