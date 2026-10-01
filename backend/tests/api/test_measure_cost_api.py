"""Measure-on-demand and the AI cost estimate at the HTTP boundary: who may open/measure a drawing (estimator+), who may
bulk-measure and read/confirm a cost estimate (lead_estimator+), who may change the auto-measure list (managing_director),
and the shapes the UI reads. Lowest allowed role and a denied role per permission."""

from __future__ import annotations

import hashlib
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import Role
from tests.api.test_tender_intake_api import TENANT, _seed_project, _sub_of

pytestmark = pytest.mark.asyncio

_SYSTEM = "SELECT set_config('app.tenant_id', :t, false), set_config('app.is_system', 'on', false)"


@pytest.fixture(autouse=True)
def _sends(monkeypatch):
    from app.workers.tasks import dwg, takeoff
    from app.workers.tasks import tender_intake as intake

    sent: list = []
    for task in (takeoff.index_sheets, takeoff.index_drawing_light, dwg.convert_dwg, intake.dispatch_intake):
        monkeypatch.setattr(task, "apply_async", lambda *a, _n=task.name, **k: sent.append((_n, k.get("priority"))) or type("T", (), {"id": "t"})())
    return sent


async def _drawing(app_engine, project_id: str, name: str, *, discipline: str, status: str = "indexed") -> str:
    async with AsyncSession(app_engine) as session, session.begin():
        await session.execute(text(_SYSTEM), {"t": TENANT})
        return str(
            (
                await session.execute(
                    text(
                        "INSERT INTO drawings (tenant_id, project_id, original_filename, kind, bucket, object_key, size_bytes, sha256, status, discipline_hint) "
                        "VALUES (:t, :p, :n, 'vector_pdf', 'b', :k, 10, :h, :s, :d) RETURNING id"
                    ),
                    {"t": TENANT, "p": project_id, "n": name, "k": f"k/{name}", "h": hashlib.sha256(name.encode()).hexdigest(), "s": status, "d": discipline},
                )
            ).scalar_one()
        )


async def _join(app_engine, project_id, client) -> None:
    async with AsyncSession(app_engine) as session, session.begin():
        await session.execute(text(_SYSTEM), {"t": TENANT})
        await session.execute(
            text("INSERT INTO project_members (project_id, user_id, tenant_id) VALUES (:p, :u, :t)"),
            {"p": project_id, "u": await _sub_of(client), "t": TENANT},
        )


async def test_opening_a_drawing_measures_it_and_the_list_says_which_state_it_is_in(authed_client, app_engine, _sends):
    est = authed_client(frozenset({Role.ESTIMATOR.value}))
    project_id, _ = await _seed_project(app_engine, member_sub=await _sub_of(est))
    did = await _drawing(app_engine, project_id, "R-1.pdf", discipline="roads_civil")
    listing = (await est.get(f"/api/v1/projects/{project_id}/drawings")).json()
    assert listing[0]["status"] == "indexed" and listing[0]["measurement"] == "indexed"
    resp = await est.post(f"/api/v1/drawings/{did}/measure")
    assert resp.status_code == 202 and resp.json() == {"state": "queued"}
    assert ("app.workers.tasks.takeoff.index_sheets", 0) in _sends  # highest priority: someone is looking at it
    again = (await est.get(f"/api/v1/drawings/{did}")).json()
    assert (again["status"], again["measurement"]) == ("queued", "queued")
    assert (await est.post(f"/api/v1/drawings/{did}/measure")).json() == {"state": "queued"}  # idempotent
    assert sum(1 for n, _p in _sends if n.endswith("index_sheets")) == 1


async def test_platform_admin_and_unauthenticated_cannot_measure(authed_client, app_engine, client):
    project_id, _ = await _seed_project(app_engine, member_sub=None)
    did = await _drawing(app_engine, project_id, "R-2.pdf", discipline="sewer")
    assert (await client.post(f"/api/v1/drawings/{did}/measure")).status_code == 401
    admin = authed_client(frozenset({Role.PLATFORM_ADMIN.value}))
    assert (await admin.post(f"/api/v1/drawings/{did}/measure")).status_code == 403


