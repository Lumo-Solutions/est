"""tenants, users, projects, project_members (+ RLS)

Revision ID: 0002
Revises: 0001
Create Date: 2026-01-01 00:00:01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from app.db.ddl import APP_CAN_SEE_PROJECT_SQL, enable_rls, tenant_policies

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

WRITE_ROLES_A = ["lead_estimator", "procurement_head", "bd_director", "managing_director"]


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("slug", sa.String(63), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("base_currency", sa.String(3), nullable=False, server_default="AED"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "users",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("keycloak_sub", sa.String(255), nullable=False),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("last_login_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("roles_cache", pg.ARRAY(sa.Text), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", pg.UUID(as_uuid=True), nullable=True),
        sa.UniqueConstraint("keycloak_sub", name="uq_users_keycloak_sub"),
    )
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])

    op.create_table(
        "projects",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("client_name", sa.String(255), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="prospect"),
        sa.Column("tender_ref", sa.String(128), nullable=True),
        sa.Column("submission_due_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("base_currency", sa.String(3), nullable=False, server_default="AED"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", pg.UUID(as_uuid=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "code", name="uq_projects_tenant_code"),
    )
    op.create_index("ix_projects_tenant_id", "projects", ["tenant_id"])

    op.create_table(
        "project_members",
        sa.Column("project_id", pg.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("project_role", sa.String(64), nullable=True),
    )
    op.create_index("ix_project_members_tenant_id", "project_members", ["tenant_id"])

    # project_members now exists -- safe to create app_can_see_project().
    op.execute(APP_CAN_SEE_PROJECT_SQL)

    # tenants itself has no tenant_id column -- readable by any authenticated
    # user (app filters by known tenant), no per-row RLS.
    for table, write_roles, delete_roles in (
        ("users", WRITE_ROLES_A, None),
        ("projects", ["bd_director", "managing_director"], ["managing_director"]),
        ("project_members", WRITE_ROLES_A, WRITE_ROLES_A),
    ):
        enable_rls(op, table)
        tenant_policies(op, table, write_roles=write_roles, delete_roles=delete_roles)


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS app_can_see_project(uuid) CASCADE;")
    op.drop_table("project_members")
    op.drop_table("projects")
    op.drop_table("users")
    op.drop_table("tenants")
