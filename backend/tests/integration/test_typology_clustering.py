"""Module B Phase 4c: clustered typology recognition end to end against a
real Postgres (RLS, FK cascades) -- detect (DXF block grouping, idempotent
re-run), confirm (splitting a detected batch into groups, setting the
master, recording deltas), reject, and the rollup arithmetic (spatial
BOQ-item scoping via Phase 4b's DrawingMeasurement bbox columns). See
docs/module-b-phase4-plan.md §4c.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app.core.context import RequestContext
from app.core.errors import ConflictError, ValidationAppError
from app.db.rls import set_rls_context
from app.models.takeoff import Drawing, DrawingEntity, DrawingMeasurement, DrawingSheet
from app.schemas.boq import BoqLineItemCreate
from app.services import boq as boq_service
from app.services import typology as typology_service

pytestmark = pytest.mark.asyncio

_ESTIMATOR = frozenset({"estimator"})
_LEAD = frozenset({"lead_estimator"})

_MEMBER_USER_ID = uuid.UUID("00000000-0000-0000-0000-0000000000b6")

_SIG = {"__sig_bbox_aspect_ratio": "2.0", "__sig_entity_count": "1", "__sig_total_edge_length": "30.0"}


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
            {"t": str(tenant_id), "c": f"B4C-{uuid.uuid4().hex[:8]}"},
        )
    ).scalar_one()
    await session.execute(
        text("INSERT INTO project_members (project_id, user_id, tenant_id) VALUES (:p, :u, :t)"),
        {"p": str(project_id), "u": str(_MEMBER_USER_ID), "t": str(tenant_id)},
    )
    return tenant_id, project_id


async def _seed_dxf_sheet_with_inserts(session, tenant_id, project_id, *, block_name="VILLA_A", count=3):
    drawing = Drawing(
        tenant_id=tenant_id, project_id=project_id, original_filename="site.dxf", kind="dxf",
        bucket="installtec-drawings", object_key="x", size_bytes=1, sha256=uuid.uuid4().hex.ljust(64, "0"),
    )
    session.add(drawing)
    await session.flush()
    sheet = DrawingSheet(
        tenant_id=tenant_id, drawing_id=drawing.id, project_id=project_id, sheet_index=0, source_name="Model",
        units="m", is_raster=False,
    )
    session.add(sheet)
    await session.flush()
    for i in range(count):
        session.add(
            DrawingEntity(
                tenant_id=tenant_id, sheet_id=sheet.id, project_id=project_id, source="dxf", entity_type="insert_node",
                layer="0", handle=f"h{i}", block_name=block_name, attributes=dict(_SIG),
                bbox_min_x=float(i * 100), bbox_min_y=0.0, bbox_max_x=float(i * 100 + 10), bbox_max_y=5.0,
                geometry={"vertices": [[float(i * 100), 0.0]], "closed": False, "bulges": None},
            )
        )
    await session.flush()
    return drawing, sheet


async def test_detect_dxf_clusters_creates_proposed_cluster_and_is_idempotent(rls_session):
    tenant_id, project_id = await _seed_project(rls_session)
    sys_ctx = _ctx(frozenset(), tenant_id=tenant_id, is_system=True)
    await set_rls_context(rls_session, sys_ctx)
    await _seed_dxf_sheet_with_inserts(rls_session, tenant_id, project_id, count=3)

    lead_ctx = _ctx(_LEAD, tenant_id=tenant_id, user_id=_MEMBER_USER_ID)
    await set_rls_context(rls_session, lead_ctx)
    clusters = await typology_service.detect_clusters(rls_session, lead_ctx, project_id)
    assert len(clusters) == 1
    cluster = clusters[0]
    assert cluster.status == "proposed"
    assert cluster.detection_method == "dxf_block"
    assert cluster.detection_key == "VILLA_A"
    assert cluster.master_instance_id is not None

    instances = await typology_service.list_cluster_instances(rls_session, cluster.id)
    assert len(instances) == 1
    assert instances[0].group_label == "type A"
    assert instances[0].instance_count == 3
    assert set(instances[0].source_handles) == {"h0", "h1", "h2"}

    again = await typology_service.detect_clusters(rls_session, lead_ctx, project_id)
    assert again == []  # already proposed for this exact (project, method, key) -- no duplicate

    all_clusters = await typology_service.list_clusters(rls_session, project_id)
    assert len(all_clusters) == 1


async def test_detect_ignores_lone_instances_and_signature_outliers(rls_session):
    tenant_id, project_id = await _seed_project(rls_session)
    sys_ctx = _ctx(frozenset(), tenant_id=tenant_id, is_system=True)
    await set_rls_context(rls_session, sys_ctx)
    await _seed_dxf_sheet_with_inserts(rls_session, tenant_id, project_id, block_name="LONE_BLOCK", count=1)

    lead_ctx = _ctx(_LEAD, tenant_id=tenant_id, user_id=_MEMBER_USER_ID)
    await set_rls_context(rls_session, lead_ctx)
    clusters = await typology_service.detect_clusters(rls_session, lead_ctx, project_id)
    assert clusters == []


async def test_confirm_splits_detected_batch_into_groups_with_master_and_deltas(rls_session):
    tenant_id, project_id = await _seed_project(rls_session)
    sys_ctx = _ctx(frozenset(), tenant_id=tenant_id, is_system=True)
    await set_rls_context(rls_session, sys_ctx)
    await _seed_dxf_sheet_with_inserts(rls_session, tenant_id, project_id, count=3)

    lead_ctx = _ctx(_LEAD, tenant_id=tenant_id, user_id=_MEMBER_USER_ID)
    await set_rls_context(rls_session, lead_ctx)
    cluster = (await typology_service.detect_clusters(rls_session, lead_ctx, project_id))[0]

    confirmed = await typology_service.confirm_cluster(
        rls_session, lead_ctx, cluster.id,
        groups=[
            {"group_label": "type A", "handles": ["h0", "h1"]},
            {"group_label": "type B", "handles": ["h2"]},
        ],
        master_group_label="type A",
        deltas=[{"group_label": "type B", "description": "+1 maid room", "boq_line_item_id": None, "quantity_delta": None, "unit": None}],
    )
    assert confirmed.status == "confirmed"
    assert confirmed.confirmed_by == lead_ctx.user_id

    instances = await typology_service.list_cluster_instances(rls_session, cluster.id)
    by_label = {i.group_label: i for i in instances}
    assert by_label["type A"].instance_count == 2
    assert by_label["type B"].instance_count == 1
    assert confirmed.master_instance_id == by_label["type A"].id

    deltas = await typology_service.list_variant_deltas(rls_session, cluster.id)
    assert len(deltas) == 1
    assert deltas[0].description == "+1 maid room"


async def test_confirm_rejects_a_partition_that_omits_or_duplicates_handles(rls_session):
    tenant_id, project_id = await _seed_project(rls_session)
    sys_ctx = _ctx(frozenset(), tenant_id=tenant_id, is_system=True)
    await set_rls_context(rls_session, sys_ctx)
    await _seed_dxf_sheet_with_inserts(rls_session, tenant_id, project_id, count=3)

    lead_ctx = _ctx(_LEAD, tenant_id=tenant_id, user_id=_MEMBER_USER_ID)
    await set_rls_context(rls_session, lead_ctx)
    cluster = (await typology_service.detect_clusters(rls_session, lead_ctx, project_id))[0]

    with pytest.raises(ValidationAppError):
        await typology_service.confirm_cluster(
            rls_session, lead_ctx, cluster.id,
            groups=[{"group_label": "type A", "handles": ["h0", "h1"]}],  # missing h2
            master_group_label="type A", deltas=[],
        )
    with pytest.raises(ValidationAppError):
        await typology_service.confirm_cluster(
            rls_session, lead_ctx, cluster.id,
            groups=[{"group_label": "type A", "handles": ["h0"]}, {"group_label": "type B", "handles": ["h0", "h1", "h2"]}],
            master_group_label="type A", deltas=[],
        )


async def test_reject_cluster_then_confirm_raises_conflict(rls_session):
    tenant_id, project_id = await _seed_project(rls_session)
    sys_ctx = _ctx(frozenset(), tenant_id=tenant_id, is_system=True)
    await set_rls_context(rls_session, sys_ctx)
    await _seed_dxf_sheet_with_inserts(rls_session, tenant_id, project_id, count=2)

    lead_ctx = _ctx(_LEAD, tenant_id=tenant_id, user_id=_MEMBER_USER_ID)
    await set_rls_context(rls_session, lead_ctx)
    cluster = (await typology_service.detect_clusters(rls_session, lead_ctx, project_id))[0]

    rejected = await typology_service.reject_cluster(rls_session, lead_ctx, cluster.id)
    assert rejected.status == "rejected"

    with pytest.raises(ConflictError):
        await typology_service.confirm_cluster(
            rls_session, lead_ctx, cluster.id,
            groups=[{"group_label": "type A", "handles": ["h0", "h1"]}], master_group_label="type A", deltas=[],
        )

    # A rejected key doesn't block a fresh detect -- deliberate default,
    # see typology_service._propose_cluster's docstring.
    reproposed = await typology_service.detect_clusters(rls_session, lead_ctx, project_id)
    assert len(reproposed) == 1
    assert reproposed[0].id != cluster.id


async def test_detect_denies_estimator(rls_session):
    tenant_id, project_id = await _seed_project(rls_session)
    sys_ctx = _ctx(frozenset(), tenant_id=tenant_id, is_system=True)
    await set_rls_context(rls_session, sys_ctx)
    await _seed_dxf_sheet_with_inserts(rls_session, tenant_id, project_id, count=2)

    estimator_ctx = _ctx(_ESTIMATOR, tenant_id=tenant_id, user_id=_MEMBER_USER_ID)
    await set_rls_context(rls_session, estimator_ctx)
    with pytest.raises(ProgrammingError, match="row-level security policy"):
        await typology_service.detect_clusters(rls_session, estimator_ctx, project_id)


async def test_rollup_multiplies_master_quantity_by_instance_count_and_adds_deltas(rls_session):
    tenant_id, project_id = await _seed_project(rls_session)
    sys_ctx = _ctx(frozenset(), tenant_id=tenant_id, is_system=True)
    await set_rls_context(rls_session, sys_ctx)
    drawing, sheet = await _seed_dxf_sheet_with_inserts(rls_session, tenant_id, project_id, count=3)

    # A measurement spatially inside the master instance's own bbox
    # (h0: x in [0, 10]) -- the rollup's spatial BOQ-scoping (Phase 4b bbox).
    measurement = DrawingMeasurement(
        tenant_id=tenant_id, drawing_id=drawing.id, sheet_id=sheet.id, project_id=project_id,
        capability="alignment", kind="alignment_length_m", value=Decimal("3.0"), unit="m", confidence=Decimal("1.0"),
        source_entity_ids=[], bbox_min_x=1.0, bbox_min_y=0.5, bbox_max_x=9.0, bbox_max_y=4.5,
    )
    rls_session.add(measurement)
    await rls_session.flush()

    lead_ctx = _ctx(_LEAD, tenant_id=tenant_id, user_id=_MEMBER_USER_ID)
    await set_rls_context(rls_session, lead_ctx)
    item = await boq_service.create_line_item(
        rls_session, lead_ctx, project_id,
        BoqLineItemCreate(item_no="1.0", description="Foundation wall run", uom="m", boq_quantity=45.0),
    )

    estimator_ctx = _ctx(_ESTIMATOR, tenant_id=tenant_id, user_id=_MEMBER_USER_ID)
    await set_rls_context(rls_session, estimator_ctx)
    await boq_service.add_measurement_link(rls_session, estimator_ctx, item.id, measurement.id)

    await set_rls_context(rls_session, lead_ctx)
    cluster = (await typology_service.detect_clusters(rls_session, lead_ctx, project_id))[0]
    confirmed = await typology_service.confirm_cluster(
        rls_session, lead_ctx, cluster.id,
        groups=[
            {"group_label": "type A", "handles": ["h0", "h1"]},
            {"group_label": "type B", "handles": ["h2"]},
        ],
        master_group_label="type A",
        deltas=[{"group_label": "type B", "description": "+1 bedroom, longer wall run", "boq_line_item_id": str(item.id), "quantity_delta": 5.0, "unit": "m"}],
    )

    rollup = await typology_service.get_rollup(rls_session, confirmed.id)
    assert rollup["total_instance_count"] == 3  # 2 (type A) + 1 (type B)
    assert len(rollup["items"]) == 1
    row = rollup["items"][0]
    assert row["boq_line_item_id"] == str(item.id)
    assert row["master_quantity"] == pytest.approx(45.0)
    # 45 x 3 total instances + (5.0 delta x 1 type-B instance)
    assert row["total"] == pytest.approx(45.0 * 3 + 5.0 * 1)
    assert row["deltas"][0]["group_label"] == "type B"
    assert row["deltas"][0]["contribution"] == pytest.approx(5.0)
