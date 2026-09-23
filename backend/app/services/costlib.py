from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql.ranges import Range
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import RequestContext
from app.core.enums import AuditAction
from app.core.errors import NotFoundError
from app.models.costlib import CostItem, CostItemRate, CostRateComponent
from app.schemas.costlib import CostItemCreate, RecordRateRequest
from app.services import audit


async def create_cost_item(session: AsyncSession, ctx: RequestContext, data: CostItemCreate) -> CostItem:
    item = CostItem(
        tenant_id=ctx.tenant_id,
        code=data.code,
        description=data.description,
        long_description=data.long_description,
        uom=data.uom,
        trade_node_id=data.trade_node_id,
        item_type=data.item_type,
        attributes=data.attributes,
    )
    session.add(item)
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.CREATE, entity_type="cost_item", entity_id=item.id,
        payload={"code": item.code},
    )
    return item


async def get_cost_item(session: AsyncSession, cost_item_id: UUID) -> CostItem:
    result = await session.execute(select(CostItem).where(CostItem.id == cost_item_id))
    item = result.scalar_one_or_none()
    if item is None:
        raise NotFoundError(f"Cost item {cost_item_id} not found")
    return item


async def record_rate(
    session: AsyncSession, ctx: RequestContext, cost_item_id: UUID, data: RecordRateRequest
) -> CostItemRate:
    """Bi-temporal write: never UPDATEs an existing rate. Closes the
    sys_period of whatever rate is currently believed-current for this
    (item, scope, currency, valid_period-overlap) and inserts a fresh row
    with sys_period=[now, inf). The GiST exclusion constraint (migration
    0007) guarantees no two "currently believed" rows overlap in valid_period
    for the same key."""
    await get_cost_item(session, cost_item_id)  # 404s if missing

    now = datetime.now(timezone.utc)
    total_rate = sum(c.quantity_per_uom * c.unit_cost * (1 + c.waste_factor) for c in data.components)

    superseded = await session.execute(
        text(
            "SELECT id FROM cost_item_rates WHERE tenant_id = :t AND cost_item_id = :i "
            "AND scope_key = :s AND currency = :c AND valid_period && daterange(:vf, :vt) "
            "AND upper_inf(sys_period)"
        ),
        {
            "t": str(ctx.tenant_id), "i": str(cost_item_id), "s": data.scope_key, "c": data.currency,
            "vf": data.valid_from, "vt": data.valid_to,
        },
    )
    superseded_ids = [row[0] for row in superseded.all()]
    if superseded_ids:
        await session.execute(
            text("UPDATE cost_item_rates SET sys_period = tstzrange(lower(sys_period), :now) WHERE id = ANY(:ids)"),
            {"now": now, "ids": superseded_ids},
        )

    new_rate = CostItemRate(
        tenant_id=ctx.tenant_id,
        cost_item_id=cost_item_id,
        scope_key=data.scope_key,
        currency=data.currency,
        total_rate=total_rate,
        valid_period=Range(lower=data.valid_from, upper=data.valid_to),
        sys_period=Range(lower=now, upper=None),
        source=data.source,
        source_ref=data.source_ref,
        confidence=data.confidence,
    )
    session.add(new_rate)
    await session.flush()

    for component in data.components:
        session.add(
            CostRateComponent(
                tenant_id=ctx.tenant_id,
                rate_id=new_rate.id,
                component_type=component.component_type,
                description=component.description,
                resource_code=component.resource_code,
                quantity_per_uom=component.quantity_per_uom,
                unit_cost=component.unit_cost,
                waste_factor=component.waste_factor,
                productivity=component.productivity,
                sort_order=component.sort_order,
            )
        )

    if superseded_ids:
        await session.execute(
            text("UPDATE cost_item_rates SET superseded_by_id = :new WHERE id = ANY(:ids)"),
            {"new": str(new_rate.id), "ids": superseded_ids},
        )

    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.CREATE, entity_type="cost_item_rate", entity_id=new_rate.id,
        payload={"cost_item_id": str(cost_item_id), "total_rate": float(total_rate), "superseded": len(superseded_ids)},
    )
    return new_rate


async def get_rate_as_of(
    session: AsyncSession, ctx: RequestContext, cost_item_id: UUID, *, valid_on: date, known_at: datetime | None = None,
    scope_key: str = "GLOBAL",
) -> CostItemRate | None:
    """A-10 historical reconstruction: what rate was believed correct for
    `valid_on` as of `known_at` (defaults to now -- i.e. the current belief)."""
    result = await session.execute(
        text(
            "SELECT * FROM costlib_rate_as_of(:t, :i, :s, :vo, :ka)"
        ),
        {
            "t": str(ctx.tenant_id), "i": str(cost_item_id), "s": scope_key,
            "vo": valid_on, "ka": known_at or datetime.now(timezone.utc),
        },
    )
    row = result.mappings().first()
    if row is None:
        return None
    rate_result = await session.execute(select(CostItemRate).where(CostItemRate.id == row["id"]))
    await audit.record(
        session, ctx, action=AuditAction.READ, entity_type="cost_item_rate", entity_id=row["id"],
        payload={"valid_on": valid_on.isoformat()},
    )
    return rate_result.scalar_one()


async def list_components(session: AsyncSession, rate_id: UUID) -> list[CostRateComponent]:
    result = await session.execute(
        select(CostRateComponent).where(CostRateComponent.rate_id == rate_id).order_by(CostRateComponent.sort_order)
    )
    return list(result.scalars().all())
