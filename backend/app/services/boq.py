from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.boq import units as unit_conversion
from app.boq.reconciliation import (
    DEFAULT_RECONCILIATION_CONFIG,
    DiscrepancyClass,
    ReconciliationConfig,
    ReconciliationResult,
    aggregate_measurement_values,
    reconcile,
)
from app.core.context import RequestContext
from app.core.enums import AuditAction
from app.core.errors import NotFoundError, ValidationAppError
from app.models.boq import BoqLineItem, BoqLineItemMeasurement, BoqTolerance
from app.models.takeoff import DrawingMeasurement
from app.schemas.boq import BoqLineItemCreate
from app.services import audit
from app.services.projects import assert_can_see_project


async def _get_line_item_raw(session: AsyncSession, item_id: UUID) -> BoqLineItem:
    result = await session.execute(select(BoqLineItem).where(BoqLineItem.id == item_id))
    item = result.scalar_one_or_none()
    if item is None:
        raise NotFoundError(f"BOQ line item {item_id} not found")
    return item


async def create_line_item(
    session: AsyncSession, ctx: RequestContext, project_id: UUID, data: BoqLineItemCreate
) -> BoqLineItem:
    await assert_can_see_project(session, ctx, project_id)

    if data.parent_id is not None:
        parent = (
            await session.execute(
                select(BoqLineItem).where(BoqLineItem.id == data.parent_id, BoqLineItem.project_id == project_id)
            )
        ).scalar_one_or_none()
        if parent is None:
            raise ValidationAppError(f"parent_id {data.parent_id} is not a BOQ item in project {project_id}")

    item = BoqLineItem(
        tenant_id=ctx.tenant_id,
        project_id=project_id,
        parent_id=data.parent_id,
        item_no=data.item_no,
        description=data.description,
        uom=data.uom,
        boq_quantity=data.boq_quantity,
        trade_node_id=data.trade_node_id,
        sort_order=data.sort_order,
        path="placeholder",  # overwritten by the boq_line_items_path_trg trigger (migration 0011)
    )
    session.add(item)
    await session.flush()
    # path/level are computed by the boq_line_items_path_trg BEFORE INSERT
    # trigger (migration 0011); SQLAlchemy has no visibility into that
    # server-side write, so the ORM object still holds our "placeholder"
    # value until explicitly refreshed (same pattern as
    # app/services/taxonomy.py::create_node for trade_nodes).
    await session.refresh(item, attribute_names=["path", "level"])
    await audit.record(
        session, ctx, action=AuditAction.CREATE, entity_type="boq_line_item", entity_id=item.id,
        project_id=project_id, payload={"item_no": data.item_no, "description": data.description},
    )
    return item


async def _resolve_tolerance_pct(session: AsyncSession, project_id: UUID, trade_node_id: UUID | None) -> float:
    """Per-trade override (if the item has a trade_node_id and one exists
    for it) -> this project's own default (trade_node_id IS NULL row) ->
    the hard-coded global default (2.0%). Never raises -- an unconfigured
    project/trade always resolves to something usable."""
    if trade_node_id is not None:
        override = (
            await session.execute(
                select(BoqTolerance.tolerance_pct).where(
                    BoqTolerance.project_id == project_id, BoqTolerance.trade_node_id == trade_node_id
                )
            )
        ).scalar_one_or_none()
        if override is not None:
            return float(override)

    project_default = (
        await session.execute(
            select(BoqTolerance.tolerance_pct).where(
                BoqTolerance.project_id == project_id, BoqTolerance.trade_node_id.is_(None)
            )
        )
    ).scalar_one_or_none()
    if project_default is not None:
        return float(project_default)

    return DEFAULT_RECONCILIATION_CONFIG.tolerance_pct


async def _linked_measurements(session: AsyncSession, item_id: UUID) -> list[DrawingMeasurement]:
    result = await session.execute(
        select(DrawingMeasurement)
        .join(BoqLineItemMeasurement, BoqLineItemMeasurement.measurement_id == DrawingMeasurement.id)
        .where(BoqLineItemMeasurement.boq_line_item_id == item_id)
    )
    return list(result.scalars().all())


