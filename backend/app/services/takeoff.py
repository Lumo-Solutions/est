from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import delete as sa_delete
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.context import RequestContext
from app.core.enums import AuditAction, DrawingStatus
from app.core.errors import ConflictError, NotFoundError, ValidationAppError
from app.integrations.embeddings import get_embedder
from app.integrations.s3 import presign_get_url, put_object_streaming
from app.models.takeoff import (
    Drawing,
    DrawingEntity,
    DrawingLayerTradeMapping,
    DrawingMeasurement,
    DrawingMeasurementOverride,
    DrawingSheet,
    ExtractionJob,
    PdfLayerMappingRule,
    SheetScaleCalibration,
)
from app.services import audit
from app.services.projects import assert_can_see_project
from app.takeoff.geometry.entities import GeometricEntity

_ALLOWED_CONTENT_TYPES = {
    "application/pdf": "vector_pdf",  # refined to scanned_pdf per-page during indexing
    "application/dxf": "dxf",
    "image/vnd.dxf": "dxf",
}

# Entity types that carry a `geometry` payload (see app.takeoff.dxf::
# index_dxf_geometry / app.takeoff.pdf::index_pdf_geometry); excludes
# "text"/"mtext"/"attrib"/"dimension", which never do (dimension entities
# carry defpoints in `vertices` too, but are deliberately excluded here --
# they're a scale-detection signal, not takeoff quantity geometry).
GEOMETRIC_ENTITY_TYPES = ("line", "lwpolyline", "arc", "insert_node")


def row_to_geometric_entity(row: DrawingEntity) -> GeometricEntity:
    geometry = row.geometry or {}
    return GeometricEntity(
        entity_type=row.entity_type,
        layer=row.layer,
        handle=row.handle,
        vertices=[tuple(v) for v in (geometry.get("vertices") or [])],
        closed=bool(geometry.get("closed", False)),
        bulges=list(geometry.get("bulges") or []),
        block_name=row.block_name,
        attributes=dict(row.attributes or {}),
        center=tuple(geometry["center"]) if geometry.get("center") else None,
        radius=geometry.get("radius"),
        start_angle_deg=geometry.get("start_angle_deg"),
        end_angle_deg=geometry.get("end_angle_deg"),
    )


def _resolve_trade_node_id(layers: set[str], rules: list[DrawingLayerTradeMapping]) -> UUID | None:
    """First rule (in a stable, deterministic order) whose layer_pattern is
    a case-insensitive substring of any of the given layers -- never
    guessed when nothing matches. Same "simple and predictable" matching
    convention as AlignmentConfig.layer_hints."""
    for rule in rules:
        pattern = rule.layer_pattern.upper()
        if any(pattern in layer.upper() for layer in layers):
            return rule.trade_node_id
    return None


def _union_bbox(
    entities_by_handle: dict[str, DrawingEntity], handles: list[str]
) -> tuple[float, float, float, float] | None:
    boxes = [
        (e.bbox_min_x, e.bbox_min_y, e.bbox_max_x, e.bbox_max_y)
        for h in handles
        if (e := entities_by_handle.get(h)) is not None and e.bbox_min_x is not None
    ]
    if not boxes:
        return None
    return (
        min(b[0] for b in boxes), min(b[1] for b in boxes),
        max(b[2] for b in boxes), max(b[3] for b in boxes),
    )


