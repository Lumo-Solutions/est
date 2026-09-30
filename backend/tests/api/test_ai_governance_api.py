"""AI governance against the real app + Postgres: the admin switch (managing
director only, audited), the per-project override, RLS on ai_calls (every role
can write, only lead_estimator+ can read), and the gateway end to end through
DbStore: blocked -> allowed -> cached, budget hard stop, project opt-out."""

from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy import text

from app.ai.errors import AIBudgetExceeded, AIDisabledForTenant
from app.ai.gateway import AIGateway, AIMeta
from app.ai.providers.anthropic import AnthropicProvider
from app.ai.store import DbStore
from app.core.config import Settings
from app.core.context import RequestContext
from app.core.enums import Role

pytestmark = pytest.mark.asyncio

TENANT = uuid.UUID("8f14e45f-ceea-4e97-8d0c-3d3b3f3c1a00")
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["label"],
    "properties": {"label": {"type": "string"}},
}


def _ctx(role: str) -> RequestContext:
    uid = uuid.uuid4()
    return RequestContext(tenant_id=TENANT, user_id=uid, sub=str(uid), roles=frozenset({role}))


def _settings(**kw) -> Settings:
    base = dict(
        APP_DATABASE_URL="postgresql://x/y", MIGRATOR_DATABASE_URL="postgresql://x/y", S3_ENDPOINT="http://s3.test",
        VLLM_API_BASE="http://vllm.internal:8000/v1", AI_PROVIDER="anthropic", AI_MODEL="claude-sonnet-5-5",
        AI_API_KEY="sk-test-key",
    )
    base.update(kw)
    return Settings(**base)


def _anthropic(settings: Settings, calls: list) -> AnthropicProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={
            "model": "claude-sonnet-5-5",
            "content": [{"type": "tool_use", "name": "record_result", "input": {"label": "ok"}}],
            "usage": {"input_tokens": 1000, "output_tokens": 200},
        })

    return AnthropicProvider(settings, transport=httpx.MockTransport(handler))


async def _gateway(settings: Settings, role: str, calls: list) -> AIGateway:
    return AIGateway(settings=settings, store=DbStore(), provider=_anthropic(settings, calls), ctx=_ctx(role))


# ------------------------------------------------------------------ admin API

async def test_status_reports_local_default_and_never_leaks_secrets(authed_client):
    est = authed_client(frozenset({Role.ESTIMATOR.value}))
    body = (await est.get("/api/v1/ai/status")).json()
    assert body["provider"] == "local_vllm" and body["external"] is False and body["available"] is True
    assert "key" not in str(body).lower()


async def test_only_managing_director_flips_the_switch_and_it_is_audited(authed_client):
    for role in (Role.ESTIMATOR, Role.LEAD_ESTIMATOR, Role.BD_DIRECTOR, Role.PROCUREMENT_HEAD):
        client = authed_client(frozenset({role.value}))
        assert (await client.put("/api/v1/admin/ai-settings", json={"external_ai_allowed": True})).status_code == 403

    md = authed_client(frozenset({Role.MANAGING_DIRECTOR.value}))
    resp = await md.put("/api/v1/admin/ai-settings", json={"external_ai_allowed": True})
    assert resp.status_code == 200 and resp.json()["external_ai_allowed"] is True
    assert (await md.get("/api/v1/ai/status")).json()["external_ai_allowed"] is True
    assert (await md.put("/api/v1/admin/ai-settings", json={"external_ai_allowed": False})).status_code == 200

    import app.db.session as dbs

    async with dbs.session_scope(_ctx(Role.MANAGING_DIRECTOR.value)) as session:
        rows = (
            await session.execute(
                text("SELECT payload FROM audit_events WHERE entity_type='tenant_ai_settings' ORDER BY seq")
            )
        ).scalars().all()
    assert len(rows) >= 2
    assert rows[-2]["external_ai_allowed"] == {"before": False, "after": True}
    assert rows[-1]["external_ai_allowed"] == {"before": True, "after": False}


