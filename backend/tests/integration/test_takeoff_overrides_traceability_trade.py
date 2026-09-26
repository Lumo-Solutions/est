"""Module B Phase 4b: non-destructive measurement overrides (effective_value
flows through BOQ reconciliation, revert restores it, a recompute clears a
stale override rather than silently keeping it), trade classification of
measurements (resolved from source-entity layers against
drawing_layer_trade_mappings, filterable on measurements:unlinked), and the
split-pane traceability endpoint (bbox-intersection query). See
docs/module-b-phase4-plan.md §4b.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app.core.context import RequestContext
from app.core.errors import ConflictError, NotFoundError, ValidationAppError
from app.db.rls import set_rls_context
from app.models.takeoff import Drawing, DrawingEntity, DrawingMeasurement, DrawingSheet
from app.models.taxonomy import TradeNode
from app.schemas.boq import BoqLineItemCreate
from app.services import boq as boq_service
from app.services import takeoff as takeoff_service

pytestmark = pytest.mark.asyncio

_ESTIMATOR = frozenset({"estimator"})
_LEAD = frozenset({"lead_estimator"})

# Same fixed-membership-id convention as the other Module B/D integration
# test files (estimator/lead_estimator aren't covered by
# app_can_see_project()'s senior-role RLS bypass).
_MEMBER_USER_ID = uuid.UUID("00000000-0000-0000-0000-0000000000b5")


def _ctx(roles: frozenset[str], *, tenant_id: uuid.UUID, is_system: bool = False, user_id: uuid.UUID | None = None) -> RequestContext:
    user_id = user_id or uuid.uuid4()
    return RequestContext(tenant_id=tenant_id, user_id=user_id, sub=str(user_id), roles=roles, is_system=is_system)


async def _seed_project(session):
    tenant_id = uuid.uuid4()
    await session.execute(
        text("INSERT INTO tenants (id, slug, name) VALUES (:id, :slug, :name)"),
        {"id": str(tenant_id), "slug": f"acme-{uuid.uuid4().hex[:8]}", "name": "Acme"},
    )
    sys_ctx = _ctx(frozenset(), tenant_id=tenant_id, is_system=True)
    await set_rls_context(session, sys_ctx)
    project_id = (
        await session.execute(
            text("INSERT INTO projects (tenant_id, code, name) VALUES (:t, :c, 'A') RETURNING id"),
            {"t": str(tenant_id), "c": f"B4B-{uuid.uuid4().hex[:8]}"},
        )
    ).scalar_one()
    await session.execute(
        text("INSERT INTO project_members (project_id, user_id, tenant_id) VALUES (:p, :u, :t)"),
        {"p": str(project_id), "u": str(_MEMBER_USER_ID), "t": str(tenant_id)},
    )
    return tenant_id, project_id


async def _seed_bare_measurement(session, tenant_id, project_id, *, value: float, unit: str = "m") -> DrawingMeasurement:
    """A DrawingMeasurement with no real geometry behind it -- fine for
    override/reconciliation tests, which don't need a real extractor run."""
    drawing = Drawing(
        tenant_id=tenant_id, project_id=project_id, original_filename="x.pdf", kind="vector_pdf",
        bucket="installtec-drawings", object_key="x", size_bytes=1, sha256="0" * 64,
    )
    session.add(drawing)
    await session.flush()
    sheet = DrawingSheet(
        tenant_id=tenant_id, drawing_id=drawing.id, project_id=project_id, sheet_index=0, source_name="page-1",
        units="pt", is_raster=False,
    )
    session.add(sheet)
    await session.flush()
    measurement = DrawingMeasurement(
        tenant_id=tenant_id, drawing_id=drawing.id, sheet_id=sheet.id, project_id=project_id,
        capability="alignment", kind="alignment_length_m", value=Decimal(str(value)), unit=unit,
        confidence=Decimal("1.0"), source_entity_ids=[],
    )
    session.add(measurement)
    await session.flush()
    return measurement