async def recompute_sheet_measurements(session: AsyncSession, sheet: DrawingSheet) -> None:
    """Deletes and rebuilds one sheet's drawing_measurements from its
    currently-persisted drawing_entities geometry, using the sheet's
    CURRENT scale_ratio -- shared by the extraction pipeline
    (app.workers.tasks.takeoff::_extract_geometry_measurements_body, one
    call per sheet) and set_manual_scale below (one call, right after a
    calibration changes scale_ratio), so dependent measurements are never
    computed against a stale ratio (Module B Phase 4a). A no-op when
    TAKEOFF_PERSIST_GEOMETRY is off (nothing persisted to recompute from)
    or the sheet has no geometry entities at all yet.

    Also resolves trade_node_id (against drawing_layer_trade_mappings) and
    a denormalized bbox (union of source entities' own boxes) per
    measurement -- Module B Phase 4b. The delete-then-reinsert here means
    a measurement's active override (drawing_measurement_overrides,
    ON DELETE CASCADE on measurement_id) does NOT survive a recompute: a
    scale recalibration or re-extraction is exactly the kind of change
    that can make a prior manual override's number stale too, so this is
    a deliberate choice, not an oversight -- an estimator re-overrides
    after a recompute rather than a stale number surviving it silently."""
    if not get_settings().takeoff_persist_geometry:
        return

    # Imported here, not at module load, so importing this module never
    # has the side effect of populating the geometry registry -- only
    # actually calling this function does (same reasoning as the
    # pipeline's own original inline import).
    from app.takeoff.geometry import stubs as _geometry_stubs  # noqa: F401 -- registers extractors
    from app.takeoff.geometry.base import get_registry

    await session.execute(sa_delete(DrawingMeasurement).where(DrawingMeasurement.sheet_id == sheet.id))

    rows = (
        await session.execute(
            select(DrawingEntity).where(
                DrawingEntity.sheet_id == sheet.id, DrawingEntity.entity_type.in_(GEOMETRIC_ENTITY_TYPES)
            )
        )
    ).scalars().all()
    if not rows:
        await session.flush()
        return

    entities = [row_to_geometric_entity(r) for r in rows]
    entities_by_handle = {r.handle: r for r in rows if r.handle}
    trade_rules = (
        await session.execute(
            select(DrawingLayerTradeMapping).where(DrawingLayerTradeMapping.project_id == sheet.project_id)
        )
    ).scalars().all()

    for extractor in get_registry().values():
        if not extractor.supports(sheet):
            continue
        for m in extractor.extract(sheet, entities):
            layers = {entities_by_handle[h].layer for h in m.source_entity_ids if h in entities_by_handle and entities_by_handle[h].layer}
            bbox = _union_bbox(entities_by_handle, m.source_entity_ids)
            session.add(
                DrawingMeasurement(
                    tenant_id=sheet.tenant_id, drawing_id=sheet.drawing_id, sheet_id=sheet.id,
                    project_id=sheet.project_id, capability=extractor.capability, kind=m.kind, value=m.value,
                    unit=m.unit, confidence=m.confidence, source_entity_ids=m.source_entity_ids,
                    extractor_metadata=m.metadata, trade_node_id=_resolve_trade_node_id(layers, trade_rules),
                    bbox_min_x=bbox[0] if bbox else None, bbox_min_y=bbox[1] if bbox else None,
                    bbox_max_x=bbox[2] if bbox else None, bbox_max_y=bbox[3] if bbox else None,
                )
            )
    await session.flush()


async def record_scale_calibration(
    session: AsyncSession, sheet: DrawingSheet, *, ratio: float | None, source: str, confidence: float,
    set_by: UUID | None, note: str | None = None,
) -> SheetScaleCalibration:
    """Writes one append-only history row and mirrors it onto the sheet's
    own current-value columns -- called for both an auto-detected fusion
    result (app.workers.tasks.takeoff::_extract_sheet_body) and a manual
    two-point calibration (set_manual_scale below). See
    app.models.takeoff.SheetScaleCalibration's docstring."""
    calibration = SheetScaleCalibration(
        tenant_id=sheet.tenant_id, sheet_id=sheet.id, project_id=sheet.project_id, ratio=ratio, source=source,
        confidence=confidence, set_by=set_by, set_at=datetime.now(timezone.utc), note=note,
    )
    session.add(calibration)
    sheet.scale_ratio = ratio
    sheet.scale_source = source
    sheet.scale_confidence = confidence
    await session.flush()
    return calibration


