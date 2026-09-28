from __future__ import annotations

import time
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


async def test_decide_with_stale_silver_acr_is_rejected(authed_client):
    # has_recent_step_up (fix/keycloak-step-up) checks acr AND that
    # auth_time is actually recent -- a still-valid session/token can go on
    # reporting acr=silver long after the OTP entry that earned it (cookie
    # reattachment, a refresh_token grant), so acr=silver alone must NOT be
    # enough once auth_time is older than Settings.step_up_max_age_s (300s
    # default). This is the exact bug fixed on that branch: before it, this
    # request would have been allowed through.
    creator = authed_client(frozenset({Role.ESTIMATOR.value}))
    create_resp = await creator.post(
        "/api/v1/approvals",
        json={"entity_type": "cost_rate_change", "entity_id": str(uuid.uuid4()), "amount": 10000, "currency": "AED"},
    )
    request_id = create_resp.json()["id"]

    stale_auth_time = int(time.time()) - 301
    approver = authed_client(frozenset({Role.LEAD_ESTIMATOR.value}), acr="silver", auth_time=stale_auth_time)
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


async def test_pending_for_me_only_shows_requests_the_caller_can_actually_decide(authed_client):
    """Phase 3 gap-fill (docs/ui-qa-brief.md): home dashboard's "approvals
    waiting for me" tile. Mirrors decide()'s own routing exactly, not just
    "every pending request" -- a lead_estimator sees the single-tier
    request routed to them, but not one routed to procurement_head, and
    the requester never sees their own request even though it's pending."""
    creator = authed_client(frozenset({Role.ESTIMATOR.value}))
    lead_routed = await creator.post(
        "/api/v1/approvals",
        json={"entity_type": "cost_rate_change", "entity_id": str(uuid.uuid4()), "amount": 10000, "currency": "AED"},
    )
    lead_request_id = lead_routed.json()["id"]
    proc_routed = await creator.post(
        "/api/v1/approvals",
        json={"entity_type": "cost_rate_change", "entity_id": str(uuid.uuid4()), "amount": 60000, "currency": "AED"},
    )
    # amount=60000 routes lead_estimator (seq 1) then procurement_head (seq
    # 2) -- current_seq starts at 1, so this one is NOT yet in
    # procurement_head's queue until lead_estimator decides it first.
    proc_request_id = proc_routed.json()["id"]

    lead = authed_client(frozenset({Role.LEAD_ESTIMATOR.value}))
    resp = await lead.get("/api/v1/approvals/pending-for-me")
    assert resp.status_code == 200
    ids = {r["id"] for r in resp.json()}
    assert lead_request_id in ids
    assert proc_request_id in ids  # lead_estimator IS the current (seq 1) step here too

    proc = authed_client(frozenset({Role.PROCUREMENT_HEAD.value}))
    proc_resp = await proc.get("/api/v1/approvals/pending-for-me")
    proc_ids = {r["id"] for r in proc_resp.json()}
    assert proc_request_id not in proc_ids  # not their turn yet (current_seq=1, not 2)

    own_resp = await creator.get("/api/v1/approvals/pending-for-me")
    assert lead_request_id not in {r["id"] for r in own_resp.json()}  # SoD: never your own request


@pytest.fixture
def dev_mfa_off(monkeypatch):
    """DEV_DISABLE_MFA=true with APP_ENV=test, applied on top of the already
    built app (services call get_settings() per request)."""
    from app.core.config import get_settings

    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DEV_DISABLE_MFA", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def _audit_payloads(app_engine, request_id: str) -> list[dict]:
    from sqlalchemy.ext.asyncio import AsyncSession

    async with AsyncSession(app_engine) as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, false), set_config('app.is_system', 'on', false)"),
            {"t": TENANT},
        )
        rows = await session.execute(
            text("SELECT payload FROM audit_events WHERE entity_id = :e AND action IN ('approve', 'reject')"),
            {"e": request_id},
        )
        return [r[0] for r in rows]


async def test_decide_without_step_up_passes_and_is_audited_when_dev_mfa_is_off(
    authed_client, dev_mfa_off, app_engine
):
    creator = authed_client(frozenset({Role.ESTIMATOR.value}))
    create_resp = await creator.post(
        "/api/v1/approvals",
        json={"entity_type": "cost_rate_change", "entity_id": str(uuid.uuid4()), "amount": 10000, "currency": "AED"},
    )
    request_id = create_resp.json()["id"]

    approver = authed_client(frozenset({Role.LEAD_ESTIMATOR.value}))  # bronze/None: no step-up
    resp = await approver.post(f"/api/v1/approvals/{request_id}/decide", json={"approve": True})
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"

    payloads = await _audit_payloads(app_engine, request_id)
    assert len(payloads) == 1
    assert payloads[0]["mfa_bypassed_dev"] is True


async def test_genuine_step_up_is_not_flagged_as_bypassed_when_dev_mfa_is_off(
    authed_client, dev_mfa_off, app_engine
):
    creator = authed_client(frozenset({Role.ESTIMATOR.value}))
    create_resp = await creator.post(
        "/api/v1/approvals",
        json={"entity_type": "cost_rate_change", "entity_id": str(uuid.uuid4()), "amount": 10000, "currency": "AED"},
    )
    request_id = create_resp.json()["id"]

    approver = authed_client(frozenset({Role.LEAD_ESTIMATOR.value}), acr="silver")
    resp = await approver.post(f"/api/v1/approvals/{request_id}/decide", json={"approve": True})
    assert resp.status_code == 200

    payloads = await _audit_payloads(app_engine, request_id)
    assert len(payloads) == 1
    assert "mfa_bypassed_dev" not in payloads[0]
