"""Module B Phase 4c: clustered typology recognition -- detect (proposes
clusters from DXF block references / PDF geometry hashing), confirm (the
estimator names groups, picks the master, records variant deltas), and
the read-only rollup. See app/takeoff/typology.py for the pure detection
algorithms this orchestrates and docs/module-b-phase4-plan.md §4c for the
design."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import RequestContext
from app.core.enums import AuditAction
from app.core.errors import ConflictError, NotFoundError, ValidationAppError
from app.models.boq import BoqLineItem, BoqLineItemMeasurement
from app.models.takeoff import DrawingEntity, DrawingMeasurement, DrawingSheet
from app.models.typology import TypologyCluster, TypologyClusterInstance, TypologyVariantDelta
from app.services import audit
from app.services.projects import assert_can_see_project
from app.services.takeoff import GEOMETRIC_ENTITY_TYPES, row_to_geometric_entity
from app.takeoff.geometry.entities import GeometricEntity
from app.takeoff.typology import (
    group_dxf_instances_by_block,
    group_pdf_regions_by_hash,
    union_bbox,
)

# Defaults the SRS doesn't specify a number for -- see
# docs/module-b-phase4-plan.md §4c ("tolerance band (configurable,
# default 2%)" for DXF, "default 5% of the region's own diagonal" for
# PDF); the proximity gap (how close two PDF entities' bboxes must be to
# be considered "the same region") has no plan-doc default at all, picked
# here as a small absolute value in page points (about 1mm at 72pt/in).
DEFAULT_DXF_SIGNATURE_TOLERANCE_PCT = 2.0
DEFAULT_PDF_GRID_TOLERANCE_PCT = 5.0
DEFAULT_PDF_PROXIMITY_GAP_PT = 2.83


async def _get_cluster(session: AsyncSession, cluster_id: UUID) -> TypologyCluster:
    result = await session.execute(select(TypologyCluster).where(TypologyCluster.id == cluster_id))
    cluster = result.scalar_one_or_none()
    if cluster is None:
        raise NotFoundError(f"Typology cluster {cluster_id} not found")
    return cluster


async def list_clusters(session: AsyncSession, project_id: UUID) -> list[TypologyCluster]:
    result = await session.execute(
        select(TypologyCluster).where(TypologyCluster.project_id == project_id).order_by(TypologyCluster.created_at)
    )
    return list(result.scalars().all())


async def get_cluster(session: AsyncSession, cluster_id: UUID) -> TypologyCluster:
    return await _get_cluster(session, cluster_id)


async def list_cluster_instances(session: AsyncSession, cluster_id: UUID) -> list[TypologyClusterInstance]:
    result = await session.execute(
        select(TypologyClusterInstance)
        .where(TypologyClusterInstance.cluster_id == cluster_id)
        .order_by(TypologyClusterInstance.group_label)
    )
    return list(result.scalars().all())


async def list_variant_deltas(session: AsyncSession, cluster_id: UUID) -> list[TypologyVariantDelta]:
    result = await session.execute(
        select(TypologyVariantDelta).where(TypologyVariantDelta.cluster_id == cluster_id)
    )
    return list(result.scalars().all())


async def _propose_cluster(
    session: AsyncSession, ctx: RequestContext, project_id: UUID, *, detection_method: str, detection_key: str,
    tolerance_pct: float, entities: list[GeometricEntity], entity_rows_by_id: dict[int, DrawingEntity],
) -> TypologyCluster | None:
    """Idempotent: skips (returns None) when a proposed or confirmed
    cluster already exists for this exact (project, method, key) --
    re-running detect must never spawn duplicate proposals for the same
    grouping. A previously *rejected* cluster does NOT block a fresh
    proposal -- see this module's docstring / docs/build-log.md for why
    that's a deliberate default, not an oversight."""
    existing = (
        await session.execute(
            select(TypologyCluster).where(
                TypologyCluster.project_id == project_id, TypologyCluster.detection_method == detection_method,
                TypologyCluster.detection_key == detection_key, TypologyCluster.status.in_(["proposed", "confirmed"]),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return None

    rows = [entity_rows_by_id[id(e)] for e in entities]
    bbox = union_bbox(entities)
    representative = rows[0]

    cluster = TypologyCluster(
        tenant_id=ctx.tenant_id, project_id=project_id, status="proposed", master_instance_id=None,
        detection_method=detection_method, detection_key=detection_key, tolerance_pct=tolerance_pct,
    )
    session.add(cluster)
    await session.flush()

    instance = TypologyClusterInstance(
        tenant_id=ctx.tenant_id, cluster_id=cluster.id, project_id=project_id, sheet_id=representative.sheet_id,
        bbox_min_x=bbox[0] if bbox else None, bbox_min_y=bbox[1] if bbox else None,
        bbox_max_x=bbox[2] if bbox else None, bbox_max_y=bbox[3] if bbox else None,
        group_label="type A", instance_count=len(rows), source_handles=[r.handle for r in rows if r.handle],
    )
    session.add(instance)
    await session.flush()

    cluster.master_instance_id = instance.id
    await session.flush()
    return cluster


async def detect_clusters(session: AsyncSession, ctx: RequestContext, project_id: UUID) -> list[TypologyCluster]:
    """Runs both detection strategies across every sheet in the project
    and proposes a new TypologyCluster for each newly-found grouping
    (skipping ones already proposed/confirmed for the same detection
    key -- see _propose_cluster). DXF sheets (units != "pt") are grouped
    by block reference; PDF sheets (units == "pt") by per-sheet proximity
    region + normalised geometry hash matched across sheets."""
    await assert_can_see_project(session, ctx, project_id)
    sheets = (
        await session.execute(select(DrawingSheet).where(DrawingSheet.project_id == project_id))
    ).scalars().all()
    if not sheets:
        return []

    dxf_sheet_ids = [s.id for s in sheets if s.units != "pt"]
    pdf_sheet_ids = [s.id for s in sheets if s.units == "pt"]

    created: list[TypologyCluster] = []

    if dxf_sheet_ids:
        rows = (
            await session.execute(
                select(DrawingEntity).where(
                    DrawingEntity.sheet_id.in_(dxf_sheet_ids), DrawingEntity.entity_type == "insert_node"
                )
            )
        ).scalars().all()
        entity_rows_by_id: dict[int, DrawingEntity] = {}
        entities: list[GeometricEntity] = []
        for row in rows:
            g = row_to_geometric_entity(row)
            entity_rows_by_id[id(g)] = row
            entities.append(g)
        for group in group_dxf_instances_by_block(entities, DEFAULT_DXF_SIGNATURE_TOLERANCE_PCT):
            cluster = await _propose_cluster(
                session, ctx, project_id, detection_method="dxf_block", detection_key=group.key,
                tolerance_pct=DEFAULT_DXF_SIGNATURE_TOLERANCE_PCT, entities=group.entities,
                entity_rows_by_id=entity_rows_by_id,
            )
            if cluster is not None:
                created.append(cluster)

    if pdf_sheet_ids:
        rows = (
            await session.execute(
                select(DrawingEntity).where(
                    DrawingEntity.sheet_id.in_(pdf_sheet_ids), DrawingEntity.entity_type.in_(GEOMETRIC_ENTITY_TYPES)
                )
            )
        ).scalars().all()
        entity_rows_by_id = {}
        entities_by_sheet: dict[UUID, list[GeometricEntity]] = {}
        for row in rows:
            g = row_to_geometric_entity(row)
            entity_rows_by_id[id(g)] = row
            entities_by_sheet.setdefault(row.sheet_id, []).append(g)
        for group in group_pdf_regions_by_hash(
            entities_by_sheet, proximity_gap=DEFAULT_PDF_PROXIMITY_GAP_PT, grid_tolerance_pct=DEFAULT_PDF_GRID_TOLERANCE_PCT
        ):
            flat_entities = [e for region in group.regions for e in region]
            cluster = await _propose_cluster(
                session, ctx, project_id, detection_method="pdf_geometry_hash", detection_key=group.key,
                tolerance_pct=DEFAULT_PDF_GRID_TOLERANCE_PCT, entities=flat_entities,
                entity_rows_by_id=entity_rows_by_id,
            )
            if cluster is not None:
                created.append(cluster)

    if created:
        await audit.record(
            session, ctx, action=AuditAction.CREATE, entity_type="typology_clusters", entity_id=project_id,
            project_id=project_id, payload={"proposed_count": len(created), "cluster_ids": [str(c.id) for c in created]},
        )
    return created


async def confirm_cluster(
    session: AsyncSession, ctx: RequestContext, cluster_id: UUID, *,
    groups: list[dict], master_group_label: str, deltas: list[dict],
) -> TypologyCluster:
    """`groups` must exactly partition the cluster's own currently-detected
    handles (every detected handle in exactly one group, no extras, no
    omissions) -- lets the estimator split a homogeneous detected batch
    into "type A" / "type B" sub-groups (e.g. spotting that 2 of 12
    detected instances are actually a variant) without a re-detect.
    Replaces the cluster's auto-detected single instance row with this
    partition (delete-then-reinsert, same whole-set-replace convention as
    pdf_layer_mapping_rules/drawing_layer_trade_mappings)."""
    cluster = await _get_cluster(session, cluster_id)
    if cluster.status != "proposed":
        raise ConflictError(f"Typology cluster {cluster_id} is {cluster.status!r}, not proposed -- cannot confirm")

    existing_instances = await list_cluster_instances(session, cluster_id)
    all_detected_handles = {h for inst in existing_instances for h in inst.source_handles}
    grouped_handles = {h for g in groups for h in g["handles"]}
    if grouped_handles != all_detected_handles:
        raise ValidationAppError(
            "groups must exactly partition this cluster's detected handles "
            f"(missing: {sorted(all_detected_handles - grouped_handles)}, "
            f"unexpected: {sorted(grouped_handles - all_detected_handles)})"
        )
    seen: set[str] = set()
    for g in groups:
        overlap = seen & set(g["handles"])
        if overlap:
            raise ValidationAppError(f"handle(s) assigned to more than one group: {sorted(overlap)}")
        seen.update(g["handles"])
    if master_group_label not in {g["group_label"] for g in groups}:
        raise ValidationAppError(f"master_group_label {master_group_label!r} is not one of the given groups")

    # Break the FK before deleting -- master_instance_id currently points
    # at an instance row about to be replaced.
    cluster.master_instance_id = None
    await session.flush()
    for inst in existing_instances:
        await session.delete(inst)
    await session.flush()

    representative_entity_by_handle = await _representative_entities_by_handle(session, cluster.project_id, grouped_handles)

    master_instance_id: UUID | None = None
    for g in groups:
        handles = g["handles"]
        rows = [representative_entity_by_handle[h] for h in handles if h in representative_entity_by_handle]
        bbox = _bbox_from_rows(rows)
        representative = rows[0] if rows else None
        instance = TypologyClusterInstance(
            tenant_id=ctx.tenant_id, cluster_id=cluster.id, project_id=cluster.project_id,
            sheet_id=representative.sheet_id if representative else None,
            bbox_min_x=bbox[0] if bbox else None, bbox_min_y=bbox[1] if bbox else None,
            bbox_max_x=bbox[2] if bbox else None, bbox_max_y=bbox[3] if bbox else None,
            group_label=g["group_label"], instance_count=len(handles), source_handles=handles,
        )
        session.add(instance)
        await session.flush()
        if g["group_label"] == master_group_label:
            master_instance_id = instance.id

    for delta in deltas:
        session.add(
            TypologyVariantDelta(
                tenant_id=ctx.tenant_id, cluster_id=cluster.id, project_id=cluster.project_id,
                group_label=delta["group_label"], description=delta["description"],
                boq_line_item_id=delta.get("boq_line_item_id"), quantity_delta=delta.get("quantity_delta"),
                unit=delta.get("unit"),
            )
        )

    cluster.status = "confirmed"
    cluster.master_instance_id = master_instance_id
    cluster.confirmed_by = ctx.user_id
    cluster.confirmed_at = datetime.now(timezone.utc)
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.UPDATE, entity_type="typology_cluster", entity_id=cluster.id,
        project_id=cluster.project_id,
        payload={"status": "confirmed", "group_count": len(groups), "master_group_label": master_group_label},
    )
    return cluster


async def reject_cluster(session: AsyncSession, ctx: RequestContext, cluster_id: UUID) -> TypologyCluster:
    cluster = await _get_cluster(session, cluster_id)
    if cluster.status != "proposed":
        raise ConflictError(f"Typology cluster {cluster_id} is {cluster.status!r}, not proposed -- cannot reject")
    cluster.status = "rejected"
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.UPDATE, entity_type="typology_cluster", entity_id=cluster.id,
        project_id=cluster.project_id, payload={"status": "rejected"},
    )
    return cluster


async def _representative_entities_by_handle(
    session: AsyncSession, project_id: UUID, handles: set[str]
) -> dict[str, DrawingEntity]:
    """Handles aren't safely unique across more than one Drawing in a
    project (see app/takeoff/typology.py's DxfInstanceGroup docstring) --
    this picks *a* matching row per handle for display purposes only
    (sheet_id/bbox of one representative), which is a real but narrow
    ambiguity: two different drawings' entities that happen to share a
    raw handle string would be indistinguishable here. Acceptable for a
    representative split-pane location (source_handles on the row still
    has every real handle for full traceability); not acceptable if this
    were used to resolve which *specific* entity to modify."""
    if not handles:
        return {}
    rows = (
        await session.execute(
            select(DrawingEntity)
            .join(DrawingSheet, DrawingSheet.id == DrawingEntity.sheet_id)
            .where(DrawingSheet.project_id == project_id, DrawingEntity.handle.in_(handles))
        )
    ).scalars().all()
    result: dict[str, DrawingEntity] = {}
    for row in rows:
        result.setdefault(row.handle, row)
    return result


def _bbox_from_rows(rows: list[DrawingEntity]) -> tuple[float, float, float, float] | None:
    boxes = [
        (r.bbox_min_x, r.bbox_min_y, r.bbox_max_x, r.bbox_max_y) for r in rows if r.bbox_min_x is not None
    ]
    if not boxes:
        return None
    return (
        min(float(b[0]) for b in boxes), min(float(b[1]) for b in boxes),
        max(float(b[2]) for b in boxes), max(float(b[3]) for b in boxes),
    )


async def get_rollup(session: AsyncSession, cluster_id: UUID) -> dict:
    """total(item) = master_group's own BOQ quantity for `item` x
    (sum of every group's instance_count) + sum(delta.quantity_delta x
    that delta's own group's instance_count, for deltas touching `item`).

    "Which BOQ items belong to the master" is resolved spatially, not via
    a new join table: any BoqLineItem linked (BoqLineItemMeasurement) to a
    DrawingMeasurement whose own bbox (Module B Phase 4b) is fully
    contained within the master instance's bbox is in scope -- this reuses
    Phase 4b's bbox columns instead of inventing new storage, per the
    plan doc's "a cluster just groups which BOQ items belong to the
    master" (read as: the rollup computation determines the grouping on
    read, not that a group is separately, explicitly stored)."""
    cluster = await _get_cluster(session, cluster_id)
    if cluster.status != "confirmed":
        raise ConflictError(f"Typology cluster {cluster_id} is {cluster.status!r}, not confirmed -- no rollup yet")
    instances = await list_cluster_instances(session, cluster_id)
    total_instance_count = sum(i.instance_count for i in instances)
    master = next((i for i in instances if i.id == cluster.master_instance_id), None)
    if master is None or master.bbox_min_x is None:
        return {"cluster_id": str(cluster_id), "total_instance_count": total_instance_count, "items": [], "note": "master instance has no known extent -- rollup unavailable"}

    measurements = (
        await session.execute(
            select(DrawingMeasurement).where(
                DrawingMeasurement.sheet_id == master.sheet_id,
                DrawingMeasurement.bbox_min_x >= master.bbox_min_x, DrawingMeasurement.bbox_max_x <= master.bbox_max_x,
                DrawingMeasurement.bbox_min_y >= master.bbox_min_y, DrawingMeasurement.bbox_max_y <= master.bbox_max_y,
            )
        )
    ).scalars().all()
    measurement_ids = [m.id for m in measurements]

    items_by_id: dict[UUID, BoqLineItem] = {}
    if measurement_ids:
        links = (
            await session.execute(
                select(BoqLineItemMeasurement, BoqLineItem)
                .join(BoqLineItem, BoqLineItem.id == BoqLineItemMeasurement.boq_line_item_id)
                .where(BoqLineItemMeasurement.measurement_id.in_(measurement_ids))
            )
        ).all()
        for _link, item in links:
            items_by_id[item.id] = item

    deltas = await list_variant_deltas(session, cluster_id)
    instance_count_by_group = {i.group_label: i.instance_count for i in instances}

    results = []
    for item in items_by_id.values():
        base_qty = float(item.boq_quantity) if item.boq_quantity is not None else 0.0
        total = base_qty * total_instance_count
        delta_breakdown = []
        for d in deltas:
            if d.boq_line_item_id != item.id or d.quantity_delta is None:
                continue
            group_count = instance_count_by_group.get(d.group_label, 0)
            contribution = float(d.quantity_delta) * group_count
            total += contribution
            delta_breakdown.append({"group_label": d.group_label, "quantity_delta": float(d.quantity_delta), "instance_count": group_count, "contribution": contribution})
        results.append({
            "boq_line_item_id": str(item.id), "item_no": item.item_no, "master_quantity": base_qty,
            "total_instance_count": total_instance_count, "total": total, "deltas": delta_breakdown,
        })

    return {"cluster_id": str(cluster_id), "total_instance_count": total_instance_count, "items": results}