async def upload_drawing(
    session: AsyncSession, ctx: RequestContext, project_id: UUID, filename: str, content_type: str | None, data: bytes
) -> Drawing:
    # `drawings` is project_scoped (RLS), but there's no prior read here to
    # let that policy silently filter an unauthorized caller out the way it
    # would for e.g. trigger_ingest's SELECT-then-UPDATE -- an INSERT's
    # WITH CHECK fails hard instead. Check first (before streaming to S3)
    # so an estimator/lead_estimator without project membership gets a
    # clean 403 immediately, not a 500 (or a wasted upload) partway through.
    await assert_can_see_project(session, ctx, project_id)

    kind = _ALLOWED_CONTENT_TYPES.get(content_type or "", "unknown")
    if kind == "unknown" and filename.lower().endswith(".dxf"):
        kind = "dxf"
    elif kind == "unknown" and filename.lower().endswith(".pdf"):
        kind = "vector_pdf"

    object_key = f"projects/{project_id}/drawings/{filename}"
    sha256 = await put_object_streaming(object_key, data, content_type)

    existing = await session.execute(
        select(Drawing).where(Drawing.project_id == project_id, Drawing.sha256 == sha256)
    )
    if (row := existing.scalar_one_or_none()) is not None:
        return row

    drawing = Drawing(
        tenant_id=ctx.tenant_id,
        project_id=project_id,
        original_filename=filename,
        content_type=content_type,
        kind=kind,
        bucket="installtec-drawings",
        object_key=object_key,
        size_bytes=len(data),
        sha256=sha256,
        status=DrawingStatus.UPLOADED.value,
        uploaded_by=ctx.user_id,
    )
    session.add(drawing)
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.CREATE, entity_type="drawing", entity_id=drawing.id,
        project_id=project_id, payload={"filename": filename, "size_bytes": len(data)},
    )
    return drawing


async def get_drawing(session: AsyncSession, drawing_id: UUID) -> Drawing:
    result = await session.execute(select(Drawing).where(Drawing.id == drawing_id))
    drawing = result.scalar_one_or_none()
    if drawing is None:
        raise NotFoundError(f"Drawing {drawing_id} not found")
    return drawing


async def trigger_ingest(session: AsyncSession, ctx: RequestContext, drawing_id: UUID) -> list[str]:
    from app.workers.tasks.takeoff import index_sheets

    drawing = await get_drawing(session, drawing_id)
    if drawing.status in (DrawingStatus.INDEXING.value, DrawingStatus.EXTRACTING.value, DrawingStatus.EMBEDDING.value):
        raise ConflictError(f"Drawing {drawing_id} is already being processed (status={drawing.status})")

    drawing.status = DrawingStatus.QUEUED.value
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.UPDATE, entity_type="drawing", entity_id=drawing.id,
        project_id=drawing.project_id, payload={"status": "queued"},
    )

    task = index_sheets.delay(
        str(drawing.id), str(ctx.tenant_id), str(ctx.user_id) if ctx.user_id else None, list(ctx.roles)
    )
    return [task.id]


async def list_jobs(session: AsyncSession, drawing_id: UUID) -> list[ExtractionJob]:
    result = await session.execute(
        select(ExtractionJob).where(ExtractionJob.drawing_id == drawing_id).order_by(ExtractionJob.started_at)
    )
    return list(result.scalars().all())


async def list_measurements(
    session: AsyncSession, drawing_id: UUID, sheet_id: UUID | None = None
) -> list[DrawingMeasurement]:
    stmt = select(DrawingMeasurement).where(DrawingMeasurement.drawing_id == drawing_id)
    if sheet_id is not None:
        stmt = stmt.where(DrawingMeasurement.sheet_id == sheet_id)
    stmt = stmt.order_by(DrawingMeasurement.sheet_id, DrawingMeasurement.capability, DrawingMeasurement.kind)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_sheet(session: AsyncSession, drawing_id: UUID, sheet_index: int) -> DrawingSheet:
    result = await session.execute(
        select(DrawingSheet).where(DrawingSheet.drawing_id == drawing_id, DrawingSheet.sheet_index == sheet_index)
    )
    sheet = result.scalar_one_or_none()
    if sheet is None:
        raise NotFoundError(f"Sheet {sheet_index} of drawing {drawing_id} not found")
    return sheet


