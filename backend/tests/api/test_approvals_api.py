from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.core.enums import Role

pytestmark = pytest.mark.asyncio

TENANT = "8f14e45f-ceea-4e97-8d0c-3d3b3f3c1a00"


@pytest.fixture(autouse=True)
async def default_approval_policy(app_engine, postgres_container):
    """Seeds a minimal default policy directly (not via app.cli, to keep
    this test self-contained) so /approvals has something to route against."""
    from sqlalchemy.ext.asyncio import AsyncSession

    async with AsyncSession(app_engine) as session, session.begin():
        await session.execute(
            text(
                "SELECT set_config('app.tenant_id', :t, false), set_config('app.is_system', 'on', false)"
            ),
            {"t": TENANT},
        )
        existing = await session.execute(
            text("SELECT id FROM approval_policies WHERE tenant_id = :t AND entity_type = 'cost_rate_change'"),
            {"t": TENANT},
        )
        if existing.first() is not None:
            return
        policy_id = (
            await session.execute(
                text(
                    "INSERT INTO approval_policies (tenant_id, entity_type, name, version, mode) "
                    "VALUES (:t, 'cost_rate_change', 'Test policy', 1, 'sequential_up_to_tier') RETURNING id"
                ),
                {"t": TENANT},
            )
        ).scalar_one()
        for seq, min_amount, max_amount, role in (
            (1, 0, 50_000, "lead_estimator"),
            (2, 50_000, 250_000, "procurement_head"),
        ):
            await session.execute(
                text(
                    "INSERT INTO approval_policy_tiers (tenant_id, policy_id, seq, min_amount, max_amount, "
                    "required_role) VALUES (:t, :p, :s, :min, :max, :r)"
                ),
                {"t": TENANT, "p": policy_id, "s": seq, "min": min_amount, "max": max_amount, "r": role},
            )


async def test_create_approval_request_routes_correct_tiers(authed_client):
    c = authed_client(frozenset({Role.ESTIMATOR.value}))
    resp = await c.post(
        "/api/v1/approvals",
        json={"entity_type": "cost_rate_change", "entity_id": str(uuid.uuid4()), "amount": 60000, "currency": "AED"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert [s["required_role"] for s in body["steps"]] == ["lead_estimator", "procurement_head"]
    assert body["status"] == "pending"
    assert body["current_seq"] == 1


async def test_decide_without_mfa_step_up_is_rejected(authed_client):
    creator = authed_client(frozenset({Role.ESTIMATOR.value}))
    create_resp = await creator.post(
        "/api/v1/approvals",
        json={"entity_type": "cost_rate_change", "entity_id": str(uuid.uuid4()), "amount": 10000, "currency": "AED"},
    )
    request_id = create_resp.json()["id"]

    approver = authed_client(frozenset({Role.LEAD_ESTIMATOR.value}))  # acr defaults to None (no step-up)
    resp = await approver.post(f"/api/v1/approvals/{request_id}/decide", json={"approve": True})
    assert resp.status_code == 403
    assert resp.json()["type"] == "urn:installtec:step-up-required"


async def test_decide_by_wrong_role_is_rejected(authed_client):
    creator = authed_client(frozenset({Role.ESTIMATOR.value}))
    create_resp = await creator.post(
        "/api/v1/approvals",
        json={"entity_type": "cost_rate_change", "entity_id": str(uuid.uuid4()), "amount": 10000, "currency": "AED"},
    )
    request_id = create_resp.json()["id"]

    wrong_role_client = authed_client(frozenset({Role.BD_DIRECTOR.value}), acr="silver")
    resp = await wrong_role_client.post(f"/api/v1/approvals/{request_id}/decide", json={"approve": True})
    assert resp.status_code == 403
    assert resp.json()["type"] == "urn:installtec:forbidden"


async def test_full_two_tier_approval_flow_with_step_up(authed_client):
    def _stepped_up(roles: frozenset[str]):
        return authed_client(roles, acr="silver")

    creator = authed_client(frozenset({Role.ESTIMATOR.value}))
    create_resp = await creator.post(
        "/api/v1/approvals",
        json={"entity_type": "cost_rate_change", "entity_id": str(uuid.uuid4()), "amount": 60000, "currency": "AED"},
    )
    request_id = create_resp.json()["id"]

    step1 = _stepped_up(frozenset({Role.LEAD_ESTIMATOR.value}))
    resp1 = await step1.post(f"/api/v1/approvals/{request_id}/decide", json={"approve": True, "note": "ok"})
    assert resp1.status_code == 200
    assert resp1.json()["status"] == "pending"
    assert resp1.json()["current_seq"] == 2

    step2 = _stepped_up(frozenset({Role.PROCUREMENT_HEAD.value}))
    resp2 = await step2.post(f"/api/v1/approvals/{request_id}/decide", json={"approve": True, "note": "final"})
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "approved"
    assert resp2.json()["completed_at"] is not None
