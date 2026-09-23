from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

pytestmark = pytest.mark.asyncio

TENANT = "8f14e45f-ceea-4e97-8d0c-3d3b3f3c1a00"


@pytest_asyncio.fixture(autouse=True)
async def _set_guc(rls_session) -> None:
    await rls_session.execute(
        text(
            "SELECT set_config('app.tenant_id', :t, false), set_config('app.user_id', :u, false), "
            "set_config('app.roles', 'procurement_head', false), set_config('app.is_system', 'off', false)"
        ),
        {"t": TENANT, "u": str(uuid.uuid4())},
    )


async def _create_vendor(session, name: str) -> str:
    result = await session.execute(
        text(
            "INSERT INTO vendors (tenant_id, legal_name, normalized_name, status) "
            "VALUES (:t, :n, :n, 'draft') RETURNING id"
        ),
        {"t": TENANT, "n": name},
    )
    return str(result.scalar_one())


async def test_overlapping_open_ended_periods_rejected(rls_session):
    vendor_id = await _create_vendor(rls_session, "PREQUAL VENDOR 1")
    await rls_session.execute(
        text(
            "INSERT INTO vendor_prequalifications (tenant_id, vendor_id, status, effective_period) "
            "VALUES (:t, :v, 'approved', daterange('2026-01-01', null))"
        ),
        {"t": TENANT, "v": vendor_id},
    )
    # pytest.raises must be the OUTER context manager -- see the comment on
    # test_update_is_rejected in test_audit_chain_db.py for why.
    with pytest.raises(Exception, match=r"(?i)exclusion"):
        async with rls_session.begin_nested():
            await rls_session.execute(
                text(
                    "INSERT INTO vendor_prequalifications (tenant_id, vendor_id, status, effective_period) "
                    "VALUES (:t, :v, 'suspended', daterange('2026-06-01', null))"
                ),
                {"t": TENANT, "v": vendor_id},
            )


async def test_non_overlapping_sequential_periods_allowed(rls_session):
    """The correct close-and-open pattern: end the first period exactly
    where the second begins."""
    vendor_id = await _create_vendor(rls_session, "PREQUAL VENDOR 2")
    await rls_session.execute(
        text(
            "INSERT INTO vendor_prequalifications (tenant_id, vendor_id, status, effective_period) "
            "VALUES (:t, :v, 'approved', daterange('2026-01-01', '2026-06-01'))"
        ),
        {"t": TENANT, "v": vendor_id},
    )
    await rls_session.execute(
        text(
            "INSERT INTO vendor_prequalifications (tenant_id, vendor_id, status, effective_period) "
            "VALUES (:t, :v, 'suspended', daterange('2026-06-01', null))"
        ),
        {"t": TENANT, "v": vendor_id},
    )
    count = await rls_session.execute(
        text("SELECT count(*) FROM vendor_prequalifications WHERE vendor_id = :v"), {"v": vendor_id}
    )
    assert count.scalar_one() == 2


async def test_different_scope_trade_nodes_do_not_conflict(rls_session):
    vendor_id = await _create_vendor(rls_session, "PREQUAL VENDOR 3")
    node_a = (
        await rls_session.execute(
            text(
                "INSERT INTO trade_nodes (tenant_id, code, name, path) "
                "VALUES (:t, 'PQ-A', 'PQ-A', 'placeholder') RETURNING id"
            ),
            {"t": TENANT},
        )
    ).scalar_one()
    node_b = (
        await rls_session.execute(
            text(
                "INSERT INTO trade_nodes (tenant_id, code, name, path) "
                "VALUES (:t, 'PQ-B', 'PQ-B', 'placeholder') RETURNING id"
            ),
            {"t": TENANT},
        )
    ).scalar_one()

    for node_id in (node_a, node_b):
        await rls_session.execute(
            text(
                "INSERT INTO vendor_prequalifications (tenant_id, vendor_id, status, scope_trade_node_id, "
                "effective_period) VALUES (:t, :v, 'approved', :n, daterange('2026-01-01', null))"
            ),
            {"t": TENANT, "v": vendor_id, "n": node_id},
        )
    count = await rls_session.execute(
        text("SELECT count(*) FROM vendor_prequalifications WHERE vendor_id = :v"), {"v": vendor_id}
    )
    assert count.scalar_one() == 2


async def test_get_prequalification_as_of_picks_the_covering_period(rls_session):
    vendor_id = await _create_vendor(rls_session, "PREQUAL VENDOR 4")
    await rls_session.execute(
        text(
            "INSERT INTO vendor_prequalifications (tenant_id, vendor_id, status, effective_period) "
            "VALUES (:t, :v, 'approved', daterange('2026-01-01', '2026-06-01'))"
        ),
        {"t": TENANT, "v": vendor_id},
    )
    await rls_session.execute(
        text(
            "INSERT INTO vendor_prequalifications (tenant_id, vendor_id, status, effective_period) "
            "VALUES (:t, :v, 'suspended', daterange('2026-06-01', null))"
        ),
        {"t": TENANT, "v": vendor_id},
    )
    status_in_march = await rls_session.execute(
        text(
            "SELECT status FROM vendor_prequalifications "
            "WHERE vendor_id = :v AND effective_period @> DATE '2026-03-01'"
        ),
        {"v": vendor_id},
    )
    assert status_in_march.scalar_one() == "approved"

    status_in_august = await rls_session.execute(
        text(
            "SELECT status FROM vendor_prequalifications "
            "WHERE vendor_id = :v AND effective_period @> DATE '2026-08-01'"
        ),
        {"v": vendor_id},
    )
    assert status_in_august.scalar_one() == "suspended"
