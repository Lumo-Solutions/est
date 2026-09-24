from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import TenantEntity
from app.db.types import Ltree


class BoqLineItem(TenantEntity):
    """Hierarchical tender BOQ line item (Phase 3), reconciled against the
    Phase 2 geometry extractors' output (drawing_measurements) via
    app/boq/reconciliation.py. path/level/sort_order follow the same ltree
    pattern as TradeNode (app/models/taxonomy.py), scoped by project_id
    instead of tenant_id -- see migration 0011's trigger for why that
    scoping has to be explicit rather than relying on RLS alone."""

    __tablename__ = "boq_line_items"
    __table_args__ = (
        UniqueConstraint("project_id", "parent_id", "item_no", name="uq_boq_line_items_project_parent_item_no"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boq_line_items.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    item_no: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    uom: Mapped[str | None] = mapped_column(String(16), nullable=True)
    boq_quantity: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    level: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    path: Mapped[str] = mapped_column(Ltree, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    # Optional trade classification (app.models.taxonomy.TradeNode), used
    # only to look up a per-trade tolerance override -- see BoqTolerance.
    trade_node_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trade_nodes.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Linked measurements live in BoqLineItemMeasurement (many-to-one,
    # migration 0013 -- one BOQ line can aggregate several measurements,
    # e.g. a pipe run's length summed across several sheets). Reconciliation
    # *state* (variance/discrepancy_class/...) lives in
    # BoqLineItemReconciliation (migration 0014), a separate table with its
    # own, looser (estimator+) write policy -- boq_line_items' own
    # WRITE_ROLES is lead_estimator+ (structural edits), and reconciling is
    # normal, frequent estimating work that must not require that role. See
    # migration 0014's docstring for the RLS bug this split fixes. The
    # properties below make that split invisible to callers (BoqLineItemOut
    # still reads item.variance etc. via plain attribute access).
    reconciliation: Mapped["BoqLineItemReconciliation | None"] = relationship(
        "BoqLineItemReconciliation", uselist=False, lazy="joined",
    )

    @property
    def variance(self) -> float | None:
        return self.reconciliation.variance if self.reconciliation else None

    @property
    def variance_pct(self) -> float | None:
        return self.reconciliation.variance_pct if self.reconciliation else None

    @property
    def discrepancy_class(self) -> str | None:
        return self.reconciliation.discrepancy_class if self.reconciliation else None

    @property
    def reconciliation_note(self) -> str | None:
        return self.reconciliation.reconciliation_note if self.reconciliation else None

    @property
    def reconciled_at(self) -> datetime | None:
        return self.reconciliation.reconciled_at if self.reconciliation else None


class BoqLineItemReconciliation(TenantEntity):
    """One row per boq_line_items row that has ever been reconciled
    (created lazily on first link/reconcile -- see app/services/boq.py::
    _apply_reconciliation) -- 1:1, but kept as its own table rather than
    columns on boq_line_items specifically so its RLS write policy can be
    estimator+ (operational) while boq_line_items' own stays lead_estimator+
    (structural). See migration 0014's docstring for the bug this fixes."""

    __tablename__ = "boq_line_item_reconciliation"
    __table_args__ = (UniqueConstraint("boq_line_item_id", name="uq_boq_line_item_reconciliation_item"),)

    boq_line_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boq_line_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    variance: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    variance_pct: Mapped[float | None] = mapped_column(Numeric(8, 3), nullable=True)
    discrepancy_class: Mapped[str | None] = mapped_column(String(16), nullable=True)
    reconciliation_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reconciled_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)


class BoqLineItemMeasurement(TenantEntity):
    """Join row: one drawing_measurements row linked to one boq_line_items
    row. Many-to-one from the BOQ side (a line item can link several
    measurements, summed by app/boq/reconciliation.py); a given
    measurement could in principle be linked from more than one BOQ line
    too (not deduplicated against -- e.g. a shared structure genuinely
    priced under two different line items), nothing here prevents that."""

    __tablename__ = "boq_line_item_measurements"
    __table_args__ = (
        UniqueConstraint("boq_line_item_id", "measurement_id", name="uq_boq_line_item_measurements_pair"),
    )

    boq_line_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boq_line_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    measurement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("drawing_measurements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )


class BoqTolerance(TenantEntity):
    """Per-project (trade_node_id NULL) or per-project-per-trade
    (trade_node_id set) reconciliation tolerance override. Falls back to
    app.boq.reconciliation.DEFAULT_RECONCILIATION_CONFIG.tolerance_pct
    (2.0%) when no row matches at all -- see
    app/services/boq.py::_resolve_tolerance_pct()."""

    __tablename__ = "boq_tolerances"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "trade_node_id", name="uq_boq_tolerances_project_trade",
            # NULLS NOT DISTINCT is set at the DB level in migration 0012
            # (op.execute, not representable via SQLAlchemy's
            # UniqueConstraint on this project's SQLAlchemy version) --
            # this ORM-level constraint exists for metadata/reflection
            # consistency, the migration's raw SQL is what's actually
            # enforced.
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    trade_node_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trade_nodes.id", ondelete="CASCADE"), nullable=True
    )
    tolerance_pct: Mapped[float] = mapped_column(Numeric(6, 3), nullable=False)
