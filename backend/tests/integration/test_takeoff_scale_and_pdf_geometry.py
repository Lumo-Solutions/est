"""Module B Phase 4a end to end: scale actually applies to a real computed
measurement (a pre-existing gap found while building this -- see
docs/build-log.md's Phase 4a section: scale_ratio was stored but never
consumed by any extractor before this phase), manual two-point calibration
writes history and recomputes, revert restores a prior calibration, and
PDF layer-mapping-rule config CRUD. See docs/module-b-phase4-plan.md §4a.

Role gating for these four endpoints is enforced only at the route's
require_roles(*_UPLOAD_ROLES) dependency (all five tenant roles are
allowed; there is no service-layer _require_role check to exercise here,
unlike e.g. settlement_service.build_settlement_draft) -- same as every
other pre-existing drawings endpoint, none of which has a dedicated API-
level permission test either. Logged as a known gap in docs/build-log.md
rather than fabricated here. What IS exercised below at the service layer
is real (non-system) project membership via the estimator role -- the
lowest role _UPLOAD_ROLES allows -- following the established
_MEMBER_USER_ID convention (estimator/lead_estimator are not covered by
app_can_see_project()'s senior-role RLS bypass)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import RequestContext
from app.core.errors import ConflictError
from app.db.rls import set_rls_context
from app.models.takeoff import Drawing, DrawingEntity, DrawingSheet
from app.schemas.drawings import PdfLayerMappingRuleIn
from app.services import takeoff as takeoff_service

pytestmark = pytest.mark.asyncio

_ESTIMATOR = frozenset({"estimator"})

# lead_estimator/estimator are NOT covered by app_can_see_project()'s
# senior-role RLS bypass -- they need an actual project_members row. Same
# fixed id convention as tests/integration/test_bid_settlement.py.
_MEMBER_USER_ID = uuid.UUID("00000000-0000-0000-0000-0000000000b4")


def _ctx(roles: frozenset[str], *, tenant_id: uuid.UUID, is_system: bool = False, user_id: uuid.UUID | None = None) -> RequestContext:
    user_id = user_id or uuid.uuid4()
    return RequestContext(tenant_id=tenant_id, user_id=user_id, sub=str(user_id), roles=roles, is_system=is_system)


async def _seed_project(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
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
            {"t": str(tenant_id), "c": f"B4A-{uuid.uuid4().hex[:8]}"},
        )
    ).scalar_one()
    await session.execute(
        text("INSERT INTO project_members (project_id, user_id, tenant_id) VALUES (:p, :u, :t)"),
        {"p": str(project_id), "u": str(_MEMBER_USER_ID), "t": str(tenant_id)},
    )
    return tenant_id, project_id


async def _seed_pdf_sheet_with_alignment_line(session: AsyncSession, tenant_id: uuid.UUID, project_id: uuid.UUID):
    """A PDF-sourced sheet (units="pt") with one persisted "line" geometry
    entity on a layer AlignmentExtractor's default config matches
    ("-CL" -- same layer-naming convention as tests/unit/test_dxf_geometry.py's
    own fixture), 100 points long."""
    drawing = Drawing(
        tenant_id=tenant_id, project_id=project_id, original_filename="tender.pdf", kind="vector_pdf",
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
    session.add(
        DrawingEntity(
            tenant_id=tenant_id, sheet_id=sheet.id, project_id=project_id, source="pdf", entity_type="line",
            layer="C-ROAD-CL", handle="line-0",
            geometry={"vertices": [[0.0, 0.0], [100.0, 0.0]], "closed": False, "bulges": None},
        )
    )
    await session.flush()
    return drawing, sheet


def _force_persist_geometry(monkeypatch) -> None:
    from types import SimpleNamespace

    monkeypatch.setattr(takeoff_service, "get_settings", lambda: SimpleNamespace(takeoff_persist_geometry=True))


# --------------------------------------------------------------------------
# scale actually applies to a computed measurement (the bug this phase found)
# --------------------------------------------------------------------------


async def test_recompute_with_no_scale_set_uses_raw_point_to_metre_conversion_only(rls_session, monkeypatch):
    _force_persist_geometry(monkeypatch)
    tenant_id, project_id = await _seed_project(rls_session)
    sys_ctx = _ctx(frozenset(), tenant_id=tenant_id, is_system=True)
    await set_rls_context(rls_session, sys_ctx)
    _drawing, sheet = await _seed_pdf_sheet_with_alignment_line(rls_session, tenant_id, project_id)
    assert sheet.scale_ratio is None

    await takeoff_service.recompute_sheet_measurements(rls_session, sheet)
    measurements = await takeoff_service.list_measurements(rls_session, sheet.drawing_id, sheet.id)
    alignment = next(m for m in measurements if m.kind == "alignment_length_m")
    pt_to_m = 0.0254 / 72.0
    # drawing_measurements.value is Numeric(18, 6) -- allow for that
    # column's own rounding, not just float error.
    assert float(alignment.value) == pytest.approx(100.0 * pt_to_m, abs=1e-6)


async def test_manual_calibration_scales_measurement_correctly(rls_session, monkeypatch):
    """The exact bug found while building this phase: without converting
    the raw point-distance to a physical length before dividing,
    known_length_m would be off by the points-to-metres factor (~2,835x).
    See services/takeoff.py::set_manual_scale's docstring."""
    _force_persist_geometry(monkeypatch)
    tenant_id, project_id = await _seed_project(rls_session)
    sys_ctx = _ctx(frozenset(), tenant_id=tenant_id, is_system=True)
    await set_rls_context(rls_session, sys_ctx)
    drawing, sheet = await _seed_pdf_sheet_with_alignment_line(rls_session, tenant_id, project_id)

    estimator_ctx = _ctx(_ESTIMATOR, tenant_id=tenant_id, user_id=_MEMBER_USER_ID)
    await set_rls_context(rls_session, estimator_ctx)
    # Calibrate: the 100pt line (the same one the alignment entity uses)
    # is stated to actually be 5 real metres long.
    updated = await takeoff_service.set_manual_scale(
        rls_session, estimator_ctx, drawing.id, sheet.sheet_index, p1=(0.0, 0.0), p2=(100.0, 0.0), known_length_m=5.0
    )
    assert updated.scale_source == "manual_two_point"

    measurements = await takeoff_service.list_measurements(rls_session, drawing.id, sheet.id)
    alignment = next(m for m in measurements if m.kind == "alignment_length_m")
    assert float(alignment.value) == pytest.approx(5.0, rel=1e-6)  # the calibrated line reads back as exactly 5m


