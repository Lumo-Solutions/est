"""prequalification & statutory register

Revision ID: 0006
Revises: 0005
Create Date: 2026-01-01 00:00:05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from app.db.ddl import enable_rls, tenant_policies

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

WRITE_ROLES = ["procurement_head", "lead_estimator", "managing_director"]
AUTHORITY_WRITE_ROLES = ["procurement_head", "managing_director"]


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
        "authorities",
        *_entity_columns(),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("jurisdiction", sa.String(64), nullable=True),
    )
    op.create_index("ix_authorities_tenant_id", "authorities", ["tenant_id"])

    op.create_table(
        "certificate_types",
        *_entity_columns(),
        sa.Column("authority_id", pg.UUID(as_uuid=True), sa.ForeignKey("authorities.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("validity_months", sa.Integer, nullable=True),
        sa.Column("is_mandatory", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("warn_days_before", sa.Integer, nullable=False, server_default="60"),
    )
    op.create_index("ix_certificate_types_tenant_id", "certificate_types", ["tenant_id"])

    op.create_table(
        "vendor_certificates",
        *_entity_columns(),
        sa.Column("vendor_id", pg.UUID(as_uuid=True), sa.ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("certificate_type_id", pg.UUID(as_uuid=True), sa.ForeignKey("certificate_types.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("certificate_no", sa.String(128), nullable=True),
        sa.Column("issue_date", sa.Date, nullable=True),
        sa.Column("expiry_date", sa.Date, nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending_verification"),
        sa.Column("document_object_key", sa.String(512), nullable=True),
        sa.Column("document_sha256", sa.String(64), nullable=True),
        sa.Column("verified_by", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("verified_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_vendor_certificates_tenant_id", "vendor_certificates", ["tenant_id"])
    op.create_index("ix_vendor_certificates_vendor_id", "vendor_certificates", ["vendor_id"])
    op.create_index("ix_vendor_certificates_expiry", "vendor_certificates", ["tenant_id", "expiry_date"])

    op.create_table(
        "vendor_prequalifications",
        *_entity_columns(),
        sa.Column("vendor_id", pg.UUID(as_uuid=True), sa.ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("grade", sa.String(16), nullable=True),
        sa.Column("max_award_value", sa.Numeric(18, 2), nullable=True),
        sa.Column("scope_trade_node_id", pg.UUID(as_uuid=True), sa.ForeignKey("trade_nodes.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("effective_period", pg.DATERANGE, nullable=False),
        sa.Column("decided_by", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("decided_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("decision_note", sa.Text, nullable=True),
        sa.Column("supersedes_id", pg.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_vendor_prequalifications_supersedes_id", "vendor_prequalifications", "vendor_prequalifications",
        ["supersedes_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_vendor_prequalifications_tenant_id", "vendor_prequalifications", ["tenant_id"])
    op.create_index("ix_vendor_prequalifications_vendor_id", "vendor_prequalifications", ["vendor_id"])
    op.execute(
        "ALTER TABLE vendor_prequalifications ADD CONSTRAINT ex_vendor_prequal_no_overlap "
        "EXCLUDE USING gist ("
        "  tenant_id WITH =, "
        "  vendor_id WITH =, "
        "  COALESCE(scope_trade_node_id, '00000000-0000-0000-0000-000000000000'::uuid) WITH =, "
        "  effective_period WITH &&"
        ");"
    )

    op.create_table(
        "certificate_alerts",
        *_entity_columns(),
        sa.Column("vendor_certificate_id", pg.UUID(as_uuid=True), sa.ForeignKey("vendor_certificates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("alert_type", sa.String(16), nullable=False),
        sa.Column("due_date", sa.Date, nullable=False),
        sa.Column("notified_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("acknowledged_by", pg.UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_certificate_alerts_tenant_id", "certificate_alerts", ["tenant_id"])

    for table, roles in (
        ("authorities", AUTHORITY_WRITE_ROLES),
        ("certificate_types", AUTHORITY_WRITE_ROLES),
        ("vendor_certificates", WRITE_ROLES),
        ("vendor_prequalifications", WRITE_ROLES),
        ("certificate_alerts", WRITE_ROLES),
    ):
        enable_rls(op, table)
        tenant_policies(op, table, write_roles=roles, delete_roles=None)


def downgrade() -> None:
    op.drop_table("certificate_alerts")
    op.drop_table("vendor_prequalifications")
    op.drop_table("vendor_certificates")
    op.drop_table("certificate_types")
    op.drop_table("authorities")