async def set_manual_scale(
    session: AsyncSession, ctx: RequestContext, drawing_id: UUID, sheet_index: int,
    p1: tuple[float, float], p2: tuple[float, float], known_length_m: float,
) -> DrawingSheet:
    """Module B Phase 4a: writes a calibration history row (never just
    overwrites the sheet's current scale in place -- a reviewer can see
    what auto-detection originally found) and recomputes every dependent
    drawing_measurement against the new ratio before returning, so
    nothing is left stale relative to the calibration that was just set.

    p1/p2 are in the sheet's raw geometry coordinates (DXF native units,
    or PDF page points). scale_ratio's convention throughout this module
    is "real metres per *printed/modelled physical* unit" (matching
    title-block text like "1:100" -- see app/takeoff/scale.py's module
    docstring and app.takeoff.geometry.units::sheet_scale_factor, which is
    what actually applies this ratio to a measurement). For a DXF sheet
    the raw coordinates already are physical units, so this is a no-op
    conversion (factor 1.0, unchanged from before this existed as its own
    step); for a PDF sheet (units="pt") the raw two-point distance is
    first converted to a physical printed length before dividing --
    without this, a PDF calibration would silently be off by the
    points-to-metres factor (~2,835x), since sheet_scale_factor() folds
    that same conversion in separately when the ratio is later applied."""
    from app.takeoff.geometry.units import meters_per_unit

    sheet = await get_sheet(session, drawing_id, sheet_index)
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    drawing_distance_native = (dx**2 + dy**2) ** 0.5
    if drawing_distance_native <= 0:
        raise ConflictError("The two calibration points must be distinct")
    unit_factor = meters_per_unit(sheet.units) if sheet.units else None
    printed_physical_distance = drawing_distance_native * (unit_factor if unit_factor is not None else 1.0)
    if printed_physical_distance <= 0:
        raise ConflictError("The two calibration points must be distinct")
    ratio = known_length_m / printed_physical_distance
    await record_scale_calibration(
        session, sheet, ratio=ratio, source="manual_two_point", confidence=1.0, set_by=ctx.user_id,
        note=f"two-point: p1={p1} p2={p2} known_length_m={known_length_m}",
    )
    await recompute_sheet_measurements(session, sheet)
    await audit.record(
        session, ctx, action=AuditAction.UPDATE, entity_type="drawing_sheet", entity_id=sheet.id,
        project_id=sheet.project_id, payload={"scale_source": "manual_two_point", "scale_ratio": float(sheet.scale_ratio)},
    )
    return sheet


async def list_scale_calibrations(session: AsyncSession, drawing_id: UUID, sheet_index: int) -> list[SheetScaleCalibration]:
    sheet = await get_sheet(session, drawing_id, sheet_index)
    result = await session.execute(
        select(SheetScaleCalibration)
        .where(SheetScaleCalibration.sheet_id == sheet.id)
        .order_by(SheetScaleCalibration.set_at.desc())
    )
    return list(result.scalars().all())


async def revert_scale_calibration(
    session: AsyncSession, ctx: RequestContext, drawing_id: UUID, sheet_index: int, calibration_id: UUID,
) -> DrawingSheet:
    """"A revert is just applying the previous calibration row's values
    through the same path" (docs/module-b-phase4-plan.md §4a) -- writes a
    *new* history row carrying the target calibration's own values (never
    deletes/rewrites history) and recomputes measurements, exactly like
    set_manual_scale."""
    sheet = await get_sheet(session, drawing_id, sheet_index)
    target = (
        await session.execute(
            select(SheetScaleCalibration).where(
                SheetScaleCalibration.id == calibration_id, SheetScaleCalibration.sheet_id == sheet.id
            )
        )
    ).scalar_one_or_none()
    if target is None:
        raise NotFoundError(f"Calibration {calibration_id} not found for this sheet")

    await record_scale_calibration(
        session, sheet, ratio=target.ratio, source=target.source, confidence=target.confidence, set_by=ctx.user_id,
        note=f"reverted to calibration {target.id} ({target.source}, set {target.set_at.isoformat()})",
    )
    await recompute_sheet_measurements(session, sheet)
    await audit.record(
        session, ctx, action=AuditAction.UPDATE, entity_type="drawing_sheet", entity_id=sheet.id,
        project_id=sheet.project_id,
        payload={"reverted_to_calibration_id": str(target.id), "scale_ratio": float(sheet.scale_ratio) if sheet.scale_ratio else None},
    )
    return sheet


