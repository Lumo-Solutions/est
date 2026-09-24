"""Module B Phase 3: BOQ reconciliation -- hierarchical line items linked to
drawing_measurements, with a persisted three-class discrepancy flag.

Revision ID: 0011
Revises: 0010
Create Date: 2026-01-01 00:00:10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from app.db.ddl import enable_rls, tenant_policies

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

# Structural edits (create/edit/reparent line items, i.e. building the
# tender BOQ) are more senior than day-to-day reconciliation work -- this
# mirrors trade_nodes' write_roles (0004_taxonomy.py), the closest existing
# precedent for "editing hierarchical master data". Linking a measurement /
# recomputing a discrepancy is a normal estimating task, gated separately
# in the service layer at the WRITE_ROLES level used everywhere else in
# Module B (see app/services/boq.py) -- there is deliberately no separate
# DB-level role split for that, since both operations write the same
# columns on the same row and RLS policies are per-table, not per-column.
WRITE_ROLES = ["lead_estimator", "procurement_head", "managing_director"]
DELETE_ROLES = ["lead_estimator", "procurement_head", "managing_director"]

# Adapted from trade_nodes_path_trg (0004_taxonomy.py) for a project-scoped
# hierarchy instead of a tenant-scoped one: every parent_id lookup and the
# cross-row path-prefix UPDATE on reparenting are additionally scoped to
# project_id, since (unlike trade_nodes, where cross-tenant visibility is
# never possible even for a query inside the trigger, thanks to RLS)
# BOQ_WRITE_ROLES here includes roles -- lead_estimator, procurement_head,
# managing_director -- that bypass project_members entirely
# (app_can_see_project()), so RLS alone would NOT stop a privileged actor
# from cross-linking BOQ items across two different projects via a
# mistaken parent_id.
_PATH_TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION boq_line_items_path_trg() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    parent_path ltree;
    old_path ltree;
    label text;
BEGIN
    label := 'n' || replace(NEW.id::text, '-', '_');

    IF NEW.parent_id IS NULL THEN
        NEW.path := label::ltree;
        NEW.level := 0;
    ELSE
        SELECT path INTO parent_path FROM boq_line_items
            WHERE id = NEW.parent_id AND project_id = NEW.project_id;
        IF parent_path IS NULL THEN
            RAISE EXCEPTION 'parent_id % does not exist in project %', NEW.parent_id, NEW.project_id;
        END IF;
        IF TG_OP = 'UPDATE' AND parent_path <@ OLD.path THEN
            RAISE EXCEPTION 'cannot reparent a line item under its own subtree';
        END IF;
        NEW.path := parent_path || label;
        NEW.level := nlevel(NEW.path) - 1;
    END IF;

    IF TG_OP = 'UPDATE' AND OLD.path IS DISTINCT FROM NEW.path THEN
        old_path := OLD.path;
        UPDATE boq_line_items
        SET path = NEW.path || subpath(path, nlevel(old_path))
        WHERE path <@ old_path AND id <> NEW.id AND project_id = NEW.project_id;
    END IF;

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
        "boq_line_items",
        *_entity_columns(),
        sa.Column("project_id", pg.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parent_id", pg.UUID(as_uuid=True), sa.ForeignKey("boq_line_items.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("item_no", sa.String(32), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("uom", sa.String(16), nullable=True),
        sa.Column("boq_quantity", sa.Numeric(18, 4), nullable=True),
        sa.Column("level", sa.Integer, nullable=False, server_default="0"),
        sa.Column("path", sa.Text, nullable=False),  # widened to ltree below
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        # Reconciliation, computed by app/boq/reconciliation.py and
        # persisted by app/services/boq.py -- never written directly by a
        # request handler.
        sa.Column(
            "linked_measurement_id", pg.UUID(as_uuid=True),
            sa.ForeignKey("drawing_measurements.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("variance", sa.Numeric(18, 4), nullable=True),
        sa.Column("variance_pct", sa.Numeric(8, 3), nullable=True),
        sa.Column("discrepancy_class", sa.String(16), nullable=True),
        sa.Column("reconciliation_note", sa.Text, nullable=True),
        sa.Column("reconciled_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.UniqueConstraint("project_id", "parent_id", "item_no", name="uq_boq_line_items_project_parent_item_no"),
    )
    op.execute("ALTER TABLE boq_line_items ALTER COLUMN path TYPE ltree USING path::ltree;")
    op.create_index("ix_boq_line_items_tenant_id", "boq_line_items", ["tenant_id"])
    op.create_index("ix_boq_line_items_project_id", "boq_line_items", ["project_id"])
    op.create_index("ix_boq_line_items_parent_id", "boq_line_items", ["parent_id"])
    op.create_index("ix_boq_line_items_linked_measurement_id", "boq_line_items", ["linked_measurement_id"])
    op.execute("CREATE INDEX ix_boq_line_items_path ON boq_line_items USING gist (path);")

    op.execute(_PATH_TRIGGER_SQL)
    op.execute(
        "CREATE TRIGGER boq_line_items_path_trg BEFORE INSERT OR UPDATE OF parent_id ON boq_line_items "
        "FOR EACH ROW EXECUTE FUNCTION boq_line_items_path_trg();"
    )

    enable_rls(op, "boq_line_items")
    tenant_policies(op, "boq_line_items", write_roles=WRITE_ROLES, delete_roles=DELETE_ROLES, project_scoped=True)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS boq_line_items_path_trg ON boq_line_items;")
    op.execute("DROP FUNCTION IF EXISTS boq_line_items_path_trg() CASCADE;")
    op.drop_table("boq_line_items")