async def _apply_reconciliation(session: AsyncSession, item: BoqLineItem) -> None:
    """Recomputes and persists variance/discrepancy_class from item's
    *current* set of linked measurements (BoqLineItemMeasurement, summed
    via aggregate_measurement_values) and boq_quantity/uom -- shared by
    add_measurement_link()/remove_measurement_link() (the set changed),
    reconcile_item() (explicit re-run), and _refresh_if_stale() (lazy,
    on-read recompute)."""
    measurements = await _linked_measurements(session, item.id)

    if not measurements:
        measurement_value: float | None = None
        measurement_unit: str | None = None
        note_override: str | None = None
    else:
        aggregated = aggregate_measurement_values(
            item.uom, [(float(m.value), m.unit) for m in measurements]
        )
        if aggregated is None:
            measurement_value, measurement_unit = None, None
            note_override = "Linked measurements have incompatible units for this BOQ item's uom"
        else:
            measurement_value, measurement_unit = aggregated
            note_override = None

    tolerance_pct = await _resolve_tolerance_pct(session, item.project_id, item.trade_node_id)
    if note_override is not None:
        result = ReconciliationResult(DiscrepancyClass.UNMATCHED.value, None, None, note_override)
    else:
        result = reconcile(
            boq_quantity=float(item.boq_quantity) if item.boq_quantity is not None else None,
            boq_uom=item.uom,
            measurement_value=measurement_value,
            measurement_unit=measurement_unit,
            config=ReconciliationConfig(tolerance_pct=tolerance_pct),
        )
    item.variance = result.variance
    item.variance_pct = result.variance_pct
    item.discrepancy_class = result.discrepancy_class
    item.reconciliation_note = result.note
    item.reconciled_at = datetime.now(UTC)


async def _refresh_if_stale(session: AsyncSession, ctx: RequestContext, item: BoqLineItem) -> BoqLineItem:
    """Self-healing lazy refresh, called on every read (get/list).

    Under the many-to-one link model there's no single cheap signal (like
    a nullable FK flipping to NULL) that tells us the linked set changed
    since the last reconciliation -- a measurement being deleted just
    removes its BoqLineItemMeasurement row (ON DELETE CASCADE), and an
    updated measurement's `updated_at` would need comparing against
    *every* linked row's timestamp. Recomputing outright is about the same
    cost as checking for staleness would be, so this always recomputes
    (once the item has been reconciled at least once -- `reconciled_at is
    not None`) and only writes an audit event when the *classification*
    actually changed, to avoid an audit entry on every single read of an
    unchanged item.

    Only acts on items that have been reconciled at least once -- a
    freshly created, never-linked item intentionally stays at
    `discrepancy_class=None` until an estimator actually reconciles it;
    that's a different, meaningful state from "reconciled, then went
    stale", not something this should silently collapse into `unmatched`
    on the first read.

    Recomputing (and therefore flushing) on every read of a
    previously-reconciled item is a real cost for a genuinely "4,200+
    line" BOQ (the SRS's own AG Grid sizing note) listed all at once --
    worth batching/caching properly if that turns out to matter in
    practice, not attempted here.
    """
    if item.reconciled_at is None:
        return item

    previous_class = item.discrepancy_class
    await _apply_reconciliation(session, item)
    await session.flush()

    if item.discrepancy_class != previous_class:
        await audit.record(
            session, ctx, action=AuditAction.UPDATE, entity_type="boq_line_item", entity_id=item.id,
            project_id=item.project_id,
            payload={
                "auto_reconciled": True,
                "previous_discrepancy_class": previous_class,
                "discrepancy_class": item.discrepancy_class,
            },
        )
    return item


async def list_line_items(session: AsyncSession, ctx: RequestContext, project_id: UUID) -> list[BoqLineItem]:
    result = await session.execute(
        select(BoqLineItem).where(BoqLineItem.project_id == project_id).order_by(BoqLineItem.path)
    )
    items = list(result.scalars().all())
    return [await _refresh_if_stale(session, ctx, item) for item in items]


