"""Phase 3b(a): many-to-one BOQ-to-measurement links.

Replaces boq_line_items.linked_measurement_id (a single optional FK) with
a join table, boq_line_item_measurements, so one BOQ line can aggregate
several measurements (e.g. a pipe run's length summed across several
sheets). Existing single links are migrated into the join table before the
old column is dropped.

Revision ID: 0013
Revises: 0012
Create Date: 2026-01-01 00:00:12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from app.db.ddl import enable_rls, tenant_policies

revision = "0013"
down_revision = "0012"
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
    op.create_table(
        "boq_line_item_measurements",
        *_entity_columns(),
        sa.Column(
            "boq_line_item_id", pg.UUID(as_uuid=True), sa.ForeignKey("boq_line_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "measurement_id", pg.UUID(as_uuid=True), sa.ForeignKey("drawing_measurements.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Denormalized from boq_line_items.project_id, same reasoning as
        # extraction_jobs/drawing_measurements (migrations 0009/0010): the
        # project_scoped RLS policy below reads this column directly, and
        # this join table has no natural project_id of its own otherwise.
        sa.Column("project_id", pg.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("boq_line_item_id", "measurement_id", name="uq_boq_line_item_measurements_pair"),
    )
    op.create_index("ix_boq_line_item_measurements_tenant_id", "boq_line_item_measurements", ["tenant_id"])
    op.create_index("ix_boq_line_item_measurements_project_id", "boq_line_item_measurements", ["project_id"])
    op.create_index("ix_boq_line_item_measurements_boq_line_item_id", "boq_line_item_measurements", ["boq_line_item_id"])
    op.create_index("ix_boq_line_item_measurements_measurement_id", "boq_line_item_measurements", ["measurement_id"])

    enable_rls(op, "boq_line_item_measurements")
    tenant_policies(
        op, "boq_line_item_measurements", write_roles=WRITE_ROLES, delete_roles=DELETE_ROLES, project_scoped=True
    )

    # Migrate existing single links into the join table before dropping
    # the column. tenant_id/created_by/updated_by copied straight from the
    # owning boq_line_items row.
    op.execute(
        "INSERT INTO boq_line_item_measurements "
        "(tenant_id, boq_line_item_id, measurement_id, project_id, created_by, updated_by) "
        "SELECT tenant_id, id, linked_measurement_id, project_id, created_by, updated_by "
        "FROM boq_line_items WHERE linked_measurement_id IS NOT NULL;"
    )

    op.drop_index("ix_boq_line_items_linked_measurement_id", table_name="boq_line_items")
    op.drop_column("boq_line_items", "linked_measurement_id")


def downgrade() -> None:
    op.add_column(
        "boq_line_items",
        sa.Column(
            "linked_measurement_id", pg.UUID(as_uuid=True),
            sa.ForeignKey("drawing_measurements.id", ondelete="SET NULL"), nullable=True,
        ),
    )
    op.create_index("ix_boq_line_items_linked_measurement_id", "boq_line_items", ["linked_measurement_id"])
    # Best-effort downgrade: a boq_line_item with more than one linked
    # measurement can only keep one of them (arbitrary pick) -- the
    # many-to-one model this migration introduces has no single-link
    # equivalent for that case, since summing several measurements into
    # one FK isn't representable.
    op.execute(
        "UPDATE boq_line_items SET linked_measurement_id = sub.measurement_id "
        "FROM (SELECT DISTINCT ON (boq_line_item_id) boq_line_item_id, measurement_id "
        "      FROM boq_line_item_measurements ORDER BY boq_line_item_id, created_at) sub "
        "WHERE boq_line_items.id = sub.boq_line_item_id;"
    )
    op.drop_table("boq_line_item_measurements")