async def test_bulk_measure_is_lead_only_audited_and_by_discipline(authed_client, app_engine, _sends):
    est = authed_client(frozenset({Role.ESTIMATOR.value}))
    project_id, _ = await _seed_project(app_engine, member_sub=await _sub_of(est))
    ids = [await _drawing(app_engine, project_id, f"r{i}.pdf", discipline="roads_civil") for i in range(3)]
    await _drawing(app_engine, project_id, "s.pdf", discipline="sewer")
    await _drawing(app_engine, project_id, "done.pdf", discipline="roads_civil", status="ready")
    url = f"/api/v1/projects/{project_id}/drawings/measure"
    assert (await est.post(url, json={"disciplines": ["roads_civil"]})).status_code == 403
    lead = authed_client(frozenset({Role.LEAD_ESTIMATOR.value}))
    await _join(app_engine, project_id, lead)
    assert (await lead.post(url, json={})).status_code == 422  # name what to measure
    resp = await lead.post(url, json={"disciplines": ["roads_civil"]})
    assert resp.status_code == 202 and resp.json() == {"matched": 3, "queued": 3, "measuring": 0, "measured": 0, "skipped": 0}
    assert [p for n, p in _sends if n.endswith("index_sheets")] == [6, 6, 6]  # behind anything a person opens (0)
    summary = (await lead.get(f"/api/v1/projects/{project_id}/drawings/measurement-summary")).json()
    assert summary["total"] == {"indexed": 1, "queued": 3, "measuring": 0, "measured": 1, "failed": 0}
    assert summary["by_discipline"]["sewer"]["indexed"] == 1
    async with AsyncSession(app_engine) as session, session.begin():
        await session.execute(text(_SYSTEM), {"t": TENANT})
        events = (await session.execute(text("SELECT payload FROM audit_events WHERE payload->>'event' = 'measure_drawings'"))).scalars().all()
    assert events and events[-1]["disciplines"] == ["roads_civil"] and events[-1]["matched"] == 3 and len(ids) == 3


async def test_the_auto_measure_list_is_managing_director_only_and_defaults_to_none(authed_client, app_engine):
    lead = authed_client(frozenset({Role.LEAD_ESTIMATOR.value}))
    assert (await lead.get("/api/v1/tender-intake/settings")).json()["auto_measure_disciplines"] == []
    assert (await lead.put("/api/v1/admin/intake-settings", json={"auto_measure_disciplines": ["sewer"]})).status_code == 403
    md = authed_client(frozenset({Role.MANAGING_DIRECTOR.value}))
    assert (await md.put("/api/v1/admin/intake-settings", json={"auto_measure_disciplines": ["made_up"]})).status_code == 422
    out = await md.put("/api/v1/admin/intake-settings", json={"auto_measure_disciplines": ["sewer", "roads_civil"]})
    assert out.status_code == 200 and out.json()["auto_measure_disciplines"] == ["roads_civil", "sewer"] and out.json()["auto_accept_min"] == 0.85
    out2 = await md.put("/api/v1/admin/intake-settings", json={"auto_accept_min": 0.9})  # either field alone
    assert out2.json()["auto_accept_min"] == 0.9 and out2.json()["auto_measure_disciplines"] == ["roads_civil", "sewer"]


async def test_cost_estimate_and_confirmation_are_lead_only(authed_client, app_engine):
    est = authed_client(frozenset({Role.ESTIMATOR.value}))
    project_id, package_id = await _seed_project(app_engine, member_sub=await _sub_of(est))
    assert (await est.get(f"/api/v1/tender-packages/{package_id}/cost-estimate")).status_code == 403
    assert (await est.post(f"/api/v1/tender-packages/{package_id}/confirm-cost", json={"accepted_usd": 1})).status_code == 403
    lead = authed_client(frozenset({Role.LEAD_ESTIMATOR.value}))
    await _join(app_engine, project_id, lead)
    out = (await lead.get(f"/api/v1/tender-packages/{package_id}/cost-estimate")).json()
    assert out["package_id"] == package_id and set(out) >= {
        "provider", "external", "files_needing_ai", "models", "total_usd", "any_unverified", "within_budget", "confirmation_required", "note",
    }
    # The test deployment's provider is local: no per-call cost, nothing to confirm.
    assert out["external"] is False and out["total_usd"] == 0 and out["confirmation_required"] is False
    done = await lead.post(f"/api/v1/tender-packages/{package_id}/confirm-cost", json={"accepted_usd": 0})
    assert done.status_code == 200 and done.json()["confirmed_at"] is not None
    assert (await lead.post(f"/api/v1/tender-packages/{uuid.uuid4()}/confirm-cost", json={"accepted_usd": 0})).status_code == 404


async def test_the_usage_view_reports_cached_tokens_and_marks_the_unverified_rate(authed_client, app_engine):
    md = authed_client(frozenset({Role.MANAGING_DIRECTOR.value}))
    async with AsyncSession(app_engine) as session, session.begin():
        await session.execute(text(_SYSTEM), {"t": TENANT})
        for model, cached in (("qwen3.7-flash", 1500), ("qwen3.7-plus", 0)):
            await session.execute(
                text(
                    "INSERT INTO ai_calls (tenant_id, task, provider, model, input_sha256, tokens_in, tokens_cached, tokens_out, cost_usd, status, external) "
                    "VALUES (:t, 'usage_probe', 'openai_compatible', :m, :h, 2000, :c, 100, 0.00004, 'ok', true)"
                ),
                {"t": TENANT, "m": model, "h": uuid.uuid4().hex * 2, "c": cached},
            )
    rows = {r["model"]: r for r in (await md.get("/api/v1/admin/ai-usage")).json()["rows"] if r["task"] == "usage_probe"}
    assert rows["qwen3.7-flash"]["tokens_cached"] == 1500 and rows["qwen3.7-flash"]["rate_verified"] is True
    assert rows["qwen3.7-plus"]["rate_verified"] is False  # not yet checked against an invoice
