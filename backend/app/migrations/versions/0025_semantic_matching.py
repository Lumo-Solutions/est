"""Module B/C Phase 5: semantic matching -- pgvector columns for BOQ line
items, drawing measurements, and quotation line items, plus the
continuous-learning feedback store. See docs/module-b-c-phase5-plan.md.

Adds:
- boq_line_items.description_embedding, drawing_measurements.
  descriptor_embedding, quotation_line_items.description_embedding --
  each nullable vector(EMBEDDING_DIM) + HNSW index (same technique as
  migration 0009's sheet_chunks.embedding, the only prior pgvector
  consumer). Nullable: embed_best_effort() degrades to leaving these NULL
  when the ONNX model isn't provisioned (see app/integrations/
  embeddings.py) -- a suggestion query simply treats a NULL embedding as
  "no semantic signal for this row," never a NOT NULL violation.
- semantic_match_feedback (new, tenant+project-scoped, RLS-forced) --
  accepted/rejected suggestion outcomes, re-ranking future suggestions by
  nearest-neighbor precedent (no model training).

Revision ID: 0025
Revises: 0024
Create Date: 2026-01-07 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql as pg

from app.core.config import get_settings
from app.db.ddl import enable_rls, tenant_policies

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None

# Feedback rows are written by whichever role can already accept/reject a
# suggestion (the existing link/accept actions this rides alongside) --
# same operational tier as drawing_measurement_overrides (migration 0023),
# not a narrower admin-only one.
FEEDBACK_WRITE_ROLES = ["estimator", "lead_estimator", "procurement_head", "bd_director", "managing_director"]


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

    op.add_column("boq_line_items", sa.Column("description_embedding", Vector(embedding_dim), nullable=True))
    op.execute(
        "CREATE INDEX ix_boq_line_items_description_embedding_hnsw ON boq_line_items "
        "USING hnsw (description_embedding vector_cosine_ops) WITH (m=16, ef_construction=64);"
    )

    op.add_column("drawing_measurements", sa.Column("descriptor_embedding", Vector(embedding_dim), nullable=True))
    op.execute(
        "CREATE INDEX ix_drawing_measurements_descriptor_embedding_hnsw ON drawing_measurements "
        "USING hnsw (descriptor_embedding vector_cosine_ops) WITH (m=16, ef_construction=64);"
    )

    op.add_column("quotation_line_items", sa.Column("description_embedding", Vector(embedding_dim), nullable=True))
    op.execute(
        "CREATE INDEX ix_quotation_line_items_description_embedding_hnsw ON quotation_line_items "
        "USING hnsw (description_embedding vector_cosine_ops) WITH (m=16, ef_construction=64);"
    )

    op.create_table(
        "semantic_match_feedback",
        *_entity_columns(),
        sa.Column("project_id", pg.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("match_type", sa.String(24), nullable=False),
        sa.Column("query_embedding", Vector(embedding_dim), nullable=False),
        sa.Column("target_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
    )
    op.create_index("ix_semantic_match_feedback_tenant_id", "semantic_match_feedback", ["tenant_id"])
    op.create_index("ix_semantic_match_feedback_project_id", "semantic_match_feedback", ["project_id"])
    op.create_index("ix_semantic_match_feedback_match_type", "semantic_match_feedback", ["match_type"])
    op.execute(
        "CREATE INDEX ix_semantic_match_feedback_query_embedding_hnsw ON semantic_match_feedback "
        "USING hnsw (query_embedding vector_cosine_ops) WITH (m=16, ef_construction=64);"
    )
    enable_rls(op, "semantic_match_feedback")
    tenant_policies(op, "semantic_match_feedback", write_roles=FEEDBACK_WRITE_ROLES, project_scoped=True)


def downgrade() -> None:
    op.drop_table("semantic_match_feedback")
    op.drop_index("ix_quotation_line_items_description_embedding_hnsw", table_name="quotation_line_items")
    op.drop_column("quotation_line_items", "description_embedding")
    op.drop_index("ix_drawing_measurements_descriptor_embedding_hnsw", table_name="drawing_measurements")
    op.drop_column("drawing_measurements", "descriptor_embedding")
    op.drop_index("ix_boq_line_items_description_embedding_hnsw", table_name="boq_line_items")
    op.drop_column("boq_line_items", "description_embedding")
