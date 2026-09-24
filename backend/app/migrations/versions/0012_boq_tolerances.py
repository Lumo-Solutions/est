"""Phase 3 fix: BOQ line items can carry a trade classification, and
reconciliation tolerance becomes configurable per project with optional
per-trade overrides (default 2%, unchanged, when no override exists).

Revision ID: 0012
Revises: 0011
Create Date: 2026-01-01 00:00:11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from app.db.ddl import enable_rls, tenant_policies

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

# Same role split as boq_line_items itself (migration 0011): setting a
# tolerance is a structural/configuration action, not day-to-day
# reconciliation work.
WRITE_ROLES = ["lead_estimator", "procurement_head", "managing_director"]
DELETE_ROLES = ["lead_estimator", "procurement_head", "managing_director"]


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
        "boq_line_items",
        sa.Column("trade_node_id", pg.UUID(as_uuid=True), sa.ForeignKey("trade_nodes.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_boq_line_items_trade_node_id", "boq_line_items", ["trade_node_id"])

    op.create_table(
        "boq_tolerances",
        *_entity_columns(),
        sa.Column("project_id", pg.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        # NULL = this project's own default (falls back further to
        # app.boq.reconciliation.DEFAULT_RECONCILIATION_CONFIG.tolerance_pct,
        # 2.0%, when no row exists for a project at all). Non-NULL =
        # override for that specific trade within this project.
        sa.Column("trade_node_id", pg.UUID(as_uuid=True), sa.ForeignKey("trade_nodes.id", ondelete="CASCADE"), nullable=True),
        sa.Column("tolerance_pct", sa.Numeric(6, 3), nullable=False),
    )
    # NULLS NOT DISTINCT (PG15+) so at most one project-default row
    # (trade_node_id IS NULL) can exist per project -- a plain
    # UniqueConstraint would let Postgres's default NULL-is-distinct
    # behavior silently allow duplicates for exactly the row that matters
    # most (the project-wide default).
    op.execute(
        "ALTER TABLE boq_tolerances ADD CONSTRAINT uq_boq_tolerances_project_trade "
        "UNIQUE NULLS NOT DISTINCT (project_id, trade_node_id);"
    )
    op.create_index("ix_boq_tolerances_tenant_id", "boq_tolerances", ["tenant_id"])
    op.create_index("ix_boq_tolerances_project_id", "boq_tolerances", ["project_id"])

    enable_rls(op, "boq_tolerances")
    tenant_policies(op, "boq_tolerances", write_roles=WRITE_ROLES, delete_roles=DELETE_ROLES, project_scoped=True)


def downgrade() -> None:
    op.drop_table("boq_tolerances")
    op.drop_index("ix_boq_line_items_trade_node_id", table_name="boq_line_items")
    op.drop_column("boq_line_items", "trade_node_id")
