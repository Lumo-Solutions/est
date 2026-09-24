"""Module C1: procurement packages, RFQ dispatch, per-tenant RFQ numbering

Adds the outbound half of Module C (SRS section 4, "AI Procurement & Bid
Leveling" -- RFQ generation/dispatch and vendor matching). Inbound quotation
ingestion, normalisation, and bid leveling (Module C2) build on top of this
schema later without further migration to these three tables (rfqs.status
already includes 'responded'/'expired' for that purpose -- see
app.core.enums.RfqStatus).

`rfq_ref` (human reference, e.g. RFQ-2026-0042) is assigned by a BEFORE
INSERT trigger from a per-tenant/per-year counter table
(procurement_rfq_counters), the same "increment-under-row-lock" shape as
audit_events_chain_trg() (migration 0003) -- guarantees uniqueness and no
lost updates under concurrent draft creation without a client-visible
retry loop.

Revision ID: 0015
Revises: 0014
Create Date: 2026-01-01 00:00:14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from app.db.ddl import enable_rls, tenant_policies

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

# Drafting a package/RFQ is structural, same seniority as BOQ structural
# edits (migration 0011) -- deliberately excludes plain "estimator".
# Dispatch/resend is gated *further* at the service layer
# (procurement_head+ with MFA step-up, app/services/procurement.py) on top
# of this RLS write policy, the same split approvals.decide() uses for its
# own step-up check beyond RLS.
WRITE_ROLES = ["lead_estimator", "procurement_head", "bd_director", "managing_director"]
DELETE_ROLES = ["procurement_head", "managing_director"]

_RFQ_REF_TRIGGER_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION rfqs_assign_ref_trg() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_year int := extract(year from now())::int;
    v_seq bigint;
BEGIN
    IF NEW.rfq_ref IS NOT NULL THEN
        RETURN NEW;
    END IF;

    INSERT INTO procurement_rfq_counters (tenant_id, year, last_seq)
    VALUES (NEW.tenant_id, v_year, 0)
    ON CONFLICT (tenant_id, year) DO NOTHING;

    UPDATE procurement_rfq_counters
    SET last_seq = last_seq + 1
    WHERE tenant_id = NEW.tenant_id AND year = v_year
    RETURNING last_seq INTO v_seq;

    NEW.rfq_ref := 'RFQ-' || v_year || '-' || lpad(v_seq::text, 4, '0');
    RETURN NEW;
END;
$$;
"""


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
        "procurement_packages",
        *_entity_columns(),
        sa.Column("project_id", pg.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("trade_node_id", pg.UUID(as_uuid=True), sa.ForeignKey("trade_nodes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("due_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
    )
    op.create_index("ix_procurement_packages_tenant_id", "procurement_packages", ["tenant_id"])
    op.create_index("ix_procurement_packages_project_id", "procurement_packages", ["project_id"])
    op.create_index("ix_procurement_packages_trade_node_id", "procurement_packages", ["trade_node_id"])
    enable_rls(op, "procurement_packages")
    tenant_policies(op, "procurement_packages", write_roles=WRITE_ROLES, delete_roles=DELETE_ROLES, project_scoped=True)

    op.create_table(
        "procurement_package_items",
        *_entity_columns(),
        sa.Column("package_id", pg.UUID(as_uuid=True), sa.ForeignKey("procurement_packages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("boq_line_item_id", pg.UUID(as_uuid=True), sa.ForeignKey("boq_line_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", pg.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("package_id", "boq_line_item_id", name="uq_procurement_package_items_pair"),
    )
    op.create_index("ix_procurement_package_items_tenant_id", "procurement_package_items", ["tenant_id"])
    op.create_index("ix_procurement_package_items_package_id", "procurement_package_items", ["package_id"])
    op.create_index("ix_procurement_package_items_project_id", "procurement_package_items", ["project_id"])
    enable_rls(op, "procurement_package_items")
    tenant_policies(op, "procurement_package_items", write_roles=WRITE_ROLES, delete_roles=DELETE_ROLES, project_scoped=True)

    # System-maintained counter, same shape/policy as audit_chain_heads
    # (migration 0003): only the rfqs_assign_ref_trg() trigger writes it.
    op.create_table(
        "procurement_rfq_counters",
        sa.Column("tenant_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("year", sa.Integer, primary_key=True),
        sa.Column("last_seq", sa.BigInteger, nullable=False, server_default="0"),
    )
    enable_rls(op, "procurement_rfq_counters")
    op.execute(
        "CREATE POLICY procurement_rfq_counters_system ON procurement_rfq_counters FOR ALL "
        "USING (app_is_system() OR tenant_id = app_tenant_id()) "
        "WITH CHECK (tenant_id = app_tenant_id() OR app_is_system());"
    )

    op.create_table(
        "rfqs",
        *_entity_columns(),
        sa.Column("package_id", pg.UUID(as_uuid=True), sa.ForeignKey("procurement_packages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", pg.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("vendor_id", pg.UUID(as_uuid=True), sa.ForeignKey("vendors.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("vendor_contact_id", pg.UUID(as_uuid=True), sa.ForeignKey("vendor_contacts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("rfq_ref", sa.String(32), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("due_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("is_override", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("override_reason", sa.Text, nullable=True),
        sa.Column("subject", sa.String(255), nullable=True),
        sa.Column("body_html", sa.Text, nullable=True),
        sa.Column("attachment_object_key", sa.String(512), nullable=True),
        sa.Column("attachment_sha256", sa.String(64), nullable=True),
        sa.Column("message_id", sa.String(255), nullable=True),
        sa.Column("reply_token", sa.String(43), nullable=False),
        sa.Column("dispatch_attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("dispatch_error", sa.Text, nullable=True),
        sa.Column("celery_task_id", sa.String(64), nullable=True),
        sa.Column("queued_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("sent_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "rfq_ref", name="uq_rfqs_tenant_ref"),
        sa.UniqueConstraint("reply_token", name="uq_rfqs_reply_token"),
    )
    op.create_index("ix_rfqs_tenant_id", "rfqs", ["tenant_id"])
    op.create_index("ix_rfqs_project_id", "rfqs", ["project_id"])
    op.create_index("ix_rfqs_package_id", "rfqs", ["package_id"])
    op.create_index("ix_rfqs_vendor_id", "rfqs", ["vendor_id"])
    op.create_index("ix_rfqs_status", "rfqs", ["status"])

    op.execute(_RFQ_REF_TRIGGER_FUNCTION_SQL)
    op.execute("CREATE TRIGGER rfqs_assign_ref_trg BEFORE INSERT ON rfqs FOR EACH ROW EXECUTE FUNCTION rfqs_assign_ref_trg();")

    enable_rls(op, "rfqs")
    tenant_policies(op, "rfqs", write_roles=WRITE_ROLES, delete_roles=DELETE_ROLES, project_scoped=True)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS rfqs_assign_ref_trg ON rfqs;")
    op.execute("DROP FUNCTION IF EXISTS rfqs_assign_ref_trg() CASCADE;")
    op.drop_table("rfqs")
    op.drop_table("procurement_rfq_counters")
    op.drop_table("procurement_package_items")
    op.drop_table("procurement_packages")