async def _seed_pdf_sheet_with_alignment_line(session, tenant_id, project_id, *, layer: str = "C-ROAD-CL"):
    drawing = Drawing(
        tenant_id=tenant_id, project_id=project_id, original_filename="tender.pdf", kind="vector_pdf",
        bucket="installtec-drawings", object_key="x", size_bytes=1, sha256="1" * 64,
    )
    session.add(drawing)
    await session.flush()
    sheet = DrawingSheet(
        tenant_id=tenant_id, drawing_id=drawing.id, project_id=project_id, sheet_index=0, source_name="page-1",
        units="pt", is_raster=False,
    )
    session.add(sheet)
    await session.flush()
    session.add(
        DrawingEntity(
            tenant_id=tenant_id, sheet_id=sheet.id, project_id=project_id, source="pdf", entity_type="line",
            layer=layer, handle="line-0", bbox_min_x=0.0, bbox_min_y=0.0, bbox_max_x=100.0, bbox_max_y=0.0,
            geometry={"vertices": [[0.0, 0.0], [100.0, 0.0]], "closed": False, "bulges": None},
        )
    )
    await session.flush()
    return drawing, sheet


def _force_persist_geometry(monkeypatch) -> None:
    from types import SimpleNamespace

    monkeypatch.setattr(takeoff_service, "get_settings", lambda: SimpleNamespace(takeoff_persist_geometry=True))


# --------------------------------------------------------------------------
# overrides: effective_value, reconciliation ripple, revert, recompute wipe
# --------------------------------------------------------------------------


async def test_override_changes_reconciliation_sum_and_revert_restores_it(rls_session):
    tenant_id, project_id = await _seed_project(rls_session)
    sys_ctx = _ctx(frozenset(), tenant_id=tenant_id, is_system=True)
    await set_rls_context(rls_session, sys_ctx)
    measurement = await _seed_bare_measurement(rls_session, tenant_id, project_id, value=10.0)

    # boq_line_items' own WRITE_ROLES is lead_estimator+ (structural edits);
    # linking/reconciling/overriding is the looser estimator+ operational
    # tier -- create the item as lead_estimator, do everything else as
    # estimator (the lowest role that can override at all).
    lead_ctx = _ctx(_LEAD, tenant_id=tenant_id, user_id=_MEMBER_USER_ID)
    await set_rls_context(rls_session, lead_ctx)
    item = await boq_service.create_line_item(
        rls_session, lead_ctx, project_id,
        BoqLineItemCreate(item_no="1.0", description="Road", uom="m", boq_quantity=10.0),
    )

    estimator_ctx = _ctx(_ESTIMATOR, tenant_id=tenant_id, user_id=_MEMBER_USER_ID)
    await set_rls_context(rls_session, estimator_ctx)
    item = await boq_service.add_measurement_link(rls_session, estimator_ctx, item.id, measurement.id)
    assert item.discrepancy_class == "match"
    assert float(item.variance) == pytest.approx(0.0)

    await takeoff_service.override_measurement(
        rls_session, estimator_ctx, measurement.id, value=15.0, unit="m", note="auto-detected scale was wrong"
    )
    item = await boq_service.get_line_item(rls_session, estimator_ctx, item.id)
    assert item.discrepancy_class == "variance"
    assert float(item.variance) == pytest.approx(5.0)

    reverted = await takeoff_service.revert_measurement_override(rls_session, estimator_ctx, measurement.id)
    assert reverted.override is None
    assert float(reverted.effective_value) == pytest.approx(10.0)

    item = await boq_service.get_line_item(rls_session, estimator_ctx, item.id)
    assert item.discrepancy_class == "match"
    assert float(item.variance) == pytest.approx(0.0)


async def test_override_requires_a_note(rls_session):
    tenant_id, project_id = await _seed_project(rls_session)
    sys_ctx = _ctx(frozenset(), tenant_id=tenant_id, is_system=True)
    await set_rls_context(rls_session, sys_ctx)
    measurement = await _seed_bare_measurement(rls_session, tenant_id, project_id, value=10.0)

    # Schema-level requirement (MeasurementOverrideIn.note: str, no default)
    # is exercised at the API layer; the service itself also refuses an
    # empty note, since it's meant to answer "why", not just "what".
    estimator_ctx = _ctx(_ESTIMATOR, tenant_id=tenant_id, user_id=_MEMBER_USER_ID)
    await set_rls_context(rls_session, estimator_ctx)
    with pytest.raises(ValidationAppError):
        await takeoff_service.override_measurement(rls_session, estimator_ctx, measurement.id, value=15.0, unit="m", note="")


