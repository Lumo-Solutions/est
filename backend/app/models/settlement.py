"""Module D1: bid settlement and margin simulation.

See docs/module-d1-plan.md for the full design (schema rationale, the
per-line formula, the rates-are-authoritative rounding rule, the status
lifecycle, and the worked example). Summary:

- BidSettlement consolidates a whole project's accepted procurement quotes
  plus manually/cost-library-costed BOQ items into one traceable settled
  bid, versioned like Quotation (never mutated once submitted; a revision
  is a new version_no).
- BidSettlementTradeOverride and the four *_pct_override columns on
  BidSettlementLineItem implement the line > trade > project-default
  percentage resolution cascade (app/services/settlement.py::resolve_pct).
- unit_sell_rate/line_amount are only ever set at submit time and are never
  adjusted afterwards for rounding -- rates are authoritative (§4 of the
  plan). tender_total = Σ line_amount is the one number approvals/exports
  ever see; rounding_difference is kept purely for audit.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import ARRAY, Boolean, Date, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import BidSettlementStatus, SettlementCostSource
from app.db.base import TenantEntity


class BidSettlement(TenantEntity):
    __tablename__ = "bid_settlements"
    __table_args__ = (UniqueConstraint("project_id", "version_no", name="uq_bid_settlements_project_version"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_no: Mapped[int] = mapped_column(nullable=False, server_default="1")
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=BidSettlementStatus.DRAFT.value)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="AED")

    default_plant_pct: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False, server_default="0")
    default_overhead_pct: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False, server_default="0")
    default_volatility_pct: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False, server_default="0")
    default_markup_pct: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False, server_default="0")

    # Populated only at submit (snapshot) -- see app/services/settlement.py::submit_settlement.
    direct_cost_total: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    plant_total: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    overhead_total: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    volatility_total: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    markup_total: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    tender_total: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    rounding_difference: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    margin_on_sell_pct: Mapped[float | None] = mapped_column(Numeric(6, 3), nullable=True)

    approval_request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("approval_requests.id", ondelete="SET NULL"), nullable=True
    )
    quantities_refreshed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # D2 outcome capture -- columns exist now so this schema needs no later ALTER.
    outcome: Mapped[str | None] = mapped_column(String(8), nullable=True)
    outcome_our_price: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    outcome_winning_price: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    outcome_competitor_names: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    # Module D2: an optional structured link alongside the free-text names
    # above, for a competitor who happens to be a known Vendor row.
    outcome_competitor_vendor_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, server_default="{}"
    )
    outcome_reason_codes: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    outcome_recorded_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    outcome_recorded_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    outcome_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class BidSettlementTradeOverride(TenantEntity):
    __tablename__ = "bid_settlement_trade_overrides"
    __table_args__ = (
        UniqueConstraint("settlement_id", "trade_node_id", name="uq_bid_settlement_trade_overrides_pair"),
    )

    settlement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bid_settlements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Denormalized from bid_settlements.project_id purely for RLS's
    # app_can_see_project() clause -- same pattern as QuotationLineItem's
    # own project_id (app/models/quotation_ingestion.py).
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    trade_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trade_nodes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    plant_pct: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)
    overhead_pct: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)
    volatility_pct: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)
    markup_pct: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)


class BidSettlementLineItem(TenantEntity):
    __tablename__ = "bid_settlement_line_items"
    __table_args__ = (UniqueConstraint("settlement_id", "boq_line_item_id", name="uq_bid_settlement_line_items_pair"),)

    settlement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bid_settlements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    boq_line_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boq_line_items.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # quantity is refreshable pre-submit (app/services/settlement.py::
    # refresh_quantities); quantity_at_build never changes after the line is
    # first created, so a diff against the live BOQ is always reconstructable.
    quantity: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    quantity_at_build: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)

    direct_unit_cost: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    source_currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="AED")
    cost_source: Mapped[str] = mapped_column(String(16), nullable=False, server_default=SettlementCostSource.MANUAL.value)
    source_quotation_line_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("quotation_line_items.id", ondelete="SET NULL"), nullable=True
    )
    source_cost_item_rate_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cost_item_rates.id", ondelete="SET NULL"), nullable=True
    )
    source_rate_as_of_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_set_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    source_set_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    source_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    fx_rate: Mapped[float | None] = mapped_column(Numeric(14, 6), nullable=True)
    fx_rate_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    fx_recorded_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    plant_pct_override: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)
    overhead_pct_override: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)
    volatility_pct_override: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)
    markup_pct_override: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)

    # Populated only at submit (snapshot) -- rates are authoritative (§4):
    # never adjusted after the fact for rounding. line_amount is always
    # exactly round(unit_sell_rate * quantity, 2), no exceptions.
    unit_sell_rate: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    line_amount: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)

    line_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class BidSettlementScenario(TenantEntity):
    """A named, saved simulate() result for side-by-side comparison --
    never authoritative, never read by submit(). Purely a UI convenience."""

    __tablename__ = "bid_settlement_scenarios"

    settlement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bid_settlements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    inputs: Mapped[dict] = mapped_column(JSONB, nullable=False)
    result: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # created_by -- who saved this scenario -- is TenantEntity's own
    # ActorStampMixin column; no separate field needed.


class SettlementReasonCode(TenantEntity):
    """Module D2 win/loss capture: a tenant-configurable reason code list
    (price/technical/relationship/timeline/scope/other, seeded by
    app.cli seed), not a hardcoded Python enum -- per the build brief's
    standing constraint that configurable values live in the DB. Validated
    against by app/services/settlement.py::record_outcome."""

    __tablename__ = "settlement_reason_codes"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_settlement_reason_codes_tenant_code"),)

    code: Mapped[str] = mapped_column(String(32), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
