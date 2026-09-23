from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.asyncio

TENANT = "8f14e45f-ceea-4e97-8d0c-3d3b3f3c1a00"


async def _set_guc(session, *, roles: str) -> None:
    await session.execute(
        text(
            "SELECT set_config('app.tenant_id', :t, false), set_config('app.user_id', :u, false), "
            "set_config('app.roles', :r, false), set_config('app.is_system', 'off', false)"
        ),
        {"t": TENANT, "u": str(uuid.uuid4()), "r": roles},
    )


async def _seed_cost_item(session) -> str:
    await _set_guc(session, roles="lead_estimator")
    result = await session.execute(
        text(
            "INSERT INTO cost_items (tenant_id, code, description, uom, item_type) "
            "VALUES (:t, 'RLS-TEST-ITEM', 'Test item', 'm3', 'material') RETURNING id"
        ),
        {"t": TENANT},
    )
    return str(result.scalar_one())


async def test_estimator_cannot_insert_cost_item_rate(rls_session):
    item_id = await _seed_cost_item(rls_session)
    await _set_guc(rls_session, roles="estimator")
    with pytest.raises(Exception, match=r"(?i)row-level security"):
        async with rls_session.begin_nested():
            await rls_session.execute(
                text(
                    "INSERT INTO cost_item_rates (tenant_id, cost_item_id, scope_key, currency, total_rate, "
                    "valid_period, sys_period, source) VALUES "
                    "(:t, :item, 'GLOBAL', 'AED', 100, daterange('2026-01-01', null), "
                    "tstzrange(now(), null), 'manual')"
                ),
                {"t": TENANT, "item": item_id},
            )


async def test_lead_estimator_can_insert_cost_item_rate(rls_session):
    item_id = await _seed_cost_item(rls_session)
    await _set_guc(rls_session, roles="lead_estimator")
    await rls_session.execute(
        text(
            "INSERT INTO cost_item_rates (tenant_id, cost_item_id, scope_key, currency, total_rate, "
            "valid_period, sys_period, source) VALUES "
            "(:t, :item, 'GLOBAL', 'AED', 100, daterange('2026-01-01', null), "
            "tstzrange(now(), null), 'manual')"
        ),
        {"t": TENANT, "item": item_id},
    )
    result = await rls_session.execute(
        text("SELECT count(*) FROM cost_item_rates WHERE cost_item_id = :item"), {"item": item_id}
    )
    assert result.scalar_one() == 1


async def test_only_managing_director_can_write_approval_policies(rls_session):
    await _set_guc(rls_session, roles="bd_director")
    with pytest.raises(Exception, match=r"(?i)row-level security"):
        async with rls_session.begin_nested():
            await rls_session.execute(
                text(
                    "INSERT INTO approval_policies (tenant_id, entity_type, name, version, mode) "
                    "VALUES (:t, 'rfq_award', 'test policy', 1, 'sequential_up_to_tier')"
                ),
                {"t": TENANT},
            )

    await _set_guc(rls_session, roles="managing_director")
    await rls_session.execute(
        text(
            "INSERT INTO approval_policies (tenant_id, entity_type, name, version, mode) "
            "VALUES (:t, 'rfq_award', 'test policy', 1, 'sequential_up_to_tier')"
        ),
        {"t": TENANT},
    )


async def test_audit_events_cannot_be_updated_or_deleted_even_as_managing_director(rls_session):
    await _set_guc(rls_session, roles="managing_director")
    insert_result = await rls_session.execute(
        text(
            "INSERT INTO audit_events (tenant_id, chain_date, seq, occurred_at, actor_sub, actor_roles, "
            "action, entity_type, payload, payload_sha256, prev_hash, event_hash, canonical_json) "
            "VALUES (:t, CURRENT_DATE, 0, now(), 'test', ARRAY['managing_director'], 'create', "
            "'vendor', '{}'::jsonb, '', '', '', '') RETURNING id"
        ),
        {"t": TENANT},
    )
    event_id = insert_result.scalar_one()

    with pytest.raises(Exception, match=r"(?i)permission denied|immutable"):
        await rls_session.execute(
            text("UPDATE audit_events SET action = 'delete' WHERE id = :id"), {"id": event_id}
        )
