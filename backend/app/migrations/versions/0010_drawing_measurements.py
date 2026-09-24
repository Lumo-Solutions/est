"""Module B Phase 2b: persisted geometry-extractor measurements

Revision ID: 0010
Revises: 0009
Create Date: 2026-01-01 00:00:09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from app.db.ddl import enable_rls, tenant_policies

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

# Same role set as the rest of Module B (migration 0009) -- measurements
# are written only by the extract_geometry_measurements Celery task
# (system actor, bypasses RLS via app_is_system()), so these roles only
# ever gate the (currently nonexistent) possibility of a request-path
# write, matching the other takeoff tables for consistency.
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
    op.create_table(
        "drawing_measurements",
        *_entity_columns(),
        sa.Column("drawing_id", pg.UUID(as_uuid=True), sa.ForeignKey("drawings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sheet_id", pg.UUID(as_uuid=True), sa.ForeignKey("drawing_sheets.id", ondelete="CASCADE"), nullable=False),
        # Denormalized from drawings.project_id for the project-scoped RLS
        # policy below (app_can_see_project(project_id) reads this column
        # directly) -- same pattern as extraction_jobs.project_id in 0009.
        sa.Column("project_id", pg.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("capability", sa.String(32), nullable=False),
        sa.Column("kind", sa.String(48), nullable=False),
        sa.Column("value", sa.Numeric(18, 6), nullable=False),
        sa.Column("unit", sa.String(16), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column("source_entity_ids", pg.JSONB, nullable=False, server_default="[]"),
        sa.Column("extractor_metadata", pg.JSONB, nullable=True),
    )
    op.create_index("ix_drawing_measurements_tenant_id", "drawing_measurements", ["tenant_id"])
    op.create_index("ix_drawing_measurements_project_id", "drawing_measurements", ["project_id"])
    op.create_index("ix_drawing_measurements_drawing_id", "drawing_measurements", ["drawing_id"])
    op.create_index("ix_drawing_measurements_sheet_id", "drawing_measurements", ["sheet_id"])
    op.create_index("ix_drawing_measurements_capability", "drawing_measurements", ["capability"])

    enable_rls(op, "drawing_measurements")
    tenant_policies(
        op, "drawing_measurements", write_roles=WRITE_ROLES, delete_roles=DELETE_ROLES, project_scoped=True
    )


def downgrade() -> None:
    op.drop_table("drawing_measurements")