async def test_setting_a_new_override_supersedes_the_active_one(rls_session):
    tenant_id, project_id = await _seed_project(rls_session)
    sys_ctx = _ctx(frozenset(), tenant_id=tenant_id, is_system=True)
    await set_rls_context(rls_session, sys_ctx)
    measurement = await _seed_bare_measurement(rls_session, tenant_id, project_id, value=10.0)

    estimator_ctx = _ctx(_ESTIMATOR, tenant_id=tenant_id, user_id=_MEMBER_USER_ID)
    await set_rls_context(rls_session, estimator_ctx)
    first = await takeoff_service.override_measurement(rls_session, estimator_ctx, measurement.id, value=15.0, unit="m", note="first correction")
    second = await takeoff_service.override_measurement(rls_session, estimator_ctx, measurement.id, value=20.0, unit="m", note="second, better, correction")

    await rls_session.refresh(first)
    assert first.reverted_at is not None  # superseded, not left dangling active
    assert second.reverted_at is None

    fresh = await takeoff_service.get_measurement(rls_session, measurement.id)
    assert float(fresh.effective_value) == pytest.approx(20.0)


async def test_revert_with_no_active_override_raises_conflict(rls_session):
    tenant_id, project_id = await _seed_project(rls_session)
    sys_ctx = _ctx(frozenset(), tenant_id=tenant_id, is_system=True)
    await set_rls_context(rls_session, sys_ctx)
    measurement = await _seed_bare_measurement(rls_session, tenant_id, project_id, value=10.0)

    estimator_ctx = _ctx(_ESTIMATOR, tenant_id=tenant_id, user_id=_MEMBER_USER_ID)
    await set_rls_context(rls_session, estimator_ctx)
    with pytest.raises(ConflictError):
        await takeoff_service.revert_measurement_override(rls_session, estimator_ctx, measurement.id)


async def test_recompute_clears_a_stale_override_rather_than_keeping_it(rls_session, monkeypatch):
    """A deliberate design choice (see services/takeoff.py::
    recompute_sheet_measurements' docstring), not an accident: the
    measurement row an override pointed at is deleted and recreated on
    recompute (ON DELETE CASCADE), so the override goes with it -- a
    stale manual number silently surviving a scale recalibration would be
    worse than requiring the estimator to re-review and re-override."""
    _force_persist_geometry(monkeypatch)
    tenant_id, project_id = await _seed_project(rls_session)
    sys_ctx = _ctx(frozenset(), tenant_id=tenant_id, is_system=True)
    await set_rls_context(rls_session, sys_ctx)
    drawing, sheet = await _seed_pdf_sheet_with_alignment_line(rls_session, tenant_id, project_id)
    await takeoff_service.recompute_sheet_measurements(rls_session, sheet)
    measurements = await takeoff_service.list_measurements(rls_session, drawing.id, sheet.id)
    measurement = next(m for m in measurements if m.kind == "alignment_length_m")

    estimator_ctx = _ctx(_ESTIMATOR, tenant_id=tenant_id, user_id=_MEMBER_USER_ID)
    await set_rls_context(rls_session, estimator_ctx)
    await takeoff_service.override_measurement(rls_session, estimator_ctx, measurement.id, value=99.0, unit="m", note="manual correction")

    await set_rls_context(rls_session, sys_ctx)
    await takeoff_service.recompute_sheet_measurements(rls_session, sheet)

    with pytest.raises(NotFoundError):
        await takeoff_service.get_measurement(rls_session, measurement.id)  # the old row is gone, not just its override
    survivors = await takeoff_service.list_measurements(rls_session, drawing.id, sheet.id)
    new_measurement = next(m for m in survivors if m.kind == "alignment_length_m")
    assert new_measurement.override is None


# --------------------------------------------------------------------------
# trade classification
# --------------------------------------------------------------------------


