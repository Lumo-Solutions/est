"""Tender document intake: packages, project documents, classification
proposals, addenda register, per-tenant class overrides, drawing revision
lineage. See docs/tender-intake-plan.md.

Every table denormalises project_id (RLS project_scoped clause is a plain
column check). tender_class_config is tenant-level (not project scoped).
RLS is ENABLE + FORCE on every table.

Revision ID: 0030
Revises: 0029
Create Date: 2026-01-10 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from app.db.ddl import enable_rls, tenant_policies

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None

# Anyone who can upload writes packages/documents/classifications (and the
# worker acts with the uploader's roles). Only confirmation writes addenda,
# and that is lead_estimator and above.
UPLOAD_WRITE_ROLES = ["estimator", "lead_estimator", "procurement_head", "bd_director", "managing_director"]
CONFIRM_WRITE_ROLES = ["lead_estimator", "procurement_head", "bd_director", "managing_director"]
CLASS_ADMIN_ROLES = ["managing_director"]


def _entity_columns() -> list[sa.Column]:
    return [
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", pg.UUID(as_uuid=True), nullable=True),
    ]


def _project_fk() -> sa.Column:
    return sa.Column("project_id", pg.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)


def upgrade() -> None:
    op.create_table(
        "tender_packages",
        *_entity_columns(),
        _project_fk(),
        sa.Column("label", sa.String(255), nullable=True),
        sa.Column("transmittal_ref", sa.String(128), nullable=True),
        sa.Column("received_date", sa.Date, nullable=False, server_default=sa.text("CURRENT_DATE")),
        sa.Column("status", sa.String(16), nullable=False, server_default="processing"),
        sa.Column("file_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("notes", sa.Text, nullable=True),
    )

    op.create_table(
        "project_documents",
        *_entity_columns(),
        _project_fk(),
        sa.Column("package_id", pg.UUID(as_uuid=True), sa.ForeignKey("tender_packages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parent_document_id", pg.UUID(as_uuid=True), sa.ForeignKey("project_documents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("archive_path", sa.String(1024), nullable=True),
        sa.Column("original_filename", sa.String(512), nullable=False),
        sa.Column("ext", sa.String(16), nullable=False, server_default=""),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("bucket", sa.String(128), nullable=False),
        sa.Column("object_key", sa.String(512), nullable=False),
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        sa.Column("content_type_sniffed", sa.String(32), nullable=True),
        sa.Column("safety_status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("rejection_reason", sa.Text, nullable=True),
        sa.Column("doc_class", sa.String(32), nullable=True),
        sa.Column("sub_type", sa.String(32), nullable=True),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("title", sa.String(512), nullable=True),
        sa.Column("document_number", sa.String(128), nullable=True),
        sa.Column("revision_label", sa.String(32), nullable=True),
        sa.Column("metadata", pg.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("evidence", pg.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("flags", pg.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("status", sa.String(16), nullable=False, server_default="received"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("duplicate_of_id", pg.UUID(as_uuid=True), sa.ForeignKey("project_documents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("supersedes_id", pg.UUID(as_uuid=True), sa.ForeignKey("project_documents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("routed_kind", sa.String(32), nullable=True),
        sa.Column("routed_ref", pg.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("confirmed_by", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("confirmed_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_project_documents_tenant_id", "project_documents", ["tenant_id"])
    op.create_index("ix_project_documents_project_id", "project_documents", ["project_id"])
    op.create_index("ix_project_documents_package_id", "project_documents", ["package_id"])
    op.create_index("ix_project_documents_project_class", "project_documents", ["project_id", "doc_class"])
    op.create_index("ix_project_documents_project_sha256", "project_documents", ["project_id", "sha256"])
    op.execute("CREATE INDEX ix_project_documents_metadata ON project_documents USING gin (metadata)")

    op.create_table(
        "document_classifications",
        *_entity_columns(),
        _project_fk(),
        sa.Column("document_id", pg.UUID(as_uuid=True), sa.ForeignKey("project_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("doc_class", sa.String(32), nullable=False),
        sa.Column("sub_type", sa.String(32), nullable=True),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column("evidence", pg.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("metadata", pg.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("is_current", sa.Boolean, nullable=False, server_default="true"),
    )
    op.create_index("ix_document_classifications_document_id", "document_classifications", ["document_id"])

    op.create_table(
        "addenda",
        *_entity_columns(),
        _project_fk(),
        sa.Column("document_id", pg.UUID(as_uuid=True), sa.ForeignKey("project_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("package_id", pg.UUID(as_uuid=True), sa.ForeignKey("tender_packages.id", ondelete="SET NULL"), nullable=True),
        sa.Column("addendum_no", sa.String(32), nullable=True),
        sa.Column("issue_date", sa.String(32), nullable=True),
        sa.Column("title", sa.String(512), nullable=True),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("routed_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("flagged_settlement_ids", pg.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.UniqueConstraint("document_id", name="uq_addenda_document"),
    )

    op.create_table(
        "addendum_links",
        *_entity_columns(),
        _project_fk(),
        sa.Column("addendum_id", pg.UUID(as_uuid=True), sa.ForeignKey("addenda.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_document_id", pg.UUID(as_uuid=True), sa.ForeignKey("project_documents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reference_text", sa.String(255), nullable=False),
        sa.Column("action", sa.String(16), nullable=False, server_default="supersedes"),
        sa.Column("resolved", sa.Boolean, nullable=False, server_default="false"),
    )
    op.create_index("ix_addendum_links_addendum_id", "addendum_links", ["addendum_id"])

    op.create_table(
        "tender_class_config",
        *_entity_columns(),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("label", sa.String(128), nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.UniqueConstraint("tenant_id", "code", name="uq_tender_class_config_tenant_code"),
    )

    for table in ("tender_packages", "document_classifications"):
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])
        op.create_index(f"ix_{table}_project_id", table, ["project_id"])
    for table in ("addenda", "addendum_links"):
        op.create_index(f"ix_{table}_project_id", table, ["project_id"])
    for table in ("tender_packages", "project_documents", "document_classifications"):
        enable_rls(op, table)
        tenant_policies(op, table, write_roles=UPLOAD_WRITE_ROLES, project_scoped=True)
    for table in ("addenda", "addendum_links"):
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])
        enable_rls(op, table)
        tenant_policies(op, table, write_roles=CONFIRM_WRITE_ROLES, project_scoped=True)
    op.create_index("ix_tender_class_config_tenant_id", "tender_class_config", ["tenant_id"])
    enable_rls(op, "tender_class_config")
    tenant_policies(op, "tender_class_config", write_roles=CLASS_ADMIN_ROLES)

    # Drawing revision lineage: a replacement drawing points at the one it supersedes.
    op.add_column("drawings", sa.Column("supersedes_id", pg.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_drawings_supersedes_id", "drawings", "drawings", ["supersedes_id"], ["id"], ondelete="SET NULL"
    )


def downgrade() -> None:
    op.drop_constraint("fk_drawings_supersedes_id", "drawings", type_="foreignkey")
    op.drop_column("drawings", "supersedes_id")
    for table in (
        "tender_class_config", "addendum_links", "addenda", "document_classifications", "project_documents", "tender_packages",
    ):
        op.drop_table(table)