async def test_project_override_roles(authed_client):
    md = authed_client(frozenset({Role.MANAGING_DIRECTOR.value}))
    pid = (await md.post("/api/v1/projects", json={"code": "AI-OVR-1", "name": "Confidential"})).json()["id"]
    lead = authed_client(frozenset({Role.LEAD_ESTIMATOR.value}))
    assert (await lead.put(f"/api/v1/projects/{pid}/ai-override", json={"external_ai_override": False})).status_code == 403
    md = authed_client(frozenset({Role.MANAGING_DIRECTOR.value}))
    resp = await md.put(f"/api/v1/projects/{pid}/ai-override", json={"external_ai_override": False})
    assert resp.status_code == 200 and resp.json()["external_ai_override"] is False
    assert (await md.put(f"/api/v1/projects/{uuid.uuid4()}/ai-override", json={"external_ai_override": None})).status_code == 404


async def test_usage_view_roles(authed_client):
    for role in (Role.ESTIMATOR, Role.LEAD_ESTIMATOR, Role.PROCUREMENT_HEAD):
        assert (await authed_client(frozenset({role.value})).get("/api/v1/admin/ai-usage")).status_code == 403
    md = authed_client(frozenset({Role.MANAGING_DIRECTOR.value}))
    body = (await md.get("/api/v1/admin/ai-usage")).json()
    assert {"month_to_date_usd", "rows", "recent"} <= set(body)


# ------------------------------------------------------------------ gateway on the real DB

async def test_gateway_blocked_then_allowed_then_cached_and_visible_to_admin(authed_client, app_engine):
    import app.db.session as dbs

    dbs.get_worker_engine.cache_clear()
    s = _settings()
    calls: list = []
    md = authed_client(frozenset({Role.MANAGING_DIRECTOR.value}))
    await md.put("/api/v1/admin/ai-settings", json={"external_ai_allowed": False})

    est_gw = await _gateway(s, Role.ESTIMATOR.value, calls)
    with pytest.raises(AIDisabledForTenant):
        await est_gw.run(task="rls_probe", system="s", user="doc-1", schema=SCHEMA)
    assert calls == []  # nothing left the boundary

    await md.put("/api/v1/admin/ai-settings", json={"external_ai_allowed": True})
    first = await est_gw.run(task="rls_probe", system="s", user="doc-1", schema=SCHEMA)
    again = await est_gw.run(task="rls_probe", system="s", user="doc-1", schema=SCHEMA)
    assert first.data == {"label": "ok"} and not first.cached and again.cached and len(calls) == 1

    body = (await md.get("/api/v1/admin/ai-usage")).json()
    probe = [r for r in body["rows"] if r["task"] == "rls_probe"]
    assert probe and probe[0]["calls"] >= 3 and probe[0]["cached"] >= 1 and probe[0]["blocked"] >= 1
    assert probe[0]["cost_usd"] > 0
    recent = [c for c in body["recent"] if c["task"] == "rls_probe"]
    assert recent and "prompt" not in recent[0] and "response" not in recent[0]

    await md.put("/api/v1/admin/ai-settings", json={"external_ai_allowed": False})


async def test_estimator_writes_but_cannot_read_ai_calls_rls(authed_client, app_engine):
    import app.db.session as dbs

    dbs.get_worker_engine.cache_clear()
    md = authed_client(frozenset({Role.MANAGING_DIRECTOR.value}))
    await md.put("/api/v1/admin/ai-settings", json={"external_ai_allowed": True})
    calls: list = []
    gw = await _gateway(_settings(), Role.ESTIMATOR.value, calls)
    await gw.run(task="rls_probe2", system="s", user="doc-x", schema=SCHEMA)

    async with dbs.session_scope(_ctx(Role.ESTIMATOR.value)) as session:
        assert (await session.execute(text("SELECT count(*) FROM ai_calls"))).scalar_one() == 0
    async with dbs.session_scope(_ctx(Role.LEAD_ESTIMATOR.value)) as session:
        n = (await session.execute(text("SELECT count(*) FROM ai_calls WHERE task='rls_probe2'"))).scalar_one()
        assert n == 1
        # append-only: no UPDATE / DELETE policy
        upd = await session.execute(text("UPDATE ai_calls SET error='x' WHERE task='rls_probe2'"))
        assert upd.rowcount == 0
        dele = await session.execute(text("DELETE FROM ai_calls WHERE task='rls_probe2'"))
        assert dele.rowcount == 0
    other_tenant = RequestContext(tenant_id=uuid.uuid4(), user_id=uuid.uuid4(), sub="x", roles=frozenset({"managing_director"}))
    async with dbs.session_scope(other_tenant) as session:
        assert (await session.execute(text("SELECT count(*) FROM ai_calls"))).scalar_one() == 0
        assert (await session.execute(text("SELECT count(*) FROM ai_cache"))).scalar_one() == 0
    await md.put("/api/v1/admin/ai-settings", json={"external_ai_allowed": False})


