"""Module E Phase 1: schema readiness -- contracts, BOQ/contract revisions
with lineage, live exclusion register, outturn cost observations.
Schema and RLS only, no workflow service logic here yet -- see
docs/module-e-schema-design.md."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Date, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TenantEntity


class Contract(TenantEntity):
    """A won BidSettlement becoming a live contract -- a thin anchor, not
    a duplicate of the settlement's own data: its BOQ lines and accepted
    vendor quotes stay reachable through settlement_id ->
    bid_settlement_line_items, never copied here."""

    __tablename__ = "contracts"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    settlement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bid_settlements.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    # Deferred, not trigger-assigned (unlike rfqs.rfq_ref) -- see migration
    # 0027's own comment for why.
    contract_ref: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="draft")
    awarded_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)


class BoqRevision(TenantEntity):
    __tablename__ = "boq_revisions"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    revision_no: Mapped[int] = mapped_column(nullable=False)
    parent_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boq_revisions.id", ondelete="SET NULL"), nullable=True
    )
    import_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boq_import_batches.id", ondelete="SET NULL"), nullable=True
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class ContractRevision(TenantEntity):
    __tablename__ = "contract_revisions"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    contract_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    revision_no: Mapped[int] = mapped_column(nullable=False)
    parent_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contract_revisions.id", ondelete="SET NULL"), nullable=True
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class ContractVariation(TenantEntity):
    __tablename__ = "contract_variations"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    contract_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    revision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contract_revisions.id", ondelete="RESTRICT"), nullable=False
    )
    variation_ref: Mapped[str | None] = mapped_column(String(32), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    delta_amount: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="proposed")


class ExclusionRegisterEntry(TenantEntity):
    """"Live" -- a contract-management screen reads from this table, not
    quotation_exclusion_flags directly; this row's own status tracks
    resolution independently of whatever happens to the originating flag,
    which Module C2 continues to own unmodified."""

    __tablename__ = "exclusion_register"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    contract_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contracts.id", ondelete="SET NULL"), nullable=True
    )
    source_exclusion_flag_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("quotation_exclusion_flags.id", ondelete="SET NULL"), nullable=True
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="open")
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)


class OutturnCostObservation(TenantEntity):
    """The provenance record a future write-back workflow will read and
    turn into a cost_item_rates row (source=RateSource.OUTTURN) via the
    existing app.services.costlib::record_rate() -- no schema change
    needed on cost_item_rates itself. written_back_rate_id is set once
    that (not-yet-built) workflow actually does so."""

    __tablename__ = "outturn_cost_observations"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    contract_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    boq_line_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boq_line_items.id", ondelete="SET NULL"), nullable=True
    )
    cost_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cost_items.id", ondelete="SET NULL"), nullable=True
    )
    observed_unit_cost: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    observed_quantity: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="AED")
    observed_at: Mapped[date] = mapped_column(Date, nullable=False)
    source_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    written_back_rate_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cost_item_rates.id", ondelete="SET NULL"), nullable=True
    )