async def get_line_item(session: AsyncSession, ctx: RequestContext, item_id: UUID) -> BoqLineItem:
    item = await _get_line_item_raw(session, item_id)
    return await _refresh_if_stale(session, ctx, item)


def _raise_if_incompatible(item: BoqLineItem, measurement: DrawingMeasurement) -> None:
    if item.uom and not unit_conversion.convertible(item.uom, measurement.unit):
        # Reject at the point of the deliberate user action (immediate,
        # specific feedback) rather than silently accepting the link and
        # only surfacing the problem as "unmatched" later -- reconcile()
        # would classify this as unmatched regardless if it ever got
        # through (defense in depth), but a 422 here is a much clearer
        # signal that the estimator picked the wrong measurement.
        boq_dim = unit_conversion.unit_dimension(item.uom)
        measurement_dim = unit_conversion.unit_dimension(measurement.unit)
        raise ValidationAppError(
            f"Cannot link: BOQ uom {item.uom!r}"
            f"{f' ({boq_dim.value})' if boq_dim else ''} is not compatible with measurement unit "
            f"{measurement.unit!r}{f' ({measurement_dim.value})' if measurement_dim else ''}"
        )


async def add_measurement_link(
    session: AsyncSession, ctx: RequestContext, item_id: UUID, measurement_id: UUID
) -> BoqLineItem:
    item = await _get_line_item_raw(session, item_id)
    measurement = (
        await session.execute(select(DrawingMeasurement).where(DrawingMeasurement.id == measurement_id))
    ).scalar_one_or_none()
    if measurement is None:
        raise NotFoundError(f"Measurement {measurement_id} not found")
    if measurement.project_id != item.project_id:
        # Same defense-in-depth reasoning as the parent_id check in
        # migration 0011: WRITE_ROLES includes roles that bypass
        # project_members, so RLS visibility alone doesn't stop a
        # privileged actor from linking across projects by mistake.
        raise ValidationAppError("Cannot link a measurement from a different project")
    _raise_if_incompatible(item, measurement)

    existing = (
        await session.execute(
            select(BoqLineItemMeasurement).where(
                BoqLineItemMeasurement.boq_line_item_id == item_id,
                BoqLineItemMeasurement.measurement_id == measurement_id,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        session.add(
            BoqLineItemMeasurement(
                tenant_id=ctx.tenant_id, boq_line_item_id=item_id, measurement_id=measurement_id,
                project_id=item.project_id,
            )
        )
        # _apply_reconciliation's _linked_measurements() query must see
        # this new row -- without flushing first it wouldn't (the INSERT
        # is still pending in this session, not yet visible to a SELECT
        # run against the same connection), so reconciliation would run
        # one link behind on every add.
        await session.flush()

    await _apply_reconciliation(session, item)
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.UPDATE, entity_type="boq_line_item", entity_id=item.id,
        project_id=item.project_id,
        payload={"measurement_linked": str(measurement_id), "discrepancy_class": item.discrepancy_class},
    )
    return item


async def remove_measurement_link(
    session: AsyncSession, ctx: RequestContext, item_id: UUID, measurement_id: UUID
) -> BoqLineItem:
    item = await _get_line_item_raw(session, item_id)
    link = (
        await session.execute(
            select(BoqLineItemMeasurement).where(
                BoqLineItemMeasurement.boq_line_item_id == item_id,
                BoqLineItemMeasurement.measurement_id == measurement_id,
            )
        )
    ).scalar_one_or_none()
    if link is None:
        raise NotFoundError(f"Measurement {measurement_id} is not linked to BOQ item {item_id}")
    await session.delete(link)
    await session.flush()

    await _apply_reconciliation(session, item)
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.UPDATE, entity_type="boq_line_item", entity_id=item.id,
        project_id=item.project_id,
        payload={"measurement_unlinked": str(measurement_id), "discrepancy_class": item.discrepancy_class},
    )
    return item


async def list_measurement_links(session: AsyncSession, item_id: UUID) -> list[DrawingMeasurement]:
    await _get_line_item_raw(session, item_id)  # 404s if missing / not visible under RLS
    return await _linked_measurements(session, item_id)


async def reconcile_item(session: AsyncSession, ctx: RequestContext, item_id: UUID) -> BoqLineItem:
    item = await _get_line_item_raw(session, item_id)
    await _apply_reconciliation(session, item)
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.UPDATE, entity_type="boq_line_item", entity_id=item.id,
        project_id=item.project_id, payload={"reconciled": True, "discrepancy_class": item.discrepancy_class},
    )
    return item