async def test_trade_classification_resolved_and_filters_unlinked_measurements(rls_session, monkeypatch):
    _force_persist_geometry(monkeypatch)
    tenant_id, project_id = await _seed_project(rls_session)
    sys_ctx = _ctx(frozenset(), tenant_id=tenant_id, is_system=True)
    await set_rls_context(rls_session, sys_ctx)
    roadworks = TradeNode(tenant_id=tenant_id, parent_id=None, code="ROAD", name="Roadworks", path="road")
    drainage = TradeNode(tenant_id=tenant_id, parent_id=None, code="DRAIN", name="Drainage", path="drain")
    rls_session.add_all([roadworks, drainage])
    await rls_session.flush()

    lead_ctx = _ctx(_LEAD, tenant_id=tenant_id, user_id=_MEMBER_USER_ID)
    await set_rls_context(rls_session, lead_ctx)
    await takeoff_service.replace_layer_trade_mappings(
        rls_session, lead_ctx, project_id, [{"layer_pattern": "ROAD-CL", "trade_node_id": roadworks.id}]
    )

    await set_rls_context(rls_session, sys_ctx)
    drawing, sheet = await _seed_pdf_sheet_with_alignment_line(rls_session, tenant_id, project_id, layer="C-ROAD-CL")
    await takeoff_service.recompute_sheet_measurements(rls_session, sheet)
    measurements = await takeoff_service.list_measurements(rls_session, drawing.id, sheet.id)
    measurement = next(m for m in measurements if m.kind == "alignment_length_m")
    assert measurement.trade_node_id == roadworks.id

    unlinked_roadworks = await boq_service.list_unlinked_measurements(rls_session, project_id, trade_node_id=roadworks.id)
    assert measurement.id in {m.id for m in unlinked_roadworks}

    unlinked_drainage = await boq_service.list_unlinked_measurements(rls_session, project_id, trade_node_id=drainage.id)
    assert measurement.id not in {m.id for m in unlinked_drainage}


async def test_replace_drawing_layer_trade_mappings_denies_estimator(rls_session):
    """No service-layer _require_role check here (same as pdf_layer_
    mapping_rules in Phase 4a) -- unlike those rules, drawing_layer_
    trade_mappings' WRITE_ROLES is narrower than _UPLOAD_ROLES
    (lead_estimator+, matching boq_tolerances), so RLS itself genuinely
    denies a plain estimator's INSERT: confirmed as a raw
    sqlalchemy.exc.ProgrammingError (asyncpg's InsufficientPrivilegeError,
    translated), not a clean ForbiddenError -- there's no service check to
    raise one."""
    tenant_id, project_id = await _seed_project(rls_session)
    sys_ctx = _ctx(frozenset(), tenant_id=tenant_id, is_system=True)
    await set_rls_context(rls_session, sys_ctx)
    trade = TradeNode(tenant_id=tenant_id, parent_id=None, code="ROAD", name="Roadworks", path="road")
    rls_session.add(trade)
    await rls_session.flush()

    estimator_ctx = _ctx(_ESTIMATOR, tenant_id=tenant_id, user_id=_MEMBER_USER_ID)
    await set_rls_context(rls_session, estimator_ctx)
    with pytest.raises(ProgrammingError, match="row-level security policy"):
        await takeoff_service.replace_layer_trade_mappings(
            rls_session, estimator_ctx, project_id, [{"layer_pattern": "ROAD-CL", "trade_node_id": trade.id}]
        )


# --------------------------------------------------------------------------
# traceability: bbox-intersection entity query
# --------------------------------------------------------------------------


async def test_list_drawing_entities_in_region_returns_intersecting_only(rls_session):
    tenant_id, project_id = await _seed_project(rls_session)
    sys_ctx = _ctx(frozenset(), tenant_id=tenant_id, is_system=True)
    await set_rls_context(rls_session, sys_ctx)
    _drawing, sheet = await _seed_pdf_sheet_with_alignment_line(rls_session, tenant_id, project_id)

    all_entities = await takeoff_service.list_drawing_entities_in_region(rls_session, sheet.id)
    assert len(all_entities) == 1

    overlapping = await takeoff_service.list_drawing_entities_in_region(rls_session, sheet.id, bbox=(50.0, -10.0, 150.0, 10.0))
    assert len(overlapping) == 1

    disjoint = await takeoff_service.list_drawing_entities_in_region(rls_session, sheet.id, bbox=(200.0, 200.0, 300.0, 300.0))
    assert len(disjoint) == 0
