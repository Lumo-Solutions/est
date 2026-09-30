"""AI pricing assistant over HTTP: who may start a run (lead_estimator and above), who may work proposals
(estimator members), bulk accept (lead), response shape, RLS for non-members, and the worker running as the
requester. Several identities share one test client, so each actor switches explicitly (see Actor)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.gateway import AIGateway
from app.ai.providers.mock import MockProvider, clear_mock_handlers, register_mock_handler
from app.ai.store import MemoryStore
from app.core.config import Settings
from app.core.context import RequestContext
from app.core.enums import Role
from tests.integration.test_bid_settlement import _seed_accepted_quotation_line

pytestmark = pytest.mark.asyncio

TENANT = uuid.UUID("8f14e45f-ceea-4e97-8d0c-3d3b3f3c1a00")
SETTINGS = Settings(APP_DATABASE_URL="postgresql://x/y", MIGRATOR_DATABASE_URL="postgresql://x/y", S3_ENDPOINT="http://s3",
                    VLLM_API_BASE="http://vllm.internal/v1", AI_PROVIDER="mock")


@pytest.fixture(autouse=True)
def _fakes(monkeypatch):
    from app.workers.tasks import ai_reading as worker

    dispatched: list = []
    monkeypatch.setattr(worker.run_settlement_ai, "apply_async", lambda args=None, countdown=0, **kw: dispatched.append(args))
    ctx = RequestContext(tenant_id=TENANT, user_id=uuid.uuid4(), sub="w", roles=frozenset({"lead_estimator"}))
    monkeypatch.setattr("app.boq.pdf_ai.default_gateway", lambda settings=None: AIGateway(settings=SETTINGS, store=MemoryStore(), provider=MockProvider(), ctx=ctx))

    def choose(req):
        out = []
        for block in req.user.split("<<<LINE id=")[1:]:
            lid = block.split("\n", 1)[0].strip()
            refs = [ln[len("- ref="):].split(" |")[0] for ln in block.splitlines() if ln.startswith("- ref=")]
            if refs:
                out.append({"id": lid, "ranked": [{"ref": r, "score": 0.95 if i == 0 else 0.3, "selected": i == 0, "rationale": "same scope"} for i, r in enumerate(refs)]})
        return {"lines": out}

    register_mock_handler("cost_choose", choose)
    register_mock_handler("markup_advise", lambda req: {"options": [
        {"label": "competitive", "markup_pct": 5, "overhead_pct": 4, "volatility_pct": 2, "rationale": "history"},
        {"label": "balanced", "markup_pct": 8, "overhead_pct": 5, "volatility_pct": 3, "rationale": "history"},
        {"label": "protective", "markup_pct": 10, "overhead_pct": 6, "volatility_pct": 4, "rationale": "risk"}], "overall": "ok"})
    yield dispatched
    clear_mock_handlers()


class Actor:
    """A stable identity (fixed sub + roles) on the shared test client. `authed_client` re-binds the ONE
    client to a fresh random identity on every call, so several actors in one test must switch explicitly:
    `actor.c` makes this actor the current principal and returns the client."""

    def __init__(self, client, monkeypatch, roles: frozenset[str]) -> None:
        from app.security.jwt import Principal, TokenValidator

        self.sub = str(uuid.uuid4())
        self._client, self._mp, self._validator = client, monkeypatch, TokenValidator
        self._principal = Principal(sub=self.sub, tenant_id=TENANT, email=None, roles=roles, acr=None, amr=[], sid=None, exp=0,
                                    auth_time=None, username=None)

    @property
    def c(self):
        self._mp.setattr(self._validator, "validate", lambda _self, _token, p=self._principal: p)
        self._client.headers["Authorization"] = "Bearer test-token"
        return self._client


async def _member(client, monkeypatch, app_engine, pid: str, role: str) -> Actor:
    actor = Actor(client, monkeypatch, frozenset({role}))
    async with AsyncSession(app_engine) as s, s.begin():
        await s.execute(text("SELECT set_config('app.tenant_id', :t, false), set_config('app.is_system', 'on', false)"), {"t": str(TENANT)})
        await s.execute(text("INSERT INTO project_members (project_id, user_id, tenant_id) VALUES (:p, :u, :t)"), {"p": pid, "u": actor.sub, "t": str(TENANT)})
    return actor


async def _seed(authed_client, app_engine) -> dict:
    md = authed_client(frozenset({Role.MANAGING_DIRECTOR.value}))
    pid = (await md.post("/api/v1/projects", json={"code": f"PR-{uuid.uuid4().hex[:6]}", "name": "Pricing"})).json()["id"]
    items = {}
    for no, desc, qty, uom in [("1.1", "Supply and lay 300mm uPVC sewer pipe", 245.0, "m"), ("1.2", "Excavate in soil", 1000.0, "m3"), ("1.3", "Street lighting column", 8.0, "nr")]:
        r = await md.post(f"/api/v1/projects/{pid}/boq-items", json={"item_no": no, "description": desc, "uom": uom, "boq_quantity": qty})
        assert r.status_code == 201, r.text
        items[no] = SimpleNamespace(id=uuid.UUID(r.json()["id"]), boq_quantity=qty)
    async with AsyncSession(app_engine) as s, s.begin():
        sysctx = RequestContext(tenant_id=TENANT, user_id=uuid.uuid4(), sub="s", roles=frozenset(), is_system=True)
        await s.execute(text("SELECT set_config('app.tenant_id', :t, false), set_config('app.is_system', 'on', false)"), {"t": str(TENANT)})
        await _seed_accepted_quotation_line(s, sysctx, project_id=uuid.UUID(pid), boq_item=items["1.1"], unit_price="95.00")
        await _seed_accepted_quotation_line(s, sysctx, project_id=uuid.UUID(pid), boq_item=items["1.2"], unit_price="10.00")
        await _seed_accepted_quotation_line(s, sysctx, project_id=uuid.UUID(pid), boq_item=items["1.2"], unit_price="12.00")
    md = authed_client(frozenset({Role.MANAGING_DIRECTOR.value}))
    settlement = (await md.post(f"/api/v1/projects/{pid}/bid-settlements")).json()
    return {"pid": pid, "sid": settlement["id"], "items": items}


async def _worker(run_id: str, sub: str):
    import app.db.session as dbs
    from app.workers.base import build_worker_context
    from app.workers.tasks.ai_reading import _settlement_ai

    dbs.get_worker_engine.cache_clear()
    await _settlement_ai(build_worker_context(str(TENANT), sub, ["lead_estimator"]), run_id)


async def test_run_roles_proposals_shape_and_decisions(authed_client, client, monkeypatch, app_engine, _fakes):
    sc = await _seed(authed_client, app_engine)
    sid, pid = sc["sid"], sc["pid"]
    est = await _member(client, monkeypatch, app_engine, pid, Role.ESTIMATOR.value)
    lead = await _member(client, monkeypatch, app_engine, pid, Role.LEAD_ESTIMATOR.value)
    # starting a run: estimator denied, lead (member) allowed
    assert (await est.c.post(f"/api/v1/bid-settlements/{sid}/ai/cost-proposals", json={})).status_code == 403
    assert (await est.c.post(f"/api/v1/bid-settlements/{sid}/ai/markup-advice", json={})).status_code == 403
    r = await lead.c.post(f"/api/v1/bid-settlements/{sid}/ai/cost-proposals", json={"use_ai": True})
    assert r.status_code == 202 and r.json()["status"] == "queued" and r.json()["kind"] == "costs"
    run_id = r.json()["id"]
    assert _fakes and _fakes[-1][0] == run_id
    await _worker(run_id, lead.sub)

    run = (await lead.c.get(f"/api/v1/settlement-ai-runs/{run_id}")).json()
    assert run["status"] == "ready" and run["counts"]["lines"] == 3 and run["counts"]["no_source"] == 1
    assert (await lead.c.get(f"/api/v1/bid-settlements/{sid}/ai/runs")).json()[0]["id"] == run_id

    page = (await lead.c.get(f"/api/v1/bid-settlements/{sid}/ai/proposals")).json()
    assert page["total"] == 3
    by = {p["item_no"]: p for p in page["items"]}
    p11, p12, p13 = by["1.1"], by["1.2"], by["1.3"]
    assert p11["chosen"]["type"] == "quote" and float(p11["chosen"]["rate"]) == 95.0 and p11["source"] == "ai"
    assert p11["description"].startswith("Supply and lay") and p11["uom"] == "m" and float(p11["quantity"]) == 245.0
    assert p11["candidates"][0]["selected"] is True and p11["status"] == "proposed" and p11["no_source"] is False
    assert p13["chosen"] is None and p13["no_source"] is True and "No cost source" in p13["rationale"]
    assert p12["chosen"] is not None
    assert (await lead.c.get(f"/api/v1/bid-settlements/{sid}/ai/proposals", params={"no_source": "true"})).json()["total"] == 1

    # working proposals: a member estimator (lowest allowed role) may accept
    ok = await est.c.post(f"/api/v1/settlement-ai-proposals/{p11['id']}/decision", json={"action": "accept"})
    assert ok.status_code == 200 and ok.json()["status"] == "accepted"
    assert (await est.c.post(f"/api/v1/settlement-ai-proposals/{p12['id']}/decision", json={"action": "nonsense"})).status_code == 422
    assert (await est.c.post(f"/api/v1/settlement-ai-proposals/{p11['id']}/decision", json={"action": "accept"})).status_code == 409
    assert (await est.c.post(f"/api/v1/settlement-ai-proposals/{p13['id']}/decision", json={"action": "accept"})).status_code == 422  # no source
    manual = await est.c.post(f"/api/v1/settlement-ai-proposals/{p13['id']}/decision", json={"action": "manual", "manual_unit_cost": "1200", "note": "phone quote"})
    assert manual.status_code == 200 and manual.json()["status"] == "overridden"
    # ...and an estimator who is NOT on the project sees and can do nothing (RLS)
    outsider = Actor(client, monkeypatch, frozenset({Role.ESTIMATOR.value}))
    assert (await outsider.c.post(f"/api/v1/settlement-ai-proposals/{p12['id']}/decision", json={"action": "accept"})).status_code in (403, 404)
    assert (await outsider.c.get(f"/api/v1/bid-settlements/{sid}/ai/proposals")).json()["total"] == 0

    # bulk accept: estimator denied, lead allowed, threshold floor enforced
    assert (await est.c.post(f"/api/v1/bid-settlements/{sid}/ai/proposals:bulk-accept", json={})).status_code == 403
    bulk = await lead.c.post(f"/api/v1/bid-settlements/{sid}/ai/proposals:bulk-accept", json={"min_confidence": 0.85})
    assert bulk.status_code == 200 and bulk.json()["accepted"] == 1   # 1.2 (the cheaper quote)
    assert (await lead.c.post(f"/api/v1/bid-settlements/{sid}/ai/proposals:bulk-accept", json={"min_confidence": 0.1})).status_code == 422

    # the costs really landed on the settlement lines (rates authoritative)
    detail = (await lead.c.get(f"/api/v1/bid-settlements/{sid}")).json()
    lines = detail.get("lines") or (await lead.c.get(f"/api/v1/bid-settlements/{sid}/lines")).json()
    costs = {l["boq_line_item_id"]: l["direct_unit_cost"] for l in lines}
    assert float(costs[str(sc["items"]["1.2"].id)]) == 10.0 and float(costs[str(sc["items"]["1.3"].id)]) == 1200.0
    assert float(costs[str(sc["items"]["1.1"].id)]) == 95.0


async def test_markup_advice_over_http_is_advisory(authed_client, client, monkeypatch, app_engine, _fakes):
    sc = await _seed(authed_client, app_engine)
    lead = await _member(client, monkeypatch, app_engine, sc["pid"], Role.LEAD_ESTIMATOR.value)
    before = (await lead.c.get(f"/api/v1/bid-settlements/{sc['sid']}")).json()
    r = await lead.c.post(f"/api/v1/bid-settlements/{sc['sid']}/ai/markup-advice", json={})
    assert r.status_code == 202 and r.json()["kind"] == "markup"
    await _worker(r.json()["id"], lead.sub)
    run = (await lead.c.get(f"/api/v1/settlement-ai-runs/{r.json()['id']}")).json()
    assert run["status"] == "ready" and [o["label"] for o in run["result"]["options"]] == ["competitive", "balanced", "protective"]
    assert all("margin_on_sell_pct" in o and "tender_total" in o for o in run["result"]["options"])
    after = (await lead.c.get(f"/api/v1/bid-settlements/{sc['sid']}")).json()
    assert before["default_markup_pct"] == after["default_markup_pct"]   # nothing was applied


async def test_not_found(authed_client, client, monkeypatch, app_engine):
    sc = await _seed(authed_client, app_engine)
    lead = await _member(client, monkeypatch, app_engine, sc["pid"], Role.LEAD_ESTIMATOR.value)
    assert (await lead.c.get(f"/api/v1/settlement-ai-runs/{uuid.uuid4()}")).status_code == 404
    assert (await lead.c.post(f"/api/v1/settlement-ai-proposals/{uuid.uuid4()}/decision", json={"action": "reject"})).status_code == 404
    assert (await lead.c.post(f"/api/v1/bid-settlements/{uuid.uuid4()}/ai/cost-proposals", json={})).status_code == 404
