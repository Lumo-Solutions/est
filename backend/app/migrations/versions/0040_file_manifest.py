"""BOQ agent, phase 1: the file manifest (fast, AI-free index of every uploaded file).

* project_file_index: one row per project document (unique document_id) holding what can be read without a model:
  path/folder/filename/size/sha256, PDF page count + sizes + page-1 text + title-block text, spreadsheet sheet names +
  header rows + row counts, the rules' classification as hints, `partial_index` when a limit cut the read short.
  `search_tsv` (GIN) and `embedding` (HNSW, cosine) make it searchable; both are RLS-scoped to the project like the rest.
* tenant_ai_settings.intake_ai_classify: the per-file AI classification at upload (default off; the code stays).

Revision ID: 0040
Revises: 0039
Create Date: 2026-10-10 09:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql as pg

from app.db.ddl import enable_rls, tenant_policies

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None

ALL_ROLES = ["estimator", "lead_estimator", "procurement_head", "bd_director", "managing_director"]
EMBEDDING_DIM = 384  # app.db.types.DEFAULT_EMBEDDING_DIM


def upgrade() -> None:
    op.add_column("tenant_ai_settings", sa.Column("intake_ai_classify", sa.Boolean, nullable=False, server_default="false"))

    op.create_table(
        "project_file_index",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("project_id", pg.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "document_id", pg.UUID(as_uuid=True), sa.ForeignKey("project_documents.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("path", sa.Text, nullable=False),
        sa.Column("folder", sa.Text, nullable=False, server_default=""),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("ext", sa.String(16), nullable=False, server_default=""),
        sa.Column("size_bytes", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("page_count", sa.Integer, nullable=True),
        sa.Column("page_sizes", pg.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("page1_text", sa.Text, nullable=False, server_default=""),
        sa.Column("title_block_text", sa.Text, nullable=False, server_default=""),
        sa.Column("sheets", pg.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("hints", pg.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("hints_text", sa.Text, nullable=False, server_default=""),
        sa.Column("partial_index", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("partial_reason", sa.String(255), nullable=True),
        sa.Column("indexed_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
        sa.Column(
            "search_tsv",
            pg.TSVECTOR,
            sa.Computed(
                "setweight(to_tsvector('simple', coalesce(filename, '')), 'A') || "
                "setweight(to_tsvector('simple', coalesce(path, '')), 'B') || "
                "setweight(to_tsvector('simple', coalesce(title_block_text, '')), 'B') || "
                "setweight(to_tsvector('simple', coalesce(hints_text, '')), 'B') || "
                "setweight(to_tsvector('simple', coalesce(page1_text, '')), 'C')",
                persisted=True,
            ),
        ),
        sa.UniqueConstraint("document_id", name="uq_project_file_index_document"),
    )
    op.create_index("ix_project_file_index_tenant_id", "project_file_index", ["tenant_id"])
    op.create_index("ix_project_file_index_project_id", "project_file_index", ["project_id"])
    op.execute("CREATE INDEX ix_project_file_index_tsv ON project_file_index USING gin (search_tsv)")
    op.execute(
        "CREATE INDEX ix_project_file_index_embedding_hnsw ON project_file_index "
        "USING hnsw (embedding vector_cosine_ops) WITH (m=16, ef_construction=64)"
    )
    enable_rls(op, "project_file_index")
    tenant_policies(op, "project_file_index", write_roles=ALL_ROLES, project_scoped=True)


def downgrade() -> None:
    op.drop_table("project_file_index")
    op.drop_column("tenant_ai_settings", "intake_ai_classify")