async def presigned_download_url(session: AsyncSession, ctx: RequestContext, drawing_id: UUID) -> str:
    drawing = await get_drawing(session, drawing_id)
    url = await presign_get_url(drawing.object_key)
    await audit.record(
        session, ctx, action=AuditAction.DOWNLOAD, entity_type="drawing", entity_id=drawing.id,
        project_id=drawing.project_id,
    )
    return url


async def search_sheets(session: AsyncSession, project_id: UUID, query: str, top_k: int) -> list[dict]:
    """Thin pgvector similarity probe -- proves the embedding store works.
    NOT BOQ reconciliation (deferred; see docs/architecture.md)."""
    embedder = get_embedder()
    vector = embedder.embed([query])[0]
    result = await session.execute(
        text(
            "SELECT sheet_id, drawing_id, chunk_type, content, embedding <=> (:v)::vector AS distance "
            "FROM sheet_chunks WHERE project_id = :p ORDER BY embedding <=> (:v)::vector LIMIT :k"
        ),
        {"v": str(vector), "p": str(project_id), "k": top_k},
    )
    return [dict(row._mapping) for row in result.all()]


async def list_pdf_layer_mapping_rules(session: AsyncSession, project_id: UUID) -> list[PdfLayerMappingRule]:
    result = await session.execute(
        select(PdfLayerMappingRule)
        .where(PdfLayerMappingRule.project_id == project_id)
        .order_by(PdfLayerMappingRule.priority)
    )
    return list(result.scalars().all())


async def replace_pdf_layer_mapping_rules(
    session: AsyncSession, ctx: RequestContext, project_id: UUID, rules: list[dict],
) -> list[PdfLayerMappingRule]:
    """Whole-set replace (not incremental add/remove) -- the rule set is
    small, project-scoped config edited as a unit, same reasoning as
    D1's TradeOverrideUpdate's own patch-set-not-incremental choice would
    have been overkill here: there's no per-field partial-update need,
    just "here is the current rule set." Audited as one action."""
    await assert_can_see_project(session, ctx, project_id)
    await session.execute(sa_delete(PdfLayerMappingRule).where(PdfLayerMappingRule.project_id == project_id))
    created = []
    for rule in rules:
        row = PdfLayerMappingRule(tenant_id=ctx.tenant_id, project_id=project_id, **rule)
        session.add(row)
        created.append(row)
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.UPDATE, entity_type="pdf_layer_mapping_rules", entity_id=project_id,
        project_id=project_id, payload={"rule_count": len(created)},
    )
    return created


# --------------------------------------------------------------------------
# Module B Phase 4b: non-destructive overrides, traceability, trade
# classification config
# --------------------------------------------------------------------------


async def get_measurement(session: AsyncSession, measurement_id: UUID) -> DrawingMeasurement:
    result = await session.execute(select(DrawingMeasurement).where(DrawingMeasurement.id == measurement_id))
    measurement = result.scalar_one_or_none()
    if measurement is None:
        raise NotFoundError(f"Measurement {measurement_id} not found")
    return measurement


