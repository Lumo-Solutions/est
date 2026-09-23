"""Connects as the real installtec_app role (never the owner) and proves
RLS tenant isolation the same way it was manually verified against a live
container during development: zero rows visible with no GUC set, a row
becomes visible once app.tenant_id matches, and invisible again once it's
switched to a different tenant.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.asyncio

TENANT_A = "8f14e45f-ceea-4e97-8d0c-3d3b3f3c1a00"
TENANT_B = "00000000-0000-0000-0000-000000000099"


async def _set_guc(session, *, tenant_id: str, user_id: str, roles: str, is_system: str = "off") -> None:
    await session.execute(
        text(
            "SELECT set_config('app.tenant_id', :t, false), set_config('app.user_id', :u, false), "
            "set_config('app.roles', :r, false), set_config('app.is_system', :s, false)"
        ),
        {"t": tenant_id, "u": user_id, "r": roles, "s": is_system},
    )


async def test_no_guc_set_returns_zero_rows(rls_session):
    result = await rls_session.execute(text("SELECT count(*) FROM vendors"))
    assert result.scalar_one() == 0


async def test_row_visible_only_to_owning_tenant(rls_session):
    user_id = str(uuid.uuid4())
    await _set_guc(rls_session, tenant_id=TENANT_A, user_id=user_id, roles="lead_estimator")
    await rls_session.execute(
        text(
            "INSERT INTO vendors (tenant_id, legal_name, normalized_name, status) "
            "VALUES (:t, 'Isolation Test Vendor', 'ISOLATION TEST VENDOR', 'draft')"
        ),
        {"t": TENANT_A},
    )

    visible_same_tenant = await rls_session.execute(text("SELECT count(*) FROM vendors"))
    assert visible_same_tenant.scalar_one() == 1

    await _set_guc(rls_session, tenant_id=TENANT_B, user_id=user_id, roles="lead_estimator")
    visible_other_tenant = await rls_session.execute(text("SELECT count(*) FROM vendors"))
    assert visible_other_tenant.scalar_one() == 0


async def test_insert_with_foreign_tenant_id_is_rejected(rls_session):
    """WITH CHECK enforces tenant_id = app_tenant_id() -- a caller cannot
    write a row into a tenant they aren't scoped to, even by supplying that
    tenant's UUID directly in the INSERT.

    A failed statement aborts the rest of the enclosing Postgres
    transaction, so the attempt runs inside a SAVEPOINT (begin_nested()) --
    without it, this assertion would be correct but would also poison the
    rls_session fixture's outer transaction for any statement after it."""
    await _set_guc(rls_session, tenant_id=TENANT_A, user_id=str(uuid.uuid4()), roles="lead_estimator")
    with pytest.raises(Exception, match=r"(?i)row-level security"):
        async with rls_session.begin_nested():
            await rls_session.execute(
                text(
                    "INSERT INTO vendors (tenant_id, legal_name, normalized_name, status) "
                    "VALUES (:t, 'Cross Tenant Insert', 'CROSS TENANT INSERT', 'draft')"
                ),
                {"t": TENANT_B},
            )


async def test_system_context_bypasses_tenant_filter_on_select(rls_session):
    user_id = str(uuid.uuid4())
    await _set_guc(rls_session, tenant_id=TENANT_A, user_id=user_id, roles="lead_estimator")
    await rls_session.execute(
        text(
            "INSERT INTO vendors (tenant_id, legal_name, normalized_name, status) "
            "VALUES (:t, 'System Visible Vendor', 'SYSTEM VISIBLE VENDOR', 'draft')"
        ),
        {"t": TENANT_A},
    )

    await _set_guc(rls_session, tenant_id=TENANT_B, user_id=user_id, roles="", is_system="on")
    result = await rls_session.execute(text("SELECT count(*) FROM vendors"))
    assert result.scalar_one() >= 1


async def test_system_context_can_write_without_role_claims(rls_session):
    """Regression test for the bug where app_is_system() only bypassed the
    SELECT policy: a system actor (Celery beat tasks, the seed CLI) has no
    role claims at all and must still be able to INSERT/UPDATE/DELETE."""
    await _set_guc(rls_session, tenant_id=TENANT_A, user_id=str(uuid.uuid4()), roles="", is_system="on")
    await rls_session.execute(
        text(
            "INSERT INTO trade_nodes (tenant_id, code, name, path) "
            "VALUES (:t, 'SYS_TEST', 'System Insert Test', 'placeholder')"
        ),
        {"t": TENANT_A},
    )
    result = await rls_session.execute(
        text("SELECT count(*) FROM trade_nodes WHERE code = 'SYS_TEST'")
    )
    assert result.scalar_one() == 1