async def test_calibration_history_recorded_and_revert_restores_prior_ratio(rls_session, monkeypatch):
    """Also a regression test for a real bug found while dev-verifying this
    phase against the live stack (see migration 0022 and docs/build-log.md):
    drawing_measurements' DELETE policy (migration 0010) never covered
    "estimator", on the since-invalidated assumption that
    recompute_sheet_measurements only ever ran as a system actor. Once
    set_manual_scale/revert_scale_calibration made it reachable as a real
    request-path actor, recompute's DELETE silently matched zero rows and
    every recalibration just ADDED another alignment_length_m row instead
    of replacing the old one -- caught here by seeding an initial
    system-actor measurement first (as the real extract_geometry_
    measurements Celery task would leave behind before any calibration
    ever happens) and asserting exactly one survives two estimator-driven
    recomputes."""
    _force_persist_geometry(monkeypatch)
    tenant_id, project_id = await _seed_project(rls_session)
    sys_ctx = _ctx(frozenset(), tenant_id=tenant_id, is_system=True)
    await set_rls_context(rls_session, sys_ctx)
    drawing, sheet = await _seed_pdf_sheet_with_alignment_line(rls_session, tenant_id, project_id)

    # Simulate an earlier auto-detected calibration + geometry pass (as
    # _extract_sheet_body / _extract_geometry_measurements_body, both
    # system-actor Celery tasks, would leave behind).
    await takeoff_service.record_scale_calibration(
        rls_session, sheet, ratio=0.01, source="title_block_text", confidence=0.95, set_by=None,
    )
    await takeoff_service.recompute_sheet_measurements(rls_session, sheet)

    estimator_ctx = _ctx(_ESTIMATOR, tenant_id=tenant_id, user_id=_MEMBER_USER_ID)
    await set_rls_context(rls_session, estimator_ctx)
    await takeoff_service.set_manual_scale(
        rls_session, estimator_ctx, drawing.id, sheet.sheet_index, p1=(0.0, 0.0), p2=(100.0, 0.0), known_length_m=5.0
    )

    history = await takeoff_service.list_scale_calibrations(rls_session, drawing.id, sheet.sheet_index)
    assert [h.source for h in history] == ["manual_two_point", "title_block_text"]  # newest first
    original = next(h for h in history if h.source == "title_block_text")

    reverted = await takeoff_service.revert_scale_calibration(
        rls_session, estimator_ctx, drawing.id, sheet.sheet_index, original.id
    )
    assert float(reverted.scale_ratio) == pytest.approx(0.01)
    assert reverted.scale_source == "title_block_text"

    history_after = await takeoff_service.list_scale_calibrations(rls_session, drawing.id, sheet.sheet_index)
    assert len(history_after) == 3  # revert adds a new row, never rewrites history
    assert history_after[0].note is not None and "reverted to calibration" in history_after[0].note

    final_measurements = await takeoff_service.list_measurements(rls_session, drawing.id, sheet.id)
    alignment_rows = [m for m in final_measurements if m.kind == "alignment_length_m"]
    assert len(alignment_rows) == 1, "recompute must replace the prior measurement, never accumulate duplicates"
    # drawing_measurements.value is Numeric(18, 6) -- allow for that
    # column's own rounding at this magnitude, same as the earlier test.
    assert float(alignment_rows[0].value) == pytest.approx(0.01 * 100.0 * (0.0254 / 72.0), abs=1e-6)


