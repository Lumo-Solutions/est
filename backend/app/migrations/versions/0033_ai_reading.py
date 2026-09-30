"""AI-assisted reading: PDF BOQ extractions, drawing annotations, BOQ line provenance.

- boq_pdf_extractions: one PDF BOQ read (deterministic table parse, AI only for
  unclear/scanned pages). Rows are stored as editable JSON until the estimator
  commits them through the import wizard; nothing touches boq_line_items before
  that. Project-scoped RLS; the same roles that may import a BOQ may write.
- boq_line_items: where a line came from (xlsx/csv/pdf), the PDF page + region,
  and whether an AI read it (ai_read) so the UI can flag it.
- drawing_annotations: dimension/quantity annotations read from a sheet (text,
  kind, printed value + unit, page region). Values are READ, never measured.
- drawing_sheets.ai_notes: legend / schedule / scale notes read from the sheet.

Revision ID: 0033
Revises: 0032
Create Date: 2026-09-30 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from app.db.ddl import enable_rls, tenant_policies

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None

BOQ_WRITE_ROLES = ["lead_estimator", "procurement_head", "managing_director"]
READ_WRITE_ROLES = ["estimator", "lead_estimator", "procurement_head", "bd_director", "managing_director"]


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
        "boq_pdf_extractions",
        *_entity_columns(),
        _project_fk(),
        sa.Column("document_id", pg.UUID(as_uuid=True), sa.ForeignKey("project_documents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_filename", sa.String(512), nullable=False),
        sa.Column("bucket", sa.String(128), nullable=False),
        sa.Column("object_key", sa.String(512), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        # queued | running | ready | failed | committed
        sa.Column("status", sa.String(12), nullable=False, server_default="queued"),
        sa.Column("use_ai", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("pages_total", sa.Integer, nullable=False, server_default="0"),
        sa.Column("pages_done", sa.Integer, nullable=False, server_default="0"),
        # [{page, status, note, rows, quality}] -- per-page progress and outcome.
        sa.Column("page_summary", pg.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        # [{row_id, page, item_no, description, uom, quantity, bbox, page_size, source, confidence, edited}]
        sa.Column("rows", pg.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("warnings", pg.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("batch_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("committed_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_boq_pdf_extractions_tenant_id", "boq_pdf_extractions", ["tenant_id"])
    op.create_index("ix_boq_pdf_extractions_project_id", "boq_pdf_extractions", ["project_id"])
    enable_rls(op, "boq_pdf_extractions")
    tenant_policies(op, "boq_pdf_extractions", write_roles=BOQ_WRITE_ROLES, project_scoped=True)

    op.add_column("boq_line_items", sa.Column("source_kind", sa.String(8), nullable=True))
    op.add_column("boq_line_items", sa.Column("source_page", sa.Integer, nullable=True))
    op.add_column("boq_line_items", sa.Column("source_bbox", pg.JSONB, nullable=True))
    op.add_column("boq_line_items", sa.Column("ai_read", sa.Boolean, nullable=False, server_default="false"))

    op.add_column("drawing_sheets", sa.Column("ai_notes", pg.JSONB, nullable=True))
    op.add_column("drawing_sheets", sa.Column("annotations_status", sa.String(16), nullable=True))
    op.add_column("drawing_sheets", sa.Column("annotations_read_at", sa.TIMESTAMP(timezone=True), nullable=True))

    op.create_table(
        "drawing_annotations",
        *_entity_columns(),
        _project_fk(),
        sa.Column("drawing_id", pg.UUID(as_uuid=True), sa.ForeignKey("drawings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sheet_id", pg.UUID(as_uuid=True), sa.ForeignKey("drawing_sheets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("page", sa.Integer, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("value", sa.Numeric(18, 4), nullable=True),
        sa.Column("unit", sa.String(16), nullable=True),
        sa.Column("material", sa.String(128), nullable=True),
        sa.Column("bbox", pg.JSONB, nullable=True),
        sa.Column("source", sa.String(8), nullable=False, server_default="ai"),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("ai_call_id", pg.UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_drawing_annotations_tenant_id", "drawing_annotations", ["tenant_id"])
    op.create_index("ix_drawing_annotations_project_id", "drawing_annotations", ["project_id"])
    op.create_index("ix_drawing_annotations_sheet_id", "drawing_annotations", ["sheet_id"])
    enable_rls(op, "drawing_annotations")
    tenant_policies(
        op, "drawing_annotations", write_roles=READ_WRITE_ROLES, delete_roles=READ_WRITE_ROLES, project_scoped=True
    )


def downgrade() -> None:
    op.drop_table("drawing_annotations")
    for col in ("annotations_read_at", "annotations_status", "ai_notes"):
        op.drop_column("drawing_sheets", col)
    for col in ("ai_read", "source_bbox", "source_page", "source_kind"):
        op.drop_column("boq_line_items", col)
    op.drop_table("boq_pdf_extractions")
