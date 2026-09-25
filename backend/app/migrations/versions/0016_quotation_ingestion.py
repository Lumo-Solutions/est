"""Module C2: inbound quotation ingestion, normalisation, and bid leveling

Adds the inbound half of Module C (SRS section 4). Two tables --
inbound_emails and quotation_attachments -- use a nullable tenant_id and
bespoke RLS instead of app/db/ddl.py::tenant_policies: a polled email's
tenant is identified from its own To: header (the plus-addressed recipient
embeds a tenant slug -- see app/procurement/inbound_address.py) *after* it's
already been received, so tenant_id starts NULL for a message whose
tenant-slug segment matches no tenant at all, and stays NULL. Those rows are
visible only to the platform_admin role (cross-tenant, not a tenant's own
staff) -- every other row is ordinary tenant-scoped RLS once a tenant is
identified, even if the reply-token match inside that tenant then fails.

quotations/quotation_line_items/quotation_exclusion_flags are only ever
created once a tenant (and an open Rfq) is already known, so they use the
standard tenant_policies helper like every Module C1 table.

Revision ID: 0016
Revises: 0015
Create Date: 2026-01-01 00:00:15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from app.db.ddl import enable_rls, tenant_policies

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

# Accepting/rejecting a vendor's price, or attaching/dismissing a flagged
# inbound email, is a procurement decision -- same tier as C1's dispatch/
# resend authority (app/services/procurement.py::_DISPATCH_ROLES), stricter
# than package/RFQ drafting (which also allows lead_estimator).
WRITE_ROLES = ["procurement_head", "bd_director", "managing_director"]
_WRITE_ROLES_SQL = "app_has_role(" + ", ".join(f"'{r}'" for r in WRITE_ROLES) + ")"


def _entity_columns() -> list[sa.Column]:
    return [
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", pg.UUID(as_uuid=True), nullable=True),
    ]


def _nullable_tenant_entity_columns() -> list[sa.Column]:
    cols = _entity_columns()
    cols[1] = sa.Column("tenant_id", pg.UUID(as_uuid=True), nullable=True)
    return cols


def upgrade() -> None:
    # ------------------------------------------------------------------
    # inbound_emails (nullable tenant_id, bespoke RLS)
    # ------------------------------------------------------------------
    op.create_table(
        "inbound_emails",
        *_nullable_tenant_entity_columns(),
        sa.Column("rfq_id", pg.UUID(as_uuid=True), sa.ForeignKey("rfqs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("imap_uid_validity", sa.String(32), nullable=False),
        sa.Column("imap_uid", sa.String(64), nullable=False),
        sa.Column("message_id", sa.String(255), nullable=True),
        sa.Column("from_address", sa.String(320), nullable=False),
        sa.Column("from_domain", sa.String(255), nullable=False),
        sa.Column("to_address", sa.String(320), nullable=False),
        sa.Column("subject", sa.String(998), nullable=True),
        sa.Column("received_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("match_status", sa.String(32), nullable=False, server_default="quarantined_unknown_tenant"),
        sa.Column("needs_review", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("review_reasons", pg.ARRAY(sa.Text), nullable=False, server_default="{}"),
        sa.Column("spf_result", sa.String(16), nullable=False, server_default="unknown"),
        sa.Column("dkim_result", sa.String(16), nullable=False, server_default="unknown"),
        sa.Column("dmarc_result", sa.String(16), nullable=False, server_default="unknown"),
        sa.Column("auth_results_raw", sa.Text, nullable=True),
        sa.Column("raw_object_key", sa.String(512), nullable=False),
        sa.Column("raw_sha256", sa.String(64), nullable=False),
        sa.Column("review_status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("reviewed_by", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("reviewed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text, nullable=True),
        sa.UniqueConstraint("imap_uid_validity", "imap_uid", name="uq_inbound_emails_imap_uid"),
    )
    op.create_index("ix_inbound_emails_tenant_id", "inbound_emails", ["tenant_id"])
    op.create_index("ix_inbound_emails_rfq_id", "inbound_emails", ["rfq_id"])
    enable_rls(op, "inbound_emails")
    op.execute(
        "CREATE POLICY inbound_emails_read ON inbound_emails FOR SELECT "
        "USING (app_is_system() "
        "OR (tenant_id IS NOT NULL AND tenant_id = app_tenant_id()) "
        "OR (tenant_id IS NULL AND app_has_role('platform_admin')));"
    )
    # Only the poller (a system actor) ever inserts a row here -- no
    # interactive user creates one directly.
    op.execute("CREATE POLICY inbound_emails_insert ON inbound_emails FOR INSERT WITH CHECK (app_is_system());")
    op.execute(
        "CREATE POLICY inbound_emails_update ON inbound_emails FOR UPDATE "
        "USING (app_is_system() "
        f"OR (tenant_id IS NOT NULL AND tenant_id = app_tenant_id() AND {_WRITE_ROLES_SQL}) "
        "OR (tenant_id IS NULL AND app_has_role('platform_admin'))) "
        # WITH CHECK deliberately also allows a platform_admin to move
        # tenant_id from NULL to a real tenant (resolving an
        # unknown-tenant email) -- that is exactly their one job here.
        "WITH CHECK (app_is_system() OR tenant_id = app_tenant_id() OR app_has_role('platform_admin'));"
    )

    # ------------------------------------------------------------------
    # quotation_attachments (nullable tenant_id, same shape as above)
    # ------------------------------------------------------------------
    op.create_table(
        "quotation_attachments",
        *_nullable_tenant_entity_columns(),
        sa.Column("inbound_email_id", pg.UUID(as_uuid=True), sa.ForeignKey("inbound_emails.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_type_declared", sa.String(128), nullable=True),
        sa.Column("content_type_sniffed", sa.String(128), nullable=True),
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        sa.Column("raw_object_key", sa.String(512), nullable=False),
        sa.Column("raw_sha256", sa.String(64), nullable=False),
        sa.Column("safety_status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("rejection_reason", sa.Text, nullable=True),
        sa.Column("processed_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_quotation_attachments_tenant_id", "quotation_attachments", ["tenant_id"])
    op.create_index("ix_quotation_attachments_inbound_email_id", "quotation_attachments", ["inbound_email_id"])
    enable_rls(op, "quotation_attachments")
    op.execute(
        "CREATE POLICY quotation_attachments_read ON quotation_attachments FOR SELECT "
        "USING (app_is_system() "
        "OR (tenant_id IS NOT NULL AND tenant_id = app_tenant_id()) "
        "OR (tenant_id IS NULL AND app_has_role('platform_admin')));"
    )
    op.execute("CREATE POLICY quotation_attachments_insert ON quotation_attachments FOR INSERT WITH CHECK (app_is_system());")
    op.execute(
        "CREATE POLICY quotation_attachments_update ON quotation_attachments FOR UPDATE "
        "USING (app_is_system() "
        f"OR (tenant_id IS NOT NULL AND tenant_id = app_tenant_id() AND {_WRITE_ROLES_SQL}) "
        "OR (tenant_id IS NULL AND app_has_role('platform_admin'))) "
        "WITH CHECK (app_is_system() OR tenant_id = app_tenant_id() OR app_has_role('platform_admin'));"
    )

    # ------------------------------------------------------------------
    # quotations (versioned per rfq+vendor -- SRS change #3)
    # ------------------------------------------------------------------
    op.create_table(
        "quotations",
        *_entity_columns(),
        sa.Column("rfq_id", pg.UUID(as_uuid=True), sa.ForeignKey("rfqs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("vendor_id", pg.UUID(as_uuid=True), sa.ForeignKey("vendors.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("package_id", pg.UUID(as_uuid=True), sa.ForeignKey("procurement_packages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", pg.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("inbound_email_id", pg.UUID(as_uuid=True), sa.ForeignKey("inbound_emails.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_attachment_id", pg.UUID(as_uuid=True), sa.ForeignKey("quotation_attachments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("extraction_method", sa.String(32), nullable=False),
        sa.Column("version_no", sa.Integer, nullable=False, server_default="1"),
        sa.Column("is_current", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column("vat_inclusive", sa.Boolean, nullable=True),
        sa.Column("submitted_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("is_late", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("status", sa.String(16), nullable=False, server_default="proposed"),
        sa.UniqueConstraint("rfq_id", "vendor_id", "version_no", name="uq_quotations_rfq_vendor_version"),
    )
    op.create_index("ix_quotations_tenant_id", "quotations", ["tenant_id"])
    op.create_index("ix_quotations_rfq_id", "quotations", ["rfq_id"])
    op.create_index("ix_quotations_vendor_id", "quotations", ["vendor_id"])
    op.create_index("ix_quotations_package_id", "quotations", ["package_id"])
    op.create_index("ix_quotations_project_id", "quotations", ["project_id"])
    # Exactly one "current" version per (rfq, vendor) -- enforced in the
    # database, not just by service-layer discipline (SRS change #3).
    op.execute(
        "CREATE UNIQUE INDEX uq_quotations_current_per_rfq_vendor ON quotations (rfq_id, vendor_id) WHERE is_current;"
    )
    enable_rls(op, "quotations")
    tenant_policies(op, "quotations", write_roles=WRITE_ROLES, project_scoped=True)

    # ------------------------------------------------------------------
    # quotation_line_items
    # ------------------------------------------------------------------
    op.create_table(
        "quotation_line_items",
        *_entity_columns(),
        sa.Column("quotation_id", pg.UUID(as_uuid=True), sa.ForeignKey("quotations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", pg.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("boq_line_item_id", pg.UUID(as_uuid=True), sa.ForeignKey("boq_line_items.id", ondelete="SET NULL"), nullable=True),
        sa.Column("vendor_item_text", sa.Text, nullable=True),
        sa.Column("vendor_description_text", sa.Text, nullable=True),
        sa.Column("unit_price", sa.Numeric(14, 4), nullable=True),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=True),
        sa.Column("extended_price_stated", sa.Numeric(16, 4), nullable=True),
        sa.Column("extended_price_computed", sa.Numeric(16, 4), nullable=True),
        sa.Column("arithmetic_mismatch", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("quantity_mismatch", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False, server_default="1.0"),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("match_method", sa.String(16), nullable=True),
        sa.Column("remarks_text", sa.Text, nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="proposed"),
        sa.Column("accepted_by", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("accepted_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_quotation_line_items_tenant_id", "quotation_line_items", ["tenant_id"])
    op.create_index("ix_quotation_line_items_quotation_id", "quotation_line_items", ["quotation_id"])
    op.create_index("ix_quotation_line_items_project_id", "quotation_line_items", ["project_id"])
    op.create_index("ix_quotation_line_items_boq_line_item_id", "quotation_line_items", ["boq_line_item_id"])
    enable_rls(op, "quotation_line_items")
    tenant_policies(op, "quotation_line_items", write_roles=WRITE_ROLES, project_scoped=True)

    # ------------------------------------------------------------------
    # quotation_exclusion_flags
    # ------------------------------------------------------------------
    op.create_table(
        "quotation_exclusion_flags",
        *_entity_columns(),
        sa.Column("quotation_id", pg.UUID(as_uuid=True), sa.ForeignKey("quotations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", pg.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("line_item_id", pg.UUID(as_uuid=True), sa.ForeignKey("quotation_line_items.id", ondelete="SET NULL"), nullable=True),
        sa.Column("flag_text", sa.Text, nullable=False),
        sa.Column("source_quote_text", sa.Text, nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False, server_default="0.5"),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("reviewed_by", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("reviewed_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_quotation_exclusion_flags_tenant_id", "quotation_exclusion_flags", ["tenant_id"])
    op.create_index("ix_quotation_exclusion_flags_quotation_id", "quotation_exclusion_flags", ["quotation_id"])
    op.create_index("ix_quotation_exclusion_flags_project_id", "quotation_exclusion_flags", ["project_id"])
    enable_rls(op, "quotation_exclusion_flags")
    tenant_policies(op, "quotation_exclusion_flags", write_roles=WRITE_ROLES, project_scoped=True)


def downgrade() -> None:
    op.drop_table("quotation_exclusion_flags")
    op.drop_table("quotation_line_items")
    op.execute("DROP INDEX IF EXISTS uq_quotations_current_per_rfq_vendor;")
    op.drop_table("quotations")
    op.drop_table("quotation_attachments")
    op.drop_table("inbound_emails")