async def test_set_manual_scale_rejects_coincident_points(rls_session, monkeypatch):
    _force_persist_geometry(monkeypatch)
    tenant_id, project_id = await _seed_project(rls_session)
    sys_ctx = _ctx(frozenset(), tenant_id=tenant_id, is_system=True)
    await set_rls_context(rls_session, sys_ctx)
    drawing, sheet = await _seed_pdf_sheet_with_alignment_line(rls_session, tenant_id, project_id)

    estimator_ctx = _ctx(_ESTIMATOR, tenant_id=tenant_id, user_id=_MEMBER_USER_ID)
    await set_rls_context(rls_session, estimator_ctx)
    with pytest.raises(ConflictError):
        await takeoff_service.set_manual_scale(
            rls_session, estimator_ctx, drawing.id, sheet.sheet_index, p1=(1.0, 1.0), p2=(1.0, 1.0), known_length_m=5.0
        )


# --------------------------------------------------------------------------
# PDF layer mapping rules
# --------------------------------------------------------------------------


async def test_replace_and_list_pdf_layer_mapping_rules(rls_session):
    tenant_id, project_id = await _seed_project(rls_session)
    estimator_ctx = _ctx(_ESTIMATOR, tenant_id=tenant_id, user_id=_MEMBER_USER_ID)
    await set_rls_context(rls_session, estimator_ctx)

    rules_in = [
        PdfLayerMappingRuleIn(target_layer="ALIGN-CL", stroke_color="#ff0000", dash_pattern="dashed", priority=1),
        PdfLayerMappingRuleIn(target_layer="TRENCH-XSEC", stroke_color="#000000", priority=2),
    ]
    created = await takeoff_service.replace_pdf_layer_mapping_rules(
        rls_session, estimator_ctx, project_id, [r.model_dump() for r in rules_in]
    )
    assert {r.target_layer for r in created} == {"ALIGN-CL", "TRENCH-XSEC"}

    listed = await takeoff_service.list_pdf_layer_mapping_rules(rls_session, project_id)
    assert [r.target_layer for r in listed] == ["ALIGN-CL", "TRENCH-XSEC"]  # ordered by priority

    # Replacing again drops the old set entirely (whole-set replace).
    replaced = await takeoff_service.replace_pdf_layer_mapping_rules(
        rls_session, estimator_ctx, project_id, [{"target_layer": "ONLY-ONE", "priority": 0}]
    )
    assert len(replaced) == 1
    listed_again = await takeoff_service.list_pdf_layer_mapping_rules(rls_session, project_id)
    assert [r.target_layer for r in listed_again] == ["ONLY-ONE"]
