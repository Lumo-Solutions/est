from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

pytestmark = pytest.mark.asyncio

TENANT = "8f14e45f-ceea-4e97-8d0c-3d3b3f3c1a00"


@pytest_asyncio.fixture(autouse=True)
async def _set_guc(rls_session) -> None:
    """autouse so every test in this module runs with RLS context already
    set -- a plain helper function that has to be called manually at the
    top of each test is too easy to forget (see the earlier bug this became
    after review: several tests here originally never called it)."""
    await rls_session.execute(
        text(
            "SELECT set_config('app.tenant_id', :t, false), set_config('app.user_id', :u, false), "
            "set_config('app.roles', 'lead_estimator', false), set_config('app.is_system', 'off', false)"
        ),
        {"t": TENANT, "u": str(uuid.uuid4())},
    )


async def _create_item(session, code: str) -> str:
    result = await session.execute(
        text(
            "INSERT INTO cost_items (tenant_id, code, description, uom, item_type) "
            "VALUES (:t, :c, 'test item', 'm3', 'material') RETURNING id"
        ),
        {"t": TENANT, "c": code},
    )
    return str(result.scalar_one())


async def test_overlapping_currently_believed_rates_rejected(rls_session):
    item_id = await _create_item(rls_session, "BITEMP-1")
    await rls_session.execute(
        text(
            "INSERT INTO cost_item_rates (tenant_id, cost_item_id, scope_key, currency, total_rate, "
            "valid_period, sys_period, source) VALUES "
            "(:t, :i, 'GLOBAL', 'AED', 350, daterange('2026-01-01','2026-06-01'), "
            "tstzrange(now(), null), 'manual')"
        ),
        {"t": TENANT, "i": item_id},
    )
    # pytest.raises must be the OUTER context manager -- see the comment on
    # test_update_is_rejected in test_audit_chain_db.py for why.
    with pytest.raises(Exception, match=r"(?i)exclusion"):
        async with rls_session.begin_nested():
            await rls_session.execute(
                text(
                    "INSERT INTO cost_item_rates (tenant_id, cost_item_id, scope_key, currency, total_rate, "
                    "valid_period, sys_period, source) VALUES "
                    "(:t, :i, 'GLOBAL', 'AED', 400, daterange('2026-03-01','2026-09-01'), "
                    "tstzrange(now(), null), 'manual')"
                ),
                {"t": TENANT, "i": item_id},
            )


async def test_correcting_history_closes_old_row_and_inserts_new(rls_session):
    """The bi-temporal write pattern services/costlib.py::record_rate()
    follows: close the old row's sys_period, then insert a fresh one --
    never UPDATE the total_rate/valid_period columns directly."""
    item_id = await _create_item(rls_session, "BITEMP-2")
    old_id = (
        await rls_session.execute(
            text(
                "INSERT INTO cost_item_rates (tenant_id, cost_item_id, scope_key, currency, total_rate, "
                "valid_period, sys_period, source) VALUES "
                "(:t, :i, 'GLOBAL', 'AED', 300, daterange('2026-01-01', null), "
                "tstzrange(now(), null), 'manual') RETURNING id"
            ),
            {"t": TENANT, "i": item_id},
        )
    ).scalar_one()

    await rls_session.execute(
        text("UPDATE cost_item_rates SET sys_period = tstzrange(lower(sys_period), now()) WHERE id = :id"),
        {"id": old_id},
    )
    await rls_session.execute(
        text(
            "INSERT INTO cost_item_rates (tenant_id, cost_item_id, scope_key, currency, total_rate, "
            "valid_period, sys_period, source, superseded_by_id) VALUES "
            "(:t, :i, 'GLOBAL', 'AED', 320, daterange('2026-01-01', null), "
            "tstzrange(now(), null), 'manual', null)"
        ),
        {"t": TENANT, "i": item_id},
    )

    current_count = await rls_session.execute(
        text("SELECT count(*) FROM cost_item_rates WHERE cost_item_id = :i AND upper_inf(sys_period)"),
        {"i": item_id},
    )
    assert current_count.scalar_one() == 1

    total_rows = await rls_session.execute(
        text("SELECT count(*) FROM cost_item_rates WHERE cost_item_id = :i"), {"i": item_id}
    )
    assert total_rows.scalar_one() == 2  # history preserved, not overwritten


async def test_costlib_rate_as_of_reconstructs_historical_belief(rls_session):
    item_id = await _create_item(rls_session, "BITEMP-3")
    # First belief, recorded "long ago": 300, valid all of 2026, sys_period closed later
    await rls_session.execute(
        text(
            "INSERT INTO cost_item_rates (tenant_id, cost_item_id, scope_key, currency, total_rate, "
            "valid_period, sys_period, source) VALUES "
            "(:t, :i, 'GLOBAL', 'AED', 300, daterange('2026-01-01','2027-01-01'), "
            "tstzrange('2026-01-01T00:00:00Z', '2026-06-01T00:00:00Z'), 'manual')"
        ),
        {"t": TENANT, "i": item_id},
    )
    # Corrected belief, recorded starting 2026-06-01: 340
    await rls_session.execute(
        text(
            "INSERT INTO cost_item_rates (tenant_id, cost_item_id, scope_key, currency, total_rate, "
            "valid_period, sys_period, source) VALUES "
            "(:t, :i, 'GLOBAL', 'AED', 340, daterange('2026-01-01','2027-01-01'), "
            "tstzrange('2026-06-01T00:00:00Z', null), 'manual')"
        ),
        {"t": TENANT, "i": item_id},
    )

    as_believed_in_march = await rls_session.execute(
        text("SELECT total_rate FROM costlib_rate_as_of(:t, :i, 'GLOBAL', '2026-03-01', '2026-03-15T00:00:00Z')"),
        {"t": TENANT, "i": item_id},
    )
    assert as_believed_in_march.scalar_one() == 300

    as_believed_today = await rls_session.execute(
        text("SELECT total_rate FROM costlib_rate_as_of(:t, :i, 'GLOBAL', '2026-03-01', now())"),
        {"t": TENANT, "i": item_id},
    )
    assert as_believed_today.scalar_one() == 340


async def test_component_amount_is_generated_correctly(rls_session):
    item_id = await _create_item(rls_session, "BITEMP-4")
    rate_id = (
        await rls_session.execute(
            text(
                "INSERT INTO cost_item_rates (tenant_id, cost_item_id, scope_key, currency, total_rate, "
                "valid_period, sys_period, source) VALUES "
                "(:t, :i, 'GLOBAL', 'AED', 0, daterange('2026-01-01', null), tstzrange(now(), null), "
                "'manual') RETURNING id"
            ),
            {"t": TENANT, "i": item_id},
        )
    ).scalar_one()
    await rls_session.execute(
        text(
            "INSERT INTO cost_rate_components (tenant_id, rate_id, component_type, description, "
            "quantity_per_uom, unit_cost, waste_factor) VALUES "
            "(:t, :r, 'material', 'concrete', 2, 100, 0.1)"
        ),
        {"t": TENANT, "r": rate_id},
    )
    amount = await rls_session.execute(
        text("SELECT amount FROM cost_rate_components WHERE rate_id = :r"), {"r": rate_id}
    )
    # 2 * 100 * 1.1 = 220
    assert amount.scalar_one() == pytest.approx(220)
