"""configurable trade taxonomy (ltree hierarchy)

Revision ID: 0004
Revises: 0003
Create Date: 2026-01-01 00:00:03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from app.db.ddl import enable_rls, tenant_policies

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

_PATH_TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION trade_nodes_path_trg() RETURNS trigger
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
        SELECT path INTO parent_path FROM trade_nodes WHERE id = NEW.parent_id;
        IF parent_path IS NULL THEN
            RAISE EXCEPTION 'parent_id % does not exist', NEW.parent_id;
        END IF;
        -- Cycle check: reject if the proposed new parent is the node being
        -- moved itself, or any of that node's current descendants (i.e.
        -- parent_path falls within OLD.path's subtree). An earlier version
        -- of this check had the ancestor/descendant relationship backwards
        -- (`OLD.path <@ (parent_path || label)`, comparing OLD.path against
        -- a path that doesn't correspond to anything real) and silently
        -- allowed cycles; this was caught by
        -- tests/integration/test_taxonomy_ltree.py::test_reparenting_under_own_subtree_is_rejected.
        IF TG_OP = 'UPDATE' AND parent_path <@ OLD.path THEN
            RAISE EXCEPTION 'cannot reparent a node under its own subtree';
        END IF;
        NEW.path := parent_path || label;
        NEW.level := nlevel(NEW.path) - 1;
    END IF;

    IF TG_OP = 'UPDATE' AND OLD.path IS DISTINCT FROM NEW.path THEN
        old_path := OLD.path;
        UPDATE trade_nodes
        SET path = NEW.path || subpath(path, nlevel(old_path))
        WHERE path <@ old_path AND id <> NEW.id;
    END IF;

    RETURN NEW;
END;
$$;
"""


def upgrade() -> None:
    op.create_table(
        "trade_nodes",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_id", pg.UUID(as_uuid=True), sa.ForeignKey("trade_nodes.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("level", sa.Integer, nullable=False, server_default="0"),
        sa.Column("path", sa.Text, nullable=False),  # widened to ltree below (not a native SA type)
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("attributes", pg.JSONB, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", pg.UUID(as_uuid=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "parent_id", "code", name="uq_trade_nodes_tenant_parent_code"),
    )
    # ltree isn't a first-class SQLAlchemy/Alembic column type -- create as
    # text then ALTER to ltree so op.create_table can stay declarative.
    op.execute("ALTER TABLE trade_nodes ALTER COLUMN path TYPE ltree USING path::ltree;")
    op.create_index("ix_trade_nodes_tenant_id", "trade_nodes", ["tenant_id"])
    op.execute("CREATE INDEX ix_trade_nodes_path ON trade_nodes USING gist (path);")

    op.execute(_PATH_TRIGGER_SQL)
    op.execute(
        "CREATE TRIGGER trade_nodes_path_trg BEFORE INSERT OR UPDATE OF parent_id ON trade_nodes "
        "FOR EACH ROW EXECUTE FUNCTION trade_nodes_path_trg();"
    )

    enable_rls(op, "trade_nodes")
    tenant_policies(
        op,
        "trade_nodes",
        write_roles=["lead_estimator", "procurement_head", "managing_director"],
        delete_roles=["managing_director"],
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trade_nodes_path_trg ON trade_nodes;")
    op.execute("DROP FUNCTION IF EXISTS trade_nodes_path_trg() CASCADE;")
    op.drop_table("trade_nodes")
