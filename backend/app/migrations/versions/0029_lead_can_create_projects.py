"""lead_estimator may create projects

The API and UI previously let only bd_director and managing_director create a
project, and migration 0002 encoded the same list in the projects INSERT
policy. Widening the API check alone would make every lead_estimator create
a 500 (RLS violation), because RLS is the real enforcement boundary
(docs/security-rls.md) -- so the policy has to change with it.

Only INSERT changes. projects_tenant_update (edit location) keeps its
bd_director/managing_director list, and projects_tenant_delete is untouched
(managing_director). The creator becomes the project's `owner` member in
the same transaction (services/projects.py::create_project).

Revision ID: 0029
Revises: 0028
Create Date: 2026-09-29 00:00:00
"""

from __future__ import annotations

from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def _policy(roles: list[str]) -> str:
    quoted = ", ".join(f"'{r}'" for r in roles)
    return (
        "CREATE POLICY projects_tenant_write ON projects FOR INSERT "
        "WITH CHECK (app_is_system() OR (tenant_id = app_tenant_id() "
        f"AND app_has_role({quoted})));"
    )


def upgrade() -> None:
    op.execute("DROP POLICY projects_tenant_write ON projects;")
    op.execute(_policy(["bd_director", "managing_director", "lead_estimator"]))


def downgrade() -> None:
    op.execute("DROP POLICY projects_tenant_write ON projects;")
    op.execute(_policy(["bd_director", "managing_director"]))
