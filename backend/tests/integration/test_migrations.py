"""Runs the full migration chain against a real pgvector/pgvector:pg16
container (via conftest.postgres_container), then asserts every business
table came out with RLS enabled and forced -- the property the whole
security model depends on. Downgrade-to-base is intentionally not exercised
here: this is a young, unreleased schema with no production data to
preserve, so `downgrade()` functions exist for local `alembic downgrade -1`
convenience during development, not as a tested rollback path.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.asyncio


async def test_all_tables_have_rls_enabled_and_forced(app_engine, postgres_container):
    async with app_engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE relkind = 'r' AND relnamespace = 'public'::regnamespace "
                "AND relname NOT IN ('alembic_version', 'tenants')"
            )
        )
        rows = result.all()
    assert rows, "expected business tables to exist after migration"
    for relname, rls_enabled, rls_forced in rows:
        assert rls_enabled, f"{relname} does not have RLS enabled"
        assert rls_forced, f"{relname} does not have RLS forced (owner could bypass it)"


async def test_tenants_table_has_no_rls_by_design(app_engine, postgres_container):
    async with app_engine.connect() as conn:
        result = await conn.execute(
            text("SELECT relrowsecurity FROM pg_class WHERE relname = 'tenants'")
        )
        (rls_enabled,) = result.one()
    assert rls_enabled is False


async def test_expected_extensions_installed(app_engine, postgres_container):
    async with app_engine.connect() as conn:
        result = await conn.execute(text("SELECT extname FROM pg_extension"))
        installed = {row[0] for row in result.all()}
    for ext in ("vector", "pg_trgm", "btree_gist", "pgcrypto", "ltree", "unaccent", "citext"):
        assert ext in installed


async def test_rls_helper_functions_exist(app_engine, postgres_container):
    async with app_engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT proname FROM pg_proc WHERE proname IN "
                "('app_tenant_id','app_user_id','app_roles','app_has_role','app_is_system',"
                "'app_can_see_project','raise_immutable')"
            )
        )
        found = {row[0] for row in result.all()}
    assert found == {
        "app_tenant_id", "app_user_id", "app_roles", "app_has_role",
        "app_is_system", "app_can_see_project", "raise_immutable",
    }


async def test_app_role_is_not_table_owner(app_engine, postgres_container):
    """The single most important RLS precondition: if installtec_app owned
    the tables, FORCE ROW LEVEL SECURITY would not apply to it at all."""
    async with app_engine.connect() as conn:
        result = await conn.execute(
            text("SELECT tableowner FROM pg_tables WHERE tablename = 'vendors'")
        )
        (owner,) = result.one()
    assert owner != "installtec_app"
    assert owner == "installtec_migrator"