async def override_measurement(
    session: AsyncSession, ctx: RequestContext, measurement_id: UUID, *, value: float, unit: str, note: str,
) -> DrawingMeasurementOverride:
    """Setting a new override while one is already active supersedes it:
    the old row's reverted_at is set in the same transaction (never
    deleted -- it stays as history), then the new row is inserted, so
    migration 0023's "at most one active row" partial unique index is
    never violated. `note` is required -- "why", not just "what" (Module
    B Phase 4b's own non-negotiable per the plan doc)."""
    if not note.strip():
        raise ValidationAppError("An override note is required -- explain why, not just what")
    measurement = await get_measurement(session, measurement_id)
    existing = (
        await session.execute(
            select(DrawingMeasurementOverride).where(
                DrawingMeasurementOverride.measurement_id == measurement_id,
                DrawingMeasurementOverride.reverted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if existing is not None:
        existing.reverted_by = ctx.user_id
        existing.reverted_at = now
        await session.flush()

    override = DrawingMeasurementOverride(
        tenant_id=measurement.tenant_id, measurement_id=measurement_id, project_id=measurement.project_id,
        value=value, unit=unit, note=note, overridden_by=ctx.user_id, overridden_at=now,
    )
    session.add(override)
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.UPDATE, entity_type="drawing_measurement", entity_id=measurement_id,
        project_id=measurement.project_id,
        payload={"override_value": float(value), "override_unit": unit, "note": note, "superseded_override_id": str(existing.id) if existing else None},
    )
    # See revert_measurement_override's comment -- `measurement.override`
    # (viewonly, lazy="joined") won't pick up this new row on its own.
    session.expire(measurement, ["override"])
    return override


async def revert_measurement_override(
    session: AsyncSession, ctx: RequestContext, measurement_id: UUID,
) -> DrawingMeasurement:
    measurement = await get_measurement(session, measurement_id)
    active = (
        await session.execute(
            select(DrawingMeasurementOverride).where(
                DrawingMeasurementOverride.measurement_id == measurement_id,
                DrawingMeasurementOverride.reverted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if active is None:
        raise ConflictError(f"Measurement {measurement_id} has no active override to revert")
    active.reverted_by = ctx.user_id
    active.reverted_at = datetime.now(timezone.utc)
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.UPDATE, entity_type="drawing_measurement", entity_id=measurement_id,
        project_id=measurement.project_id, payload={"reverted_override_id": str(active.id)},
    )
    # `override` is a viewonly, lazy="joined" relationship (its primaryjoin
    # filters reverted_at IS NULL) -- it was already loaded, stale, before
    # `active.reverted_at` was just set above, and the identity map won't
    # silently refresh an already-populated relationship just because a
    # later SELECT re-fetches the same parent row. Expiring it first, then
    # immediately re-fetching (the expired attribute is repopulated as
    # part of that awaited SELECT's own JOIN, not a separate lazy load --
    # a *bare* attribute access after expire(), with no subsequent await,
    # is what raises MissingGreenlet under async SQLAlchemy; this avoids
    # that by never touching `.override` without an awaited query first).
    session.expire(measurement, ["override"])
    return await get_measurement(session, measurement_id)


async def list_drawing_entities_in_region(
    session: AsyncSession, sheet_id: UUID,
    bbox: tuple[float, float, float, float] | None = None,
) -> list[DrawingEntity]:
    """For the split-pane traceability view -- all entities on a sheet, or
    (with bbox) only those *intersecting* a queried region, not just those
    fully contained by it, so a region straddling a boundary still returns
    what overlaps it (Module B Phase 4b)."""
    stmt = select(DrawingEntity).where(DrawingEntity.sheet_id == sheet_id)
    if bbox is not None:
        min_x, min_y, max_x, max_y = bbox
        stmt = stmt.where(
            DrawingEntity.bbox_min_x <= max_x, DrawingEntity.bbox_max_x >= min_x,
            DrawingEntity.bbox_min_y <= max_y, DrawingEntity.bbox_max_y >= min_y,
        )
    result = await session.execute(stmt.order_by(DrawingEntity.entity_type, DrawingEntity.handle))
    return list(result.scalars().all())


async def list_layer_trade_mappings(session: AsyncSession, project_id: UUID) -> list[DrawingLayerTradeMapping]:
    result = await session.execute(
        select(DrawingLayerTradeMapping)
        .where(DrawingLayerTradeMapping.project_id == project_id)
        .order_by(DrawingLayerTradeMapping.created_at)
    )
    return list(result.scalars().all())


async def replace_layer_trade_mappings(
    session: AsyncSession, ctx: RequestContext, project_id: UUID, mappings: list[dict],
) -> list[DrawingLayerTradeMapping]:
    """Whole-set replace, same reasoning as replace_pdf_layer_mapping_rules
    above -- small project-scoped config, edited as a unit."""
    await assert_can_see_project(session, ctx, project_id)
    await session.execute(sa_delete(DrawingLayerTradeMapping).where(DrawingLayerTradeMapping.project_id == project_id))
    created = []
    for mapping in mappings:
        row = DrawingLayerTradeMapping(tenant_id=ctx.tenant_id, project_id=project_id, **mapping)
        session.add(row)
        created.append(row)
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.UPDATE, entity_type="drawing_layer_trade_mappings", entity_id=project_id,
        project_id=project_id, payload={"mapping_count": len(created)},
    )
    return created
