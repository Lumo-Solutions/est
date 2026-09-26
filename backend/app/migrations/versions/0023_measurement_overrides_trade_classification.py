"""Module B Phase 4b: non-destructive measurement overrides, traceability
bbox, trade classification of measurements

Adds:
- drawing_measurement_overrides -- one row per override *event* (never
  deleted, only reverted via reverted_by/reverted_at -- the row itself is
  the audit trail). At most one ACTIVE row (reverted_at IS NULL) per
  measurement, enforced by a partial unique index, same technique as
  bid_settlements' one-current-version index (migration 0019).
  Deliberately its own table with a looser (estimator+) write policy than
  drawing_measurements' own extractor-owned one -- same reasoning as
  boq_line_item_reconciliation's split off boq_line_items (migration
  0014): an override is normal, frequent estimating work, not a
  structural change to how a measurement was computed.
- drawing_measurements.trade_node_id (nullable FK) + bbox_min_x/min_y/
  max_x/max_y (nullable, denormalized union of its source entities'
  boxes) -- NOT a separate source_sheet_id column: drawing_measurements
  already has sheet_id, which is exactly "which sheet this measurement's
  source geometry lives on" (every extractor computes one measurement per
  sheet already), so no second FK is added even though the plan doc
  mentions one -- see docs/build-log.md's Phase 4b section for why.
- drawing_layer_trade_mappings -- project-scoped, ordered-by-nothing (a
  layer_pattern is either a substring match or it isn't; unlike PDF layer
  rules there's no color/width tiebreak needed) mapping from a
  case-insensitive layer-name substring to a trade_node_id, resolved at
  measurement creation/recompute time. Config-CRUD write policy
  (lead_estimator+) mirrors boq_tolerances' own (migration 0012), not
  drawing_measurements' extractor-owned one or overrides' estimator+ one.

Revision ID: 0023
Revises: 0022
Create Date: 2026-01-06 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from app.db.ddl import enable_rls, tenant_policies

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None

# Overriding a measurement is normal, frequent estimating work -- same
# role set as drawing_measurements' own WRITE_ROLES (migration 0010) and
# every other Module B operational action.
OVERRIDE_WRITE_ROLES = ["estimator", "lead_estimator", "procurement_head", "bd_director", "managing_director"]
# Config CRUD (which layer maps to which trade) is a structural/admin
# action -- same role set as boq_tolerances (migration 0012), not the
# operational estimator+ set above.
TRADE_MAPPING_WRITE_ROLES = ["lead_estimator", "procurement_head", "managing_director"]


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
    op.add_column(
        "drawing_measurements",
        sa.Column("trade_node_id", pg.UUID(as_uuid=True), sa.ForeignKey("trade_nodes.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_drawing_measurements_trade_node_id", "drawing_measurements", ["trade_node_id"])
    for col in ("bbox_min_x", "bbox_min_y", "bbox_max_x", "bbox_max_y"):
        op.add_column("drawing_measurements", sa.Column(col, sa.Numeric(18, 6), nullable=True))

    op.create_table(
        "drawing_measurement_overrides",
        *_entity_columns(),
        sa.Column("measurement_id", pg.UUID(as_uuid=True), sa.ForeignKey("drawing_measurements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", pg.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("value", sa.Numeric(18, 6), nullable=False),
        sa.Column("unit", sa.String(16), nullable=False),
        sa.Column("note", sa.Text, nullable=False),
        sa.Column("overridden_by", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("overridden_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("reverted_by", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("reverted_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_drawing_measurement_overrides_tenant_id", "drawing_measurement_overrides", ["tenant_id"])
    op.create_index("ix_drawing_measurement_overrides_project_id", "drawing_measurement_overrides", ["project_id"])
    op.create_index("ix_drawing_measurement_overrides_measurement_id", "drawing_measurement_overrides", ["measurement_id"])
    op.execute(
        "CREATE UNIQUE INDEX uq_drawing_measurement_overrides_active "
        "ON drawing_measurement_overrides (measurement_id) WHERE reverted_at IS NULL;"
    )
    enable_rls(op, "drawing_measurement_overrides")
    tenant_policies(op, "drawing_measurement_overrides", write_roles=OVERRIDE_WRITE_ROLES, project_scoped=True)

    op.create_table(
        "drawing_layer_trade_mappings",
        *_entity_columns(),
        sa.Column("project_id", pg.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("layer_pattern", sa.String(128), nullable=False),
        sa.Column("trade_node_id", pg.UUID(as_uuid=True), sa.ForeignKey("trade_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("project_id", "layer_pattern", name="uq_drawing_layer_trade_mappings_project_pattern"),
    )
    op.create_index("ix_drawing_layer_trade_mappings_tenant_id", "drawing_layer_trade_mappings", ["tenant_id"])
    op.create_index("ix_drawing_layer_trade_mappings_project_id", "drawing_layer_trade_mappings", ["project_id"])
    enable_rls(op, "drawing_layer_trade_mappings")
    tenant_policies(op, "drawing_layer_trade_mappings", write_roles=TRADE_MAPPING_WRITE_ROLES, delete_roles=TRADE_MAPPING_WRITE_ROLES, project_scoped=True)


def downgrade() -> None:
    op.drop_table("drawing_layer_trade_mappings")
    op.drop_table("drawing_measurement_overrides")
    for col in ("bbox_max_y", "bbox_max_x", "bbox_min_y", "bbox_min_x"):
        op.drop_column("drawing_measurements", col)
    op.drop_index("ix_drawing_measurements_trade_node_id", table_name="drawing_measurements")
    op.drop_column("drawing_measurements", "trade_node_id")