async def test_project_optout_and_budget_hard_stop_on_real_db(authed_client, app_engine):
    import app.db.session as dbs

    dbs.get_worker_engine.cache_clear()
    md = authed_client(frozenset({Role.MANAGING_DIRECTOR.value}))
    await md.put("/api/v1/admin/ai-settings", json={"external_ai_allowed": True})
    pid = uuid.UUID((await md.post("/api/v1/projects", json={"code": f"AI-B-{uuid.uuid4().hex[:6]}", "name": "B"})).json()["id"])
    calls: list = []

    s = _settings(AI_PROJECT_BUDGET_USD="0.005")
    gw = await _gateway(s, Role.LEAD_ESTIMATOR.value, calls)
    meta = AIMeta(project_id=pid, entity_type="probe", entity_id="1")
    await gw.run(task="budget_probe", system="s", user="one", schema=SCHEMA, meta=meta)  # 0.006 -> over cap
    with pytest.raises(AIBudgetExceeded):
        await gw.run(task="budget_probe", system="s", user="two", schema=SCHEMA, meta=meta)
    assert len(calls) == 1

    # opt the project out: blocked even with budget headroom
    await md.put(f"/api/v1/projects/{pid}/ai-override", json={"external_ai_override": False})
    gw2 = await _gateway(_settings(), Role.LEAD_ESTIMATOR.value, calls)
    with pytest.raises(AIDisabledForTenant):
        await gw2.run(task="budget_probe", system="s", user="three", schema=SCHEMA, meta=meta)
    await md.put("/api/v1/admin/ai-settings", json={"external_ai_allowed": False})


async def test_status_says_when_the_monthly_budget_is_reached_for_every_role(authed_client, client, app_engine):
    """The UI message comes from /ai/status. The spend is summed system-wide, so an estimator (who cannot read ai_calls
    under RLS) is told the same thing as a director."""
    from decimal import Decimal

    import app.db.session as dbs
    from app.ai.store import CallRecord, DbStore
    from app.core.config import get_settings

    dbs.get_worker_engine.cache_clear()
    md = authed_client(frozenset({Role.MANAGING_DIRECTOR.value}))
    await md.put("/api/v1/admin/ai-settings", json={"external_ai_allowed": True})
    await DbStore().record(_ctx(Role.LEAD_ESTIMATOR.value), CallRecord(
        task="budget_status", provider="anthropic", model="claude-sonnet-5-5", prompt_version="1", input_sha256="0" * 64,
        status="ok", external=True, cost_usd=Decimal("5.000000"),
    ))
    app = client._transport.app
    capped = _settings(AI_MONTHLY_BUDGET_USD="1.00")
    app.dependency_overrides[get_settings] = lambda: capped
    try:
        for role in (Role.ESTIMATOR, Role.MANAGING_DIRECTOR):
            body = (await authed_client(frozenset({role.value})).get("/api/v1/ai/status")).json()
            assert body["budget_exceeded"] is True and body["available"] is False and "budget" in body["message"].lower()
            assert body["provider"] == "anthropic" and "key" not in str(body).lower()
        roomy = _settings(AI_MONTHLY_BUDGET_USD="1000")
        app.dependency_overrides[get_settings] = lambda: roomy
        body = (await authed_client(frozenset({Role.ESTIMATOR.value})).get("/api/v1/ai/status")).json()
        assert body["budget_exceeded"] is False and body["available"] is True
    finally:
        app.dependency_overrides.pop(get_settings, None)
        await authed_client(frozenset({Role.MANAGING_DIRECTOR.value})).put("/api/v1/admin/ai-settings", json={"external_ai_allowed": False})
