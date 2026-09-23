"""extensions, RLS helper functions, immutability trigger function

Revision ID: 0001
Revises:
Create Date: 2026-01-01 00:00:00
"""

from __future__ import annotations

from alembic import op

from app.db.ddl import HELPER_FUNCTION_STATEMENTS

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

EXTENSIONS = ["vector", "pg_trgm", "btree_gist", "pgcrypto", "ltree", "unaccent", "citext"]


def upgrade() -> None:
    for ext in EXTENSIONS:
        op.execute(f"CREATE EXTENSION IF NOT EXISTS {ext};")
    for statement in HELPER_FUNCTION_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS raise_immutable() CASCADE;")
    op.execute("DROP FUNCTION IF EXISTS app_can_see_project(uuid) CASCADE;")
    op.execute("DROP FUNCTION IF EXISTS app_is_system() CASCADE;")
    op.execute("DROP FUNCTION IF EXISTS app_has_role(text[]) CASCADE;")
    op.execute("DROP FUNCTION IF EXISTS app_roles() CASCADE;")
    op.execute("DROP FUNCTION IF EXISTS app_user_id() CASCADE;")
    op.execute("DROP FUNCTION IF EXISTS app_tenant_id() CASCADE;")
