"""The BOQ agent over HTTP with the worker bodies run for real against the test database: who may start a run, confirm and
chat (lead_estimator and above) and who may only look (estimators on the project), the response shapes the UI relies on, RLS for
someone who is not on the project, and the whole path run -> confirm -> submit through the API."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.factory import set_gateway_override
from app.ai.providers.mock import MockProvider, clear_mock_handlers
from app.core.enums import Role
from tests.api.test_pricing_ai_api import TENANT, Actor, _member, _seed
from tests.integration.test_tender_intake_flow import _install_gateway

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    import app.db.session as dbs
    from app.workers.tasks import agent as agent_tasks

    queue: list = []
    monkeypatch.setattr(agent_tasks, "enqueue", lambda kind, rid, tid, countdown=1: queue.append((kind, rid, tid)))
    dbs.get_worker_engine.cache_clear()
    _install_gateway(MockProvider())
    yield queue
    set_gateway_override(None)
    clear_mock_handlers()


async def _drive(queue: list) -> None:
    import app.db.session as dbs
    from app.agent import chat, runner

    dbs.get_worker_engine.cache_clear()

    def enqueue(kind, rid, tid):
        queue.append((kind, rid, tid))

    n = 0
    while queue and n < 60:
        kind, rid, tid = queue.pop(0)
        n += 1
        if kind == "plan":
            await runner.plan_run(rid, tid, enqueue)
        elif kind == "section":
            await runner.run_next_section(rid, tid, enqueue)
        else:
            await chat.run_turn(rid, tid, enqueue)


async def _policy(app_engine) -> None:
    from tests.integration.test_bid_settlement import _seed_bid_submission_policy

    async with AsyncSession(app_engine) as s, s.begin():
        await s.execute(text("SELECT set_config('app.tenant_id', :t, false), set_config('app.is_system', 'on', false)"), {"t": str(TENANT)})
        have = (await s.execute(text("SELECT count(*) FROM approval_policies WHERE entity_type='bid_submission'"))).scalar_one()
        if not have:
            await _seed_bid_submission_policy(s, TENANT)


async def test_run_roles_shapes_trace_and_rls(authed_client, client, monkeypatch, app_engine, _env):
    sc = await _seed(authed_client, app_engine)
    pid, sid = sc["pid"], sc["sid"]
    est = await _member(client, monkeypatch, app_engine, pid, Role.ESTIMATOR.value)
    lead = await _member(client, monkeypatch, app_engine, pid, Role.LEAD_ESTIMATOR.value)
    outsider = Actor(client, monkeypatch, frozenset({Role.ESTIMATOR.value}))

    # only a lead starts a run; the response carries the estimate, limits and one row per section
    assert (await est.c.post(f"/api/v1/projects/{pid}/agent/runs", json={})).status_code == 403
    r = await lead.c.post(f"/api/v1/projects/{pid}/agent/runs", json={})
    assert r.status_code == 202, r.text
    run = r.json()
    assert run["status"] == "queued" and run["kind"] == "run" and run["estimate"]["external"] is False and run["estimate"]["usd"] == 0
    assert run["limits"]["max_steps"] == 40 and run["limits"]["max_page_views"] == 60 and run["limits"]["max_usd"] == 5.0
    assert run["sections"] and run["sections"][0]["status"] == "pending" and run["sections"][0]["line_count"] == 3
    assert [q[0] for q in _env] == ["plan"]
    assert (await lead.c.post(f"/api/v1/projects/{pid}/agent/runs", json={})).status_code == 409  # one active run per project
    await _drive(_env)

    done = (await est.c.get(f"/api/v1/agent/runs/{run['id']}")).json()  # an estimator on the project may look
    assert done["status"] == "done" and done["steps_total"] > 0 and done["plan"]["sections"] and done["summary"]["applied"]["applied"] >= 1
    assert done["sections"][0]["status"] == "done" and done["sections"][0]["coverage"]["lines_total"] == 3
    steps = (await est.c.get(f"/api/v1/agent/runs/{run['id']}/steps")).json()
    assert [s["seq"] for s in steps] == sorted(s["seq"] for s in steps) and {"tool", "note", "result_summary", "file_refs", "injection", "ok"} <= set(steps[0])
    later = (await est.c.get(f"/api/v1/agent/runs/{run['id']}/steps", params={"after_seq": steps[0]["seq"], "limit": 2})).json()
    assert len(later) <= 2 and all(s["seq"] > steps[0]["seq"] for s in later)
    assert (await est.c.get(f"/api/v1/projects/{pid}/agent/runs")).json()[0]["id"] == run["id"]
    # a stranger sees nothing
    assert (await outsider.c.get(f"/api/v1/agent/runs/{run['id']}")).status_code in (403, 404)
    assert (await outsider.c.get(f"/api/v1/projects/{pid}/agent/runs")).status_code in (200, 403, 404)
    assert (await lead.c.get(f"/api/v1/agent/runs/{uuid.uuid4()}")).status_code == 404

    # the agent-filled line is visible with its proposal, unconfirmed, and the settlement says so
    lines = (await est.c.get(f"/api/v1/bid-settlements/{sid}/agent-lines")).json()
    assert len(lines) == 1 and lines[0]["cost_source"] == "agent_candidate" and lines[0]["agent_confirmed_by"] is None
    prop = lines[0]["proposal"]
    assert prop["kind"] == "candidate" and float(prop["rate"]) == 10.0 and prop["candidate_ref"].startswith("q:") and prop["evidence"]
    assert (await est.c.get(f"/api/v1/bid-settlements/{sid}/agent-summary")).json() == {"agent_lines": 1, "unconfirmed": 1}
    assert (await est.c.get(f"/api/v1/agent/proposals/{prop['id']}")).json()["id"] == prop["id"]
    detail = (await lead.c.get(f"/api/v1/bid-settlements/{sid}")).json()
    line = next(l for l in (detail.get("lines") or (await lead.c.get(f"/api/v1/bid-settlements/{sid}/lines")).json()) if l["id"] == lines[0]["line_id"])
    assert line["cost_source"] == "agent_candidate" and line["agent_proposal_id"] == prop["id"] and line["agent_confirmed_by"] is None

    # confirming: an estimator may not; the wrong proposal id is a conflict; the right one works and is idempotent
    url = f"/api/v1/bid-settlements/{sid}/lines/{lines[0]['line_id']}/agent-confirm"
    assert (await est.c.post(url, json={"proposal_id": prop["id"]})).status_code == 403
    assert (await lead.c.post(url, json={"proposal_id": str(uuid.uuid4())})).status_code == 409
    ok = await lead.c.post(url, json={"proposal_id": prop["id"]})
    assert ok.status_code == 200 and ok.json()["agent_confirmed_by"] == lead.sub
    assert (await lead.c.post(url, json={"proposal_id": prop["id"]})).status_code == 200
    assert (await lead.c.get(f"/api/v1/bid-settlements/{sid}/agent-summary")).json()["unconfirmed"] == 0
    assert (await est.c.post(f"/api/v1/bid-settlements/{sid}/agent-confirm-bulk")).status_code == 403
    assert (await lead.c.post(f"/api/v1/bid-settlements/{sid}/agent-confirm-bulk")).json()["confirmed"] == 0


async def test_run_through_to_a_submitted_settlement_over_http(authed_client, client, monkeypatch, app_engine, _env):
    await _policy(app_engine)
    sc = await _seed(authed_client, app_engine)
    pid, sid = sc["pid"], sc["sid"]
    lead = await _member(client, monkeypatch, app_engine, pid, Role.LEAD_ESTIMATOR.value)
    assert (await lead.c.post(f"/api/v1/projects/{pid}/agent/runs", json={})).status_code == 202
    await _drive(_env)
    detail = (await lead.c.get(f"/api/v1/bid-settlements/{sid}")).json()
    all_lines = detail.get("lines") or (await lead.c.get(f"/api/v1/bid-settlements/{sid}/lines")).json()
    # the one line with no source at all is the person's to cost
    open_line = next(l for l in all_lines if l["direct_unit_cost"] is None)
    set_cost = await lead.c.patch(
        f"/api/v1/bid-settlements/{sid}/lines/{open_line['id']}", json={"cost_source": "manual", "manual_unit_cost": "1200", "source_note": "supplier phone quote"}
    )
    assert set_cost.status_code == 200, set_cost.text
    bd = authed_client(frozenset({Role.BD_DIRECTOR.value}), acr="silver")
    blocked = await bd.post(f"/api/v1/bid-settlements/{sid}/submit")
    assert blocked.status_code == 409 and "estimation agent" in blocked.text  # the agent's line is unconfirmed
    agent_line = (await lead.c.get(f"/api/v1/bid-settlements/{sid}/agent-lines")).json()[0]
    assert (await lead.c.post(f"/api/v1/bid-settlements/{sid}/lines/{agent_line['line_id']}/agent-confirm", json={"proposal_id": agent_line["agent_proposal_id"]})).status_code == 200
    bd = authed_client(frozenset({Role.BD_DIRECTOR.value}), acr="silver")
    submitted = await bd.post(f"/api/v1/bid-settlements/{sid}/submit")
    assert submitted.status_code == 200, submitted.text
    body = submitted.json()
    assert body["status"] == "submitted" and float(body["tender_total"]) > 0 and body["approval_request_id"]
    # a submitted settlement is closed to the agent: a new run needs an explicit new draft
    again = await lead.c.post(f"/api/v1/projects/{pid}/agent/runs", json={})
    assert again.status_code == 409


async def test_pause_resume_cancel_and_confirm_over_http(authed_client, client, monkeypatch, app_engine, _env):
    sc = await _seed(authed_client, app_engine)
    pid = sc["pid"]
    lead = await _member(client, monkeypatch, app_engine, pid, Role.LEAD_ESTIMATOR.value)
    est = await _member(client, monkeypatch, app_engine, pid, Role.ESTIMATOR.value)
    run = (await lead.c.post(f"/api/v1/projects/{pid}/agent/runs", json={"limits": {"max_steps": 12}})).json()
    assert run["limits"]["max_steps"] == 12
    assert (await est.c.post(f"/api/v1/agent/runs/{run['id']}/pause")).status_code == 403
    assert (await lead.c.post(f"/api/v1/agent/runs/{run['id']}/pause")).json()["status"] == "paused"
    await _drive(_env)
    assert (await lead.c.get(f"/api/v1/agent/runs/{run['id']}")).json()["steps_total"] == 0
    assert (await lead.c.post(f"/api/v1/agent/runs/{run['id']}/confirm")).status_code == 409  # not waiting for a cost confirmation
    assert (await lead.c.post(f"/api/v1/agent/runs/{run['id']}/resume")).status_code == 202
    await _drive(_env)
    assert (await lead.c.get(f"/api/v1/agent/runs/{run['id']}")).json()["status"] == "done"
    assert (await lead.c.post(f"/api/v1/agent/runs/{run['id']}/cancel")).status_code == 409  # already finished
    bad = await lead.c.post(f"/api/v1/projects/{pid}/agent/runs", json={"sections": ["nope-not-a-section"]})
    assert bad.status_code == 422


async def test_chat_over_http(authed_client, client, monkeypatch, app_engine, _env):
    from app.agent.mock_sessions import Script
    from app.ai.providers.mock import register_mock_handler

    sc = await _seed(authed_client, app_engine)
    pid = sc["pid"]
    lead = await _member(client, monkeypatch, app_engine, pid, Role.LEAD_ESTIMATOR.value)
    est = await _member(client, monkeypatch, app_engine, pid, Role.ESTIMATOR.value)
    register_mock_handler("agent.step", Script([{"note": "answer", "tool": "finish_section", "args": {"summary": "Nothing has run yet."}}]))
    assert (await est.c.post(f"/api/v1/projects/{pid}/agent/chat", json={"message": "hello"})).status_code == 403
    assert (await lead.c.post(f"/api/v1/projects/{pid}/agent/chat", json={"message": ""})).status_code == 422
    r = await lead.c.post(f"/api/v1/projects/{pid}/agent/chat", json={"message": "What have you done so far?"})
    assert r.status_code == 202 and r.json()["message"]["role"] == "user"
    conv = r.json()["conversation_id"]
    assert (await lead.c.post(f"/api/v1/projects/{pid}/agent/chat", json={"message": "again", "conversation_id": conv})).status_code == 409  # still answering
    await _drive(_env)
    msgs = (await est.c.get(f"/api/v1/agent/conversations/{conv}/messages")).json()
    assert [m["role"] for m in msgs] == ["user", "assistant"] and msgs[1]["content"] == "Nothing has run yet."
    after = (await est.c.get(f"/api/v1/agent/conversations/{conv}/messages", params={"after": msgs[0]["created_at"]})).json()
    assert [m["role"] for m in after] == ["assistant"]
    assert (await est.c.get(f"/api/v1/projects/{pid}/agent/conversations")).json()[0]["id"] == conv


async def test_ai_classify_is_a_managing_director_setting_that_defaults_off(authed_client):
    md = authed_client(frozenset({Role.MANAGING_DIRECTOR.value}))
    assert (await md.get("/api/v1/tender-intake/settings")).json()["ai_classify"] is False
    lead = authed_client(frozenset({Role.LEAD_ESTIMATOR.value}))
    assert (await lead.put("/api/v1/admin/intake-settings", json={"ai_classify": True})).status_code == 403
    md = authed_client(frozenset({Role.MANAGING_DIRECTOR.value}))
    on = await md.put("/api/v1/admin/intake-settings", json={"ai_classify": True})
    assert on.status_code == 200 and on.json()["ai_classify"] is True
    assert (await md.put("/api/v1/admin/intake-settings", json={"ai_classify": False})).json()["ai_classify"] is False
