"""Module D1: bid settlement and margin simulation

Adds bid_settlements (versioned per project, like quotations),
bid_settlement_trade_overrides (sparse per-trade percentage overrides),
bid_settlement_line_items (one per included BOQ line item), and
bid_settlement_scenarios (named, non-authoritative saved simulate()
results). See docs/module-d1-plan.md for the full design.

Revision ID: 0019
Revises: 0018
Create Date: 2026-01-02 00:00:01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from app.db.ddl import enable_rls, tenant_policies

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

# bid_settlements/bid_settlement_trade_overrides: structural, drafted and
# revised by lead_estimator+ (matches quotations' own WRITE_ROLES, migration
# 0016) -- the header-level percentages and trade overrides are the same
# kind of decision as accepting a version, not day-to-day line costing.
HEADER_WRITE_ROLES = ["lead_estimator", "procurement_head", "bd_director", "managing_director"]
# bid_settlement_line_items/bid_settlement_scenarios: day-to-day estimating
# work (setting a line's cost/source, running a simulation) -- estimator+,
# matching BOQ's own operational write policy (migration 0009/0013/0014).
LINE_WRITE_ROLES = ["estimator", "lead_estimator", "procurement_head", "bd_director", "managing_director"]


def _entity_columns() -> list[sa.Column]:
    return [
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", pg.UUID(as_uuid=True), nullable=True),
    ]


def upgrade() -> None:
    # ------------------------------------------------------------------
    # bid_settlements
    # ------------------------------------------------------------------
    op.create_table(
        "bid_settlements",
        *_entity_columns(),
        sa.Column("project_id", pg.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_no", sa.Integer, nullable=False, server_default="1"),
        sa.Column("is_current", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="AED"),
        sa.Column("default_plant_pct", sa.Numeric(6, 4), nullable=False, server_default="0"),
        sa.Column("default_overhead_pct", sa.Numeric(6, 4), nullable=False, server_default="0"),
        sa.Column("default_volatility_pct", sa.Numeric(6, 4), nullable=False, server_default="0"),
        sa.Column("default_markup_pct", sa.Numeric(6, 4), nullable=False, server_default="0"),
        sa.Column("direct_cost_total", sa.Numeric(18, 2), nullable=True),
        sa.Column("plant_total", sa.Numeric(18, 2), nullable=True),
        sa.Column("overhead_total", sa.Numeric(18, 2), nullable=True),
        sa.Column("volatility_total", sa.Numeric(18, 2), nullable=True),
        sa.Column("markup_total", sa.Numeric(18, 2), nullable=True),
        sa.Column("tender_total", sa.Numeric(18, 2), nullable=True),
        sa.Column("rounding_difference", sa.Numeric(18, 2), nullable=True),
        sa.Column("margin_on_sell_pct", sa.Numeric(6, 3), nullable=True),
        sa.Column("approval_request_id", pg.UUID(as_uuid=True), sa.ForeignKey("approval_requests.id", ondelete="SET NULL"), nullable=True),
        sa.Column("quantities_refreshed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("submitted_by", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("decided_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("decided_by", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("outcome", sa.String(8), nullable=True),
        sa.Column("outcome_our_price", sa.Numeric(18, 2), nullable=True),
        sa.Column("outcome_winning_price", sa.Numeric(18, 2), nullable=True),
        sa.Column("outcome_competitor_names", pg.ARRAY(sa.Text), nullable=False, server_default="{}"),
        sa.Column("outcome_reason_codes", pg.ARRAY(sa.Text), nullable=False, server_default="{}"),
        sa.Column("outcome_recorded_by", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("outcome_recorded_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("outcome_note", sa.Text, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.UniqueConstraint("project_id", "version_no", name="uq_bid_settlements_project_version"),
    )
    op.create_index("ix_bid_settlements_tenant_id", "bid_settlements", ["tenant_id"])
    op.create_index("ix_bid_settlements_project_id", "bid_settlements", ["project_id"])
    # Exactly one "current" version per project -- same pattern as
    # quotations' uq_quotations_current_per_rfq_vendor (migration 0016).
    op.execute(
        "CREATE UNIQUE INDEX uq_bid_settlements_current_per_project ON bid_settlements (project_id) WHERE is_current;"
    )
    enable_rls(op, "bid_settlements")
    tenant_policies(op, "bid_settlements", write_roles=HEADER_WRITE_ROLES, project_scoped=True)

    # ------------------------------------------------------------------
    # bid_settlement_trade_overrides
    # ------------------------------------------------------------------
    op.create_table(
        "bid_settlement_trade_overrides",
        *_entity_columns(),
        sa.Column("settlement_id", pg.UUID(as_uuid=True), sa.ForeignKey("bid_settlements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", pg.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("trade_node_id", pg.UUID(as_uuid=True), sa.ForeignKey("trade_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plant_pct", sa.Numeric(6, 4), nullable=True),
        sa.Column("overhead_pct", sa.Numeric(6, 4), nullable=True),
        sa.Column("volatility_pct", sa.Numeric(6, 4), nullable=True),
        sa.Column("markup_pct", sa.Numeric(6, 4), nullable=True),
        sa.UniqueConstraint("settlement_id", "trade_node_id", name="uq_bid_settlement_trade_overrides_pair"),
    )
    op.create_index("ix_bid_settlement_trade_overrides_tenant_id", "bid_settlement_trade_overrides", ["tenant_id"])
    op.create_index("ix_bid_settlement_trade_overrides_settlement_id", "bid_settlement_trade_overrides", ["settlement_id"])
    op.create_index("ix_bid_settlement_trade_overrides_project_id", "bid_settlement_trade_overrides", ["project_id"])
    op.create_index("ix_bid_settlement_trade_overrides_trade_node_id", "bid_settlement_trade_overrides", ["trade_node_id"])
    enable_rls(op, "bid_settlement_trade_overrides")
    tenant_policies(op, "bid_settlement_trade_overrides", write_roles=HEADER_WRITE_ROLES, project_scoped=True)

    # ------------------------------------------------------------------
    # bid_settlement_line_items
    # ------------------------------------------------------------------
    op.create_table(
        "bid_settlement_line_items",
        *_entity_columns(),
        sa.Column("settlement_id", pg.UUID(as_uuid=True), sa.ForeignKey("bid_settlements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("boq_line_item_id", pg.UUID(as_uuid=True), sa.ForeignKey("boq_line_items.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("project_id", pg.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("quantity_at_build", sa.Numeric(18, 4), nullable=False),
        sa.Column("direct_unit_cost", sa.Numeric(14, 4), nullable=True),
        sa.Column("source_currency", sa.String(3), nullable=False, server_default="AED"),
        sa.Column("cost_source", sa.String(16), nullable=False, server_default="manual"),
        sa.Column("source_quotation_line_item_id", pg.UUID(as_uuid=True), sa.ForeignKey("quotation_line_items.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_cost_item_rate_id", pg.UUID(as_uuid=True), sa.ForeignKey("cost_item_rates.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_rate_as_of_date", sa.Date, nullable=True),
        sa.Column("source_set_by", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("source_set_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("source_note", sa.Text, nullable=True),
        sa.Column("fx_rate", sa.Numeric(14, 6), nullable=True),
        sa.Column("fx_rate_date", sa.Date, nullable=True),
        sa.Column("fx_recorded_by", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("plant_pct_override", sa.Numeric(6, 4), nullable=True),
        sa.Column("overhead_pct_override", sa.Numeric(6, 4), nullable=True),
        sa.Column("volatility_pct_override", sa.Numeric(6, 4), nullable=True),
        sa.Column("markup_pct_override", sa.Numeric(6, 4), nullable=True),
        sa.Column("unit_sell_rate", sa.Numeric(14, 2), nullable=True),
        sa.Column("line_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("line_note", sa.Text, nullable=True),
        sa.UniqueConstraint("settlement_id", "boq_line_item_id", name="uq_bid_settlement_line_items_pair"),
    )
    op.create_index("ix_bid_settlement_line_items_tenant_id", "bid_settlement_line_items", ["tenant_id"])
    op.create_index("ix_bid_settlement_line_items_settlement_id", "bid_settlement_line_items", ["settlement_id"])
    op.create_index("ix_bid_settlement_line_items_boq_line_item_id", "bid_settlement_line_items", ["boq_line_item_id"])
    op.create_index("ix_bid_settlement_line_items_project_id", "bid_settlement_line_items", ["project_id"])
    enable_rls(op, "bid_settlement_line_items")
    tenant_policies(op, "bid_settlement_line_items", write_roles=LINE_WRITE_ROLES, project_scoped=True)

    # ------------------------------------------------------------------
    # bid_settlement_scenarios
    # ------------------------------------------------------------------
    op.create_table(
        "bid_settlement_scenarios",
        *_entity_columns(),
        sa.Column("settlement_id", pg.UUID(as_uuid=True), sa.ForeignKey("bid_settlements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", pg.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("inputs", pg.JSONB, nullable=False),
        sa.Column("result", pg.JSONB, nullable=False),
    )
    op.create_index("ix_bid_settlement_scenarios_tenant_id", "bid_settlement_scenarios", ["tenant_id"])
    op.create_index("ix_bid_settlement_scenarios_settlement_id", "bid_settlement_scenarios", ["settlement_id"])
    op.create_index("ix_bid_settlement_scenarios_project_id", "bid_settlement_scenarios", ["project_id"])
    enable_rls(op, "bid_settlement_scenarios")
    tenant_policies(op, "bid_settlement_scenarios", write_roles=LINE_WRITE_ROLES, project_scoped=True)


def downgrade() -> None:
    op.drop_table("bid_settlement_scenarios")
    op.drop_table("bid_settlement_line_items")
    op.drop_table("bid_settlement_trade_overrides")
    op.execute("DROP INDEX IF EXISTS uq_bid_settlements_current_per_project;")
    op.drop_table("bid_settlements")
