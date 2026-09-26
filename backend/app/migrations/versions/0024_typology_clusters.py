"""Module B Phase 4c: clustered typology recognition

Adds typology_clusters (one row per detected/confirmed repeating-unit
group), typology_cluster_instances (one row per GROUP within a cluster --
"type A", "type B", ... -- not one row per raw detected repeat: a group's
`instance_count` is how many repeats it represents, `source_handles`
(JSONB) lists every repeat's own DrawingEntity.handle for traceability,
and sheet_id/bbox_* give ONE representative location for the split pane,
not an exhaustive per-repeat location list -- see
docs/module-b-phase4-plan.md §4c and its own "instance_count ... a whole
group, not per-instance-row" note, and app/services/typology.py for the
detection/confirm logic this backs), and typology_variant_deltas (an
explicit, quantifiable delta against a real BOQ item for a non-master
group, e.g. "+1 maid room").

typology_clusters.master_instance_id is a nullable FK to
typology_cluster_instances.id, set only after the cluster's own instance
rows exist (detect_clusters() creates the cluster row first with it NULL,
inserts instances, then updates it) -- the two tables reference each
other, so this can't be NOT NULL at creation time.

Revision ID: 0024
Revises: 0023
Create Date: 2026-01-07 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from app.db.ddl import enable_rls, tenant_policies

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None

# Detecting/confirming clusters is structural, project-level configuration
# work (same tier as boq_tolerances/drawing_layer_trade_mappings), not
# day-to-day operational estimating -- the plan doc's own endpoint list
# names lead_estimator+ explicitly for detect/confirm.
WRITE_ROLES = ["lead_estimator", "procurement_head", "managing_director"]


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
        "typology_clusters",
        *_entity_columns(),
        sa.Column("project_id", pg.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="proposed"),
        sa.Column("master_instance_id", pg.UUID(as_uuid=True), nullable=True),  # FK added below, after the child table exists
        sa.Column("detection_method", sa.String(24), nullable=False),
        # The block_name (DXF) or geometry hash (PDF) that produced this
        # cluster -- lets a re-run of detect_clusters() recognise "this
        # exact grouping already has a proposed/confirmed cluster" instead
        # of creating a duplicate.
        sa.Column("detection_key", sa.String(128), nullable=False),
        sa.Column("tolerance_pct", sa.Numeric(6, 3), nullable=False),
        sa.Column("confirmed_by", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("confirmed_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_typology_clusters_tenant_id", "typology_clusters", ["tenant_id"])
    op.create_index("ix_typology_clusters_project_id", "typology_clusters", ["project_id"])
    op.create_index("ix_typology_clusters_project_method_key", "typology_clusters", ["project_id", "detection_method", "detection_key"])

    op.create_table(
        "typology_cluster_instances",
        *_entity_columns(),
        sa.Column("cluster_id", pg.UUID(as_uuid=True), sa.ForeignKey("typology_clusters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", pg.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sheet_id", pg.UUID(as_uuid=True), sa.ForeignKey("drawing_sheets.id", ondelete="SET NULL"), nullable=True),
        sa.Column("bbox_min_x", sa.Numeric(18, 6), nullable=True),
        sa.Column("bbox_min_y", sa.Numeric(18, 6), nullable=True),
        sa.Column("bbox_max_x", sa.Numeric(18, 6), nullable=True),
        sa.Column("bbox_max_y", sa.Numeric(18, 6), nullable=True),
        sa.Column("group_label", sa.String(64), nullable=False),
        sa.Column("instance_count", sa.Integer, nullable=False),
        sa.Column("source_handles", pg.JSONB, nullable=False, server_default="[]"),
        sa.UniqueConstraint("cluster_id", "group_label", name="uq_typology_cluster_instances_cluster_group"),
    )
    op.create_index("ix_typology_cluster_instances_tenant_id", "typology_cluster_instances", ["tenant_id"])
    op.create_index("ix_typology_cluster_instances_project_id", "typology_cluster_instances", ["project_id"])
    op.create_index("ix_typology_cluster_instances_cluster_id", "typology_cluster_instances", ["cluster_id"])

    op.create_foreign_key(
        "fk_typology_clusters_master_instance", "typology_clusters", "typology_cluster_instances",
        ["master_instance_id"], ["id"], ondelete="SET NULL",
    )

    op.create_table(
        "typology_variant_deltas",
        *_entity_columns(),
        sa.Column("cluster_id", pg.UUID(as_uuid=True), sa.ForeignKey("typology_clusters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", pg.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("group_label", sa.String(64), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        # SET NULL, not RESTRICT/CASCADE -- same "an optional reference to
        # something that might be deleted later" precedent as
        # boq_line_items.import_batch_id (migration 0020): a deleted BOQ
        # item shouldn't take the whole variant delta down with it.
        sa.Column("boq_line_item_id", pg.UUID(as_uuid=True), sa.ForeignKey("boq_line_items.id", ondelete="SET NULL"), nullable=True),
        sa.Column("quantity_delta", sa.Numeric(18, 4), nullable=True),
        sa.Column("unit", sa.String(16), nullable=True),
    )
    op.create_index("ix_typology_variant_deltas_tenant_id", "typology_variant_deltas", ["tenant_id"])
    op.create_index("ix_typology_variant_deltas_project_id", "typology_variant_deltas", ["project_id"])
    op.create_index("ix_typology_variant_deltas_cluster_id", "typology_variant_deltas", ["cluster_id"])

    for table in ("typology_clusters", "typology_cluster_instances", "typology_variant_deltas"):
        enable_rls(op, table)
        tenant_policies(op, table, write_roles=WRITE_ROLES, delete_roles=WRITE_ROLES, project_scoped=True)


def downgrade() -> None:
    op.drop_table("typology_variant_deltas")
    op.drop_constraint("fk_typology_clusters_master_instance", "typology_clusters", type_="foreignkey")
    op.drop_table("typology_cluster_instances")
    op.drop_table("typology_clusters")
