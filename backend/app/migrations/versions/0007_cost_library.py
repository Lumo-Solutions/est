"""master cost library: bi-temporal component-level unit rates

Revision ID: 0007
Revises: 0006
Create Date: 2026-01-01 00:00:06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from app.db.ddl import enable_rls, tenant_policies

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

WRITE_ROLES = ["lead_estimator", "procurement_head", "managing_director"]


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
    op.create_table(
        "cost_items",
        *_entity_columns(),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("long_description", sa.Text, nullable=True),
        sa.Column("uom", sa.String(16), nullable=False),
        sa.Column("trade_node_id", pg.UUID(as_uuid=True), sa.ForeignKey("trade_nodes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("item_type", sa.String(16), nullable=False, server_default="material"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("attributes", pg.JSONB, nullable=True),
        sa.UniqueConstraint("tenant_id", "code", name="uq_cost_items_tenant_code"),
    )
    op.create_index("ix_cost_items_tenant_id", "cost_items", ["tenant_id"])
    op.execute("CREATE INDEX ix_cost_items_description_trgm ON cost_items USING gin (description gin_trgm_ops);")

    op.create_table(
        "cost_item_rates",
        *_entity_columns(),
        sa.Column("cost_item_id", pg.UUID(as_uuid=True), sa.ForeignKey("cost_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scope_key", sa.String(128), nullable=False, server_default="GLOBAL"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="AED"),
        sa.Column("total_rate", sa.Numeric(18, 6), nullable=False),
        sa.Column("valid_period", pg.DATERANGE, nullable=False),
        sa.Column("sys_period", pg.TSTZRANGE, nullable=False, server_default=sa.text("tstzrange(now(), null)")),
        sa.Column("source", sa.String(16), nullable=False, server_default="manual"),
        sa.Column("source_ref", sa.String(255), nullable=True),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("superseded_by_id", pg.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_cost_item_rates_superseded_by_id", "cost_item_rates", "cost_item_rates",
        ["superseded_by_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_cost_item_rates_tenant_id", "cost_item_rates", ["tenant_id"])
    op.create_index("ix_cost_item_rates_cost_item_id", "cost_item_rates", ["cost_item_id"])
    op.execute("CREATE INDEX ix_cost_item_rates_valid_period ON cost_item_rates USING gist (valid_period);")
    op.execute("CREATE INDEX ix_cost_item_rates_sys_period ON cost_item_rates USING gist (sys_period);")
    op.execute(
        "CREATE INDEX ix_cost_item_rates_current ON cost_item_rates (tenant_id, cost_item_id) "
        "WHERE upper_inf(sys_period);"
    )
    op.execute(
        "ALTER TABLE cost_item_rates ADD CONSTRAINT ex_cost_item_rates_no_overlap "
        "EXCLUDE USING gist ("
        "  tenant_id WITH =, "
        "  cost_item_id WITH =, "
        "  scope_key WITH =, "
        "  currency WITH =, "
        "  valid_period WITH &&"
        ") WHERE (upper_inf(sys_period));"
    )

    op.create_table(
        "cost_rate_components",
        *_entity_columns(),
        sa.Column("rate_id", pg.UUID(as_uuid=True), sa.ForeignKey("cost_item_rates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("component_type", sa.String(16), nullable=False, server_default="material"),
        sa.Column("description", sa.String(255), nullable=False),
        sa.Column("resource_code", sa.String(64), nullable=True),
        sa.Column("quantity_per_uom", sa.Numeric(18, 6), nullable=False, server_default="1"),
        sa.Column("unit_cost", sa.Numeric(18, 6), nullable=False),
        sa.Column("waste_factor", sa.Numeric(6, 4), nullable=False, server_default="0"),
        sa.Column("productivity", sa.Numeric(18, 6), nullable=True),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "amount", sa.Numeric(18, 6),
            sa.Computed("quantity_per_uom * unit_cost * (1 + waste_factor)", persisted=True),
        ),
    )
    op.create_index("ix_cost_rate_components_tenant_id", "cost_rate_components", ["tenant_id"])
    op.create_index("ix_cost_rate_components_rate_id", "cost_rate_components", ["rate_id"])

    op.execute(
        """
        CREATE OR REPLACE FUNCTION costlib_rate_as_of(
            p_tenant uuid, p_item uuid, p_scope text, p_valid_on date, p_known_at timestamptz
        ) RETURNS SETOF cost_item_rates
        LANGUAGE sql STABLE AS $$
            SELECT * FROM cost_item_rates
            WHERE tenant_id = p_tenant
              AND cost_item_id = p_item
              AND scope_key = p_scope
              AND valid_period @> p_valid_on
              AND sys_period @> p_known_at
        $$;
        """
    )

    for table, roles in (
        ("cost_items", WRITE_ROLES),
        ("cost_item_rates", WRITE_ROLES),
        ("cost_rate_components", WRITE_ROLES),
    ):
        enable_rls(op, table)
        tenant_policies(op, table, write_roles=roles, delete_roles=None)


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS costlib_rate_as_of(uuid, uuid, text, date, timestamptz);")
    op.drop_table("cost_rate_components")
    op.drop_table("cost_item_rates")
    op.drop_table("cost_items")
