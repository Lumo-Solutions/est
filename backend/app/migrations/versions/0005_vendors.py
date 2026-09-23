"""vendor master, contacts, trades, duplicate candidates

Revision ID: 0005
Revises: 0004
Create Date: 2026-01-01 00:00:04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from app.db.ddl import enable_rls, tenant_policies

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

WRITE_ROLES = ["lead_estimator", "procurement_head", "bd_director", "managing_director"]
DELETE_ROLES = ["procurement_head", "managing_director"]


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
        "vendors",
        *_entity_columns(),
        sa.Column("legal_name", sa.String(255), nullable=False),
        sa.Column("trading_name", sa.String(255), nullable=True),
        sa.Column("normalized_name", sa.String(255), nullable=False),
        sa.Column("trade_license_no", sa.String(64), nullable=True),
        sa.Column("normalized_license", sa.String(64), nullable=True),
        sa.Column("license_authority", sa.String(64), nullable=True),
        sa.Column("trn_vat_no", sa.String(32), nullable=True),
        sa.Column("country", sa.String(2), nullable=True),
        sa.Column("emirate", sa.String(32), nullable=True),
        sa.Column("address_line", sa.Text, nullable=True),
        sa.Column("normalized_address", sa.Text, nullable=True),
        sa.Column("primary_email", sa.String(320), nullable=True),
        sa.Column("email_domain", sa.String(255), nullable=True),
        sa.Column("primary_phone", sa.String(32), nullable=True),
        sa.Column("phone_e164", sa.String(20), nullable=True),
        sa.Column("phone_last9", sa.String(9), nullable=True),
        sa.Column("website_domain", sa.String(255), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("merged_into_vendor_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("contact_fingerprint", sa.String(64), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
    )
    op.create_foreign_key(
        "fk_vendors_merged_into_vendor_id_vendors", "vendors", "vendors",
        ["merged_into_vendor_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_vendors_tenant_id", "vendors", ["tenant_id"])
    op.execute("CREATE INDEX ix_vendors_normalized_name_trgm ON vendors USING gin (normalized_name gin_trgm_ops);")
    op.execute("CREATE INDEX ix_vendors_normalized_license_trgm ON vendors USING gin (normalized_license gin_trgm_ops);")
    op.create_index("ix_vendors_tenant_phone_last9", "vendors", ["tenant_id", "phone_last9"])
    op.create_index("ix_vendors_tenant_email_domain", "vendors", ["tenant_id", "email_domain"])
    op.create_index("ix_vendors_tenant_contact_fingerprint", "vendors", ["tenant_id", "contact_fingerprint"])

    op.create_table(
        "vendor_contacts",
        *_entity_columns(),
        sa.Column("vendor_id", pg.UUID(as_uuid=True), sa.ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("role_title", sa.String(128), nullable=True),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("phone", sa.String(32), nullable=True),
        sa.Column("is_primary", sa.Boolean, nullable=False, server_default="false"),
    )
    op.create_index("ix_vendor_contacts_tenant_id", "vendor_contacts", ["tenant_id"])
    op.create_index("ix_vendor_contacts_vendor_id", "vendor_contacts", ["vendor_id"])

    op.create_table(
        "vendor_trades",
        *_entity_columns(),
        sa.Column("vendor_id", pg.UUID(as_uuid=True), sa.ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("trade_node_id", pg.UUID(as_uuid=True), sa.ForeignKey("trade_nodes.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("is_primary", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("capability_notes", sa.Text, nullable=True),
        sa.UniqueConstraint("vendor_id", "trade_node_id", name="uq_vendor_trades_vendor_trade"),
    )
    op.create_index("ix_vendor_trades_tenant_id", "vendor_trades", ["tenant_id"])
    op.create_index("ix_vendor_trades_vendor_id", "vendor_trades", ["vendor_id"])

    op.create_table(
        "vendor_duplicate_candidates",
        *_entity_columns(),
        sa.Column("vendor_a_id", pg.UUID(as_uuid=True), sa.ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("vendor_b_id", pg.UUID(as_uuid=True), sa.ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("score", sa.Numeric(5, 4), nullable=False),
        sa.Column("signals", pg.JSONB, nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="open"),
        sa.Column("detected_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("resolved_by", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("resolved_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("resolution_note", sa.Text, nullable=True),
        sa.UniqueConstraint("tenant_id", "vendor_a_id", "vendor_b_id", name="uq_vendor_dupes_tenant_pair"),
        sa.CheckConstraint("vendor_a_id < vendor_b_id", name="ck_vendor_dupes_ordered_pair"),
    )
    op.create_index("ix_vendor_duplicate_candidates_tenant_id", "vendor_duplicate_candidates", ["tenant_id"])

    for table, delete_roles in (
        ("vendors", DELETE_ROLES),
        ("vendor_contacts", DELETE_ROLES),
        ("vendor_trades", DELETE_ROLES),
        ("vendor_duplicate_candidates", None),
    ):
        enable_rls(op, table)
        tenant_policies(op, table, write_roles=WRITE_ROLES, delete_roles=delete_roles)


def downgrade() -> None:
    op.drop_table("vendor_duplicate_candidates")
    op.drop_table("vendor_trades")
    op.drop_table("vendor_contacts")
    op.drop_table("vendors")
