"""Reusable RLS DDL emitters used by Alembic migrations.

Every business table follows the same pattern (see docs/security-rls.md):
tenant isolation via app_tenant_id(), role-gated writes via app_has_role(),
and FORCE ROW LEVEL SECURITY so even the table owner can't accidentally
bypass it. Project-scoped tables add app_can_see_project(project_id).

Usage from a migration:
    from app.db.ddl import enable_rls, tenant_policies
    enable_rls(op, "vendors")
    tenant_policies(op, "vendors", write_roles=WRITE_ROLES_MODULE_A, delete_roles=[...])
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Protocol


class _Executor(Protocol):
    def execute(self, sql: str) -> Any: ...


# Executed once in migration 0001. STABLE + SECURITY INVOKER: cheap to call
# repeatedly per-row in a policy, and never runs with elevated privilege.
#
# asyncpg (used via SQLAlchemy's asyncpg dialect) refuses to run more than
# one statement per prepared execute ("cannot insert multiple commands into
# a prepared statement"), unlike psycopg2 -- so this is a LIST of
# individually-executed statements, not one multi-statement string. Every
# migration in this project follows the same rule: one CREATE/ALTER per
# op.execute() call.
HELPER_FUNCTION_STATEMENTS: list[str] = [
    """
    CREATE OR REPLACE FUNCTION app_tenant_id() RETURNS uuid
    LANGUAGE sql STABLE AS $$
        SELECT nullif(current_setting('app.tenant_id', true), '')::uuid
    $$;
    """,
    """
    CREATE OR REPLACE FUNCTION app_user_id() RETURNS uuid
    LANGUAGE sql STABLE AS $$
        SELECT nullif(current_setting('app.user_id', true), '')::uuid
    $$;
    """,
    """
    CREATE OR REPLACE FUNCTION app_roles() RETURNS text[]
    LANGUAGE sql STABLE AS $$
        SELECT coalesce(
            string_to_array(nullif(current_setting('app.roles', true), ''), ','),
            '{}'::text[]
        )
    $$;
    """,
    """
    CREATE OR REPLACE FUNCTION app_has_role(VARIADIC r text[]) RETURNS boolean
    LANGUAGE sql STABLE AS $$
        SELECT app_roles() && r
    $$;
    """,
    """
    CREATE OR REPLACE FUNCTION app_is_system() RETURNS boolean
    LANGUAGE sql STABLE AS $$
        SELECT coalesce(nullif(current_setting('app.is_system', true), ''), 'off') = 'on'
    $$;
    """,
    """
    CREATE OR REPLACE FUNCTION raise_immutable() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION 'audit_events rows are immutable (append-only, hash-chained)';
    END;
    $$;
    """,
]

# app_can_see_project() references project_members, which does not exist
# yet in migration 0001 -- Postgres validates LANGUAGE sql function bodies
# against the catalog at CREATE time (confirmed empirically; an earlier
# version of this comment assumed otherwise), so this is created separately
# by migration 0002 once project_members exists, not in the list above.
APP_CAN_SEE_PROJECT_SQL = """
CREATE OR REPLACE FUNCTION app_can_see_project(p uuid) RETURNS boolean
LANGUAGE sql STABLE AS $$
    SELECT p IS NULL
        OR app_is_system()
        OR app_has_role('managing_director', 'bd_director', 'procurement_head')
        OR EXISTS (
            SELECT 1 FROM project_members m
            WHERE m.project_id = p AND m.user_id = app_user_id()
        )
$$;
"""


def enable_rls(op: _Executor, table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")


def _role_list_sql(roles: Iterable[str]) -> str:
    quoted = ", ".join(f"'{r}'" for r in roles)
    return f"app_has_role({quoted})"


def tenant_policies(
    op: _Executor,
    table: str,
    *,
    write_roles: Iterable[str],
    delete_roles: Iterable[str] | None = None,
    project_scoped: bool = False,
    read_roles: Iterable[str] | None = None,
) -> None:
    """Emits the standard SELECT/INSERT/UPDATE/DELETE policy set for a
    tenant-scoped (optionally also project-scoped) business table."""
    project_clause = " AND app_can_see_project(project_id)" if project_scoped else ""
    read_clause = f" AND {_role_list_sql(read_roles)}" if read_roles else ""

    # app_is_system() bypasses every clause below, not just SELECT: Celery
    # beat/maintenance tasks (certificate-expiry scans, stale-job reaping)
    # and the seed CLI all write as a system actor with no role claims, and
    # would otherwise be locked out of every RLS-protected table -- a gap
    # an earlier version of this helper had (system bypass on SELECT only).
    op.execute(
        f"CREATE POLICY {table}_tenant_read ON {table} FOR SELECT "
        f"USING (app_is_system() OR (tenant_id = app_tenant_id(){project_clause}{read_clause}));"
    )
    op.execute(
        f"CREATE POLICY {table}_tenant_write ON {table} FOR INSERT "
        f"WITH CHECK (app_is_system() OR (tenant_id = app_tenant_id() "
        f"AND {_role_list_sql(write_roles)}{project_clause}));"
    )
    op.execute(
        f"CREATE POLICY {table}_tenant_update ON {table} FOR UPDATE "
        f"USING (app_is_system() OR (tenant_id = app_tenant_id() "
        f"AND {_role_list_sql(write_roles)}{project_clause})) "
        f"WITH CHECK (app_is_system() OR tenant_id = app_tenant_id());"
    )
    if delete_roles:
        op.execute(
            f"CREATE POLICY {table}_tenant_delete ON {table} FOR DELETE "
            f"USING (app_is_system() OR (tenant_id = app_tenant_id() "
            f"AND {_role_list_sql(delete_roles)}{project_clause}));"
        )


def audit_insert_only_policies(op: _Executor, table: str) -> None:
    """audit_events: any authenticated actor may INSERT (via the audit
    service, same transaction as the business write); only the four
    lead_estimator+ roles may SELECT; there is deliberately no UPDATE/DELETE
    policy at all, on top of the REVOKE + trigger immutability guards."""
    op.execute(
        f"CREATE POLICY {table}_tenant_read ON {table} FOR SELECT "
        f"USING (app_is_system() OR (tenant_id = app_tenant_id() AND "
        f"{_role_list_sql(['lead_estimator', 'procurement_head', 'bd_director', 'managing_director'])}));"
    )
    op.execute(
        f"CREATE POLICY {table}_insert ON {table} FOR INSERT "
        f"WITH CHECK (tenant_id = app_tenant_id() OR app_is_system());"
    )
