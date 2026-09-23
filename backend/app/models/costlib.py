from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Computed, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import DATERANGE, JSONB, TSTZRANGE, UUID
from sqlalchemy.dialects.postgresql.ranges import Range
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import CostItemType, RateComponentType, RateSource
from app.db.base import TenantEntity
from app.db.types import Money


class CostItem(TenantEntity):
    __tablename__ = "cost_items"

    code: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    long_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    uom: Mapped[str] = mapped_column(String(16), nullable=False)
    trade_node_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trade_nodes.id", ondelete="SET NULL"), nullable=True
    )
    item_type: Mapped[str] = mapped_column(String(16), nullable=False, server_default=CostItemType.MATERIAL.value)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    attributes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class CostItemRate(TenantEntity):
    """Bi-temporal rate row. Never UPDATEd in place: correcting history means
    closing sys_period on the old row and inserting a new one (see
    services/costlib.py::record_rate). A GiST exclusion constraint (created
    in the migration) prevents overlapping *currently-believed*
    (upper_inf(sys_period)) rates for the same (item, scope, currency)."""

    __tablename__ = "cost_item_rates"

    cost_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cost_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scope_key: Mapped[str] = mapped_column(String(128), nullable=False, server_default="GLOBAL")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="AED")
    total_rate: Mapped[float] = mapped_column(Money, nullable=False)
    valid_period: Mapped[Range[date]] = mapped_column(DATERANGE, nullable=False)
    sys_period: Mapped[Range[datetime]] = mapped_column(TSTZRANGE, nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False, server_default=RateSource.MANUAL.value)
    source_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cost_item_rates.id", ondelete="SET NULL"), nullable=True
    )


class CostRateComponent(TenantEntity):
    __tablename__ = "cost_rate_components"

    rate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cost_item_rates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    component_type: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=RateComponentType.MATERIAL.value
    )
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    resource_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    quantity_per_uom: Mapped[float] = mapped_column(Money, nullable=False, server_default="1")
    unit_cost: Mapped[float] = mapped_column(Money, nullable=False)
    waste_factor: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False, server_default="0")
    productivity: Mapped[float | None] = mapped_column(Money, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    amount: Mapped[float] = mapped_column(
        Money,
        Computed("quantity_per_uom * unit_cost * (1 + waste_factor)", persisted=True),
    )
