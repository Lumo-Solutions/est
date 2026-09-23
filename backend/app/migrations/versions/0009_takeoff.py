"""Module B: drawing ingestion, sheets, entities, embeddings, extraction jobs

Revision ID: 0009
Revises: 0008
Create Date: 2026-01-01 00:00:08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql as pg

from app.core.config import get_settings
from app.db.ddl import enable_rls, tenant_policies

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

WRITE_ROLES = ["estimator", "lead_estimator", "procurement_head", "bd_director", "managing_director"]
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
    embedding_dim = get_settings().embedding_dim

    op.create_table(
        "drawings",
        *_entity_columns(),
        sa.Column("project_id", pg.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("original_filename", sa.String(512), nullable=False),
        sa.Column("content_type", sa.String(128), nullable=True),
        sa.Column("kind", sa.String(16), nullable=False, server_default="unknown"),
        sa.Column("bucket", sa.String(128), nullable=False),
        sa.Column("object_key", sa.String(512), nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("sheet_count", sa.Integer, nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="uploaded"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("discipline_hint", sa.String(32), nullable=True),
        sa.Column("revision_label", sa.String(32), nullable=True),
        sa.Column("uploaded_by", pg.UUID(as_uuid=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "project_id", "sha256", name="uq_drawings_tenant_project_sha256"),
    )
    op.create_index("ix_drawings_tenant_id", "drawings", ["tenant_id"])
    op.create_index("ix_drawings_project_id", "drawings", ["project_id"])

    op.create_table(
        "drawing_sheets",
        *_entity_columns(),
        sa.Column("drawing_id", pg.UUID(as_uuid=True), sa.ForeignKey("drawings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("sheet_index", sa.Integer, nullable=False),
        sa.Column("source_name", sa.String(255), nullable=True),
        sa.Column("width_pt", sa.Numeric(12, 3), nullable=True),
        sa.Column("height_pt", sa.Numeric(12, 3), nullable=True),
        sa.Column("units", sa.String(16), nullable=True),
        sa.Column("is_raster", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("raw_text", sa.Text, nullable=True),
        sa.Column("text_char_count", sa.Integer, nullable=True),
        sa.Column("title_block", pg.JSONB, nullable=True),
        sa.Column("drawing_number", sa.String(128), nullable=True),
        sa.Column("sheet_title", sa.String(255), nullable=True),
        sa.Column("revision", sa.String(16), nullable=True),
        sa.Column("issue_date", sa.String(32), nullable=True),
        sa.Column("discipline", sa.String(32), nullable=True),
        sa.Column("scale_text", sa.String(64), nullable=True),
        sa.Column("scale_ratio", sa.Numeric(12, 6), nullable=True),
        sa.Column("scale_source", sa.String(24), nullable=True, server_default="unknown"),
        sa.Column("scale_confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("extraction_status", sa.String(16), nullable=True),
        sa.Column("vlm_model", sa.String(128), nullable=True),
        sa.Column("vlm_raw", pg.JSONB, nullable=True),
        sa.UniqueConstraint("drawing_id", "sheet_index", name="uq_drawing_sheets_drawing_index"),
    )
    op.create_index("ix_drawing_sheets_tenant_id", "drawing_sheets", ["tenant_id"])
    op.create_index("ix_drawing_sheets_project_id", "drawing_sheets", ["project_id"])
    op.create_index("ix_drawing_sheets_drawing_id", "drawing_sheets", ["drawing_id"])

    op.create_table(
        "drawing_entities",
        *_entity_columns(),
        sa.Column("sheet_id", pg.UUID(as_uuid=True), sa.ForeignKey("drawing_sheets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(8), nullable=False),
        sa.Column("entity_type", sa.String(24), nullable=False),
        sa.Column("layer", sa.String(128), nullable=True),
        sa.Column("block_name", sa.String(128), nullable=True),
        sa.Column("text_value", sa.Text, nullable=True),
        sa.Column("bbox_min_x", sa.Numeric(18, 6), nullable=True),
        sa.Column("bbox_min_y", sa.Numeric(18, 6), nullable=True),
        sa.Column("bbox_max_x", sa.Numeric(18, 6), nullable=True),
        sa.Column("bbox_max_y", sa.Numeric(18, 6), nullable=True),
        sa.Column("geometry", pg.JSONB, nullable=True),
        sa.Column("attributes", pg.JSONB, nullable=True),
        sa.Column("handle", sa.String(32), nullable=True),
    )
    op.create_index("ix_drawing_entities_tenant_id", "drawing_entities", ["tenant_id"])
    op.create_index("ix_drawing_entities_project_id", "drawing_entities", ["project_id"])
    op.create_index("ix_drawing_entities_sheet_id", "drawing_entities", ["sheet_id"])
    op.create_index("ix_drawing_entities_sheet_type", "drawing_entities", ["sheet_id", "entity_type"])
    op.create_index("ix_drawing_entities_tenant_layer", "drawing_entities", ["tenant_id", "layer"])

    op.create_table(
        "sheet_chunks",
        *_entity_columns(),
        sa.Column("sheet_id", pg.UUID(as_uuid=True), sa.ForeignKey("drawing_sheets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("drawing_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("chunk_type", sa.String(24), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("token_count", sa.Integer, nullable=True),
        sa.Column("embedding", Vector(embedding_dim), nullable=False),
        sa.Column("embedding_model", sa.String(128), nullable=False),
        sa.Column("embedding_version", sa.SmallInteger, nullable=False, server_default="1"),
        sa.Column("source_ref", pg.JSONB, nullable=True),
    )
    op.create_index("ix_sheet_chunks_tenant_id", "sheet_chunks", ["tenant_id"])
    op.create_index("ix_sheet_chunks_project_id", "sheet_chunks", ["project_id"])
    op.create_index("ix_sheet_chunks_sheet_id", "sheet_chunks", ["sheet_id"])
    op.execute(
        "CREATE INDEX ix_sheet_chunks_embedding_hnsw ON sheet_chunks "
        "USING hnsw (embedding vector_cosine_ops) WITH (m=16, ef_construction=64);"
    )

    op.create_table(
        "extraction_jobs",
        *_entity_columns(),
        sa.Column("drawing_id", pg.UUID(as_uuid=True), sa.ForeignKey("drawings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sheet_id", pg.UUID(as_uuid=True), sa.ForeignKey("drawing_sheets.id", ondelete="CASCADE"), nullable=True),
        # Denormalized from drawings.project_id for the project-scoped RLS
        # policy below (app_can_see_project(project_id) reads this column
        # directly, same pattern as approval_steps.project_id in 0008).
        sa.Column("project_id", pg.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_type", sa.String(24), nullable=False),
        sa.Column("celery_task_id", sa.String(64), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempt", sa.SmallInteger, nullable=False, server_default="1"),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("metrics", pg.JSONB, nullable=True),
    )
    op.create_index("ix_extraction_jobs_tenant_id", "extraction_jobs", ["tenant_id"])
    op.create_index("ix_extraction_jobs_drawing_id", "extraction_jobs", ["drawing_id"])
    op.execute(
        "CREATE UNIQUE INDEX uq_extraction_jobs_dedup ON extraction_jobs "
        "(drawing_id, coalesce(sheet_id, '00000000-0000-0000-0000-000000000000'::uuid), job_type, attempt);"
    )

    for table in ("drawings", "drawing_sheets", "drawing_entities", "sheet_chunks", "extraction_jobs"):
        enable_rls(op, table)
        tenant_policies(op, table, write_roles=WRITE_ROLES, delete_roles=DELETE_ROLES, project_scoped=True)


def downgrade() -> None:
    op.drop_table("extraction_jobs")
    op.drop_table("sheet_chunks")
    op.drop_table("drawing_entities")
    op.drop_table("drawing_sheets")
    op.drop_table("drawings")