async def delete_line_item(session: AsyncSession, ctx: RequestContext, item_id: UUID) -> None:
    item = await _get_line_item_raw(session, item_id)
    await session.delete(item)
    await audit.record(
        session, ctx, action=AuditAction.DELETE, entity_type="boq_line_item", entity_id=item_id,
        project_id=item.project_id, payload={"item_no": item.item_no},
    )


async def set_tolerance(
    session: AsyncSession, ctx: RequestContext, project_id: UUID, trade_node_id: UUID | None, tolerance_pct: float
) -> BoqTolerance:
    await assert_can_see_project(session, ctx, project_id)

    existing = (
        await session.execute(
            select(BoqTolerance).where(
                BoqTolerance.project_id == project_id,
                BoqTolerance.trade_node_id == trade_node_id if trade_node_id is not None else BoqTolerance.trade_node_id.is_(None),
            )
        )
    ).scalar_one_or_none()

    if existing is not None:
        existing.tolerance_pct = tolerance_pct
        row = existing
        action = AuditAction.UPDATE
    else:
        row = BoqTolerance(
            tenant_id=ctx.tenant_id, project_id=project_id, trade_node_id=trade_node_id, tolerance_pct=tolerance_pct
        )
        session.add(row)
        action = AuditAction.CREATE

    await session.flush()
    await audit.record(
        session, ctx, action=action, entity_type="boq_tolerance", entity_id=row.id, project_id=project_id,
        payload={"trade_node_id": str(trade_node_id) if trade_node_id else None, "tolerance_pct": tolerance_pct},
    )
    return row


async def list_tolerances(session: AsyncSession, project_id: UUID) -> list[BoqTolerance]:
    result = await session.execute(select(BoqTolerance).where(BoqTolerance.project_id == project_id))
    return list(result.scalars().all())


async def list_unlinked_measurements(
    session: AsyncSession, project_id: UUID, drawing_id: UUID | None = None
) -> list[DrawingMeasurement]:
    """Measurements in this project that no boq_line_item_measurements row
    references at all -- "possible missed scope": the AI takeoff found
    something no BOQ line item currently accounts for. The complement of
    app/api/v1/routes/drawings.py's GET .../measurements (which lists
    everything, linked or not).

    No trade filter here (unlike the ask this was scoped against) --
    drawing_measurements has no trade classification of its own (only
    boq_line_items does, via trade_node_id, for tolerance lookups -- see
    BoqTolerance), and a measurement with no BOQ line linking to it by
    definition can't inherit one from a line item either. Mapping an
    extractor `capability` (alignment/corridor_area/trench_prismoidal_
    volume/pipe_network_topology) to a trade would need a real convention
    this codebase doesn't have yet -- not invented here; see
    docs/boq-reconciliation.md.
    """
    linked_ids = select(BoqLineItemMeasurement.measurement_id)
    stmt = select(DrawingMeasurement).where(
        DrawingMeasurement.project_id == project_id, DrawingMeasurement.id.not_in(linked_ids)
    )
    if drawing_id is not None:
        stmt = stmt.where(DrawingMeasurement.drawing_id == drawing_id)
    result = await session.execute(stmt.order_by(DrawingMeasurement.drawing_id, DrawingMeasurement.sheet_id))
    return list(result.scalars().all())
