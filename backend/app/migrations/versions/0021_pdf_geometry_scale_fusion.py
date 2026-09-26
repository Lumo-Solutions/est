"""Module B Phase 4a: PDF layer mapping, scale disagreement, calibration history

Adds pdf_layer_mapping_rules (project-scoped, ordered -- synthesizes
GeometricEntity.layer for PDF geometry from stroke colour/line width/dash
pattern/OCG name, since PDFs have no layers), drawing_sheets.
scale_disagreement (set by the new multi-signal fusion -- see
app/takeoff/scale.py::estimate_scale -- when two confident signals
disagree by more than 10%), and sheet_scale_calibrations (append-only
history of every scale change, auto-detected or manual two-point, so a
reviewer can see and revert to what auto-detection originally found).

Revision ID: 0021
Revises: 0020
Create Date: 2026-01-04 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from app.db.ddl import enable_rls, tenant_policies

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None

# Same role set as the rest of Module B (migrations 0009/0010) -- kept
# consistent rather than inventing a narrower tier just for this phase.
WRITE_ROLES = ["estimator", "lead_estimator", "procurement_head", "bd_director", "managing_director"]


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
    op.add_column("drawing_sheets", sa.Column("scale_disagreement", sa.Boolean, nullable=False, server_default="false"))

    op.create_table(
        "pdf_layer_mapping_rules",
        *_entity_columns(),
        sa.Column("project_id", pg.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_layer", sa.String(128), nullable=False),
        sa.Column("stroke_color", sa.String(16), nullable=True),
        sa.Column("min_line_width", sa.Numeric(8, 3), nullable=True),
        sa.Column("max_line_width", sa.Numeric(8, 3), nullable=True),
        sa.Column("dash_pattern", sa.String(16), nullable=True),
        sa.Column("ocg_name_contains", sa.String(128), nullable=True),
        sa.Column("priority", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_index("ix_pdf_layer_mapping_rules_tenant_id", "pdf_layer_mapping_rules", ["tenant_id"])
    op.create_index("ix_pdf_layer_mapping_rules_project_id", "pdf_layer_mapping_rules", ["project_id"])
    enable_rls(op, "pdf_layer_mapping_rules")
    # delete_roles is required here (unlike sheet_scale_calibrations below,
    # which is deliberately append-only): app.services.takeoff::
    # replace_pdf_layer_mapping_rules does a whole-set DELETE before
    # re-inserting. Without a DELETE policy, FORCE ROW LEVEL SECURITY's
    # default-deny means that DELETE silently matches zero rows -- found
    # while building this phase's integration test.
    tenant_policies(op, "pdf_layer_mapping_rules", write_roles=WRITE_ROLES, delete_roles=WRITE_ROLES, project_scoped=True)

    op.create_table(
        "sheet_scale_calibrations",
        *_entity_columns(),
        sa.Column("sheet_id", pg.UUID(as_uuid=True), sa.ForeignKey("drawing_sheets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("ratio", sa.Numeric(12, 6), nullable=True),
        sa.Column("source", sa.String(24), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column("set_by", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("set_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("note", sa.Text, nullable=True),
    )
    op.create_index("ix_sheet_scale_calibrations_tenant_id", "sheet_scale_calibrations", ["tenant_id"])
    op.create_index("ix_sheet_scale_calibrations_sheet_id", "sheet_scale_calibrations", ["sheet_id"])
    op.create_index("ix_sheet_scale_calibrations_project_id", "sheet_scale_calibrations", ["project_id"])
    enable_rls(op, "sheet_scale_calibrations")
    tenant_policies(op, "sheet_scale_calibrations", write_roles=WRITE_ROLES, project_scoped=True)


def downgrade() -> None:
    op.drop_table("sheet_scale_calibrations")
    op.drop_table("pdf_layer_mapping_rules")
    op.drop_column("drawing_sheets", "scale_disagreement")
