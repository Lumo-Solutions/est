"""AI-first intake at the HTTP boundary: who may change the auto-accept threshold (managing_director only, audited),
who may read it, who may reclassify (one by one, in bulk, with `confirm`) and see the project's document tree."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import Role
from tests.api.test_tender_intake_api import TENANT, _fakes, _seed_doc, _seed_project, _sub_of  # noqa: F401

pytestmark = pytest.mark.asyncio

ROLES_BELOW_MD = (Role.ESTIMATOR, Role.LEAD_ESTIMATOR, Role.PROCUREMENT_HEAD, Role.BD_DIRECTOR)


async def test_only_the_managing_director_changes_the_threshold_and_everyone_can_read_it(authed_client, app_engine):
    # authed_client hands back ONE shared client whose identity is whichever role was set last: set it before each call.
    def as_(role: Role):
        return authed_client(frozenset({role.value}))

    assert (await as_(Role.MANAGING_DIRECTOR).get("/api/v1/tender-intake/settings")).json() == {"auto_accept_min": 0.85, "default_auto_accept_min": 0.85, "auto_measure_disciplines": [], "ai_classify": False}
    for role in ROLES_BELOW_MD:
        assert (await as_(role).put("/api/v1/admin/intake-settings", json={"auto_accept_min": 0.9})).status_code == 403, role
        assert (await as_(role).get("/api/v1/tender-intake/settings")).status_code == 200, role
    ok = await as_(Role.MANAGING_DIRECTOR).put("/api/v1/admin/intake-settings", json={"auto_accept_min": 0.92})
    assert ok.status_code == 200 and ok.json()["auto_accept_min"] == 0.92
    assert (await as_(Role.ESTIMATOR).get("/api/v1/tender-intake/settings")).json()["auto_accept_min"] == 0.92
    for bad in (0.3, 1.5):
        assert (await as_(Role.MANAGING_DIRECTOR).put("/api/v1/admin/intake-settings", json={"auto_accept_min": bad})).status_code in (400, 422), bad
    assert (await as_(Role.MANAGING_DIRECTOR).get("/api/v1/tender-intake/settings")).json()["auto_accept_min"] == 0.92
    async with AsyncSession(app_engine) as session, session.begin():
        await session.execute(text("SELECT set_config('app.tenant_id', :t, false), set_config('app.is_system', 'on', false)"), {"t": TENANT})
        payloads = (await session.execute(text("SELECT payload FROM audit_events WHERE entity_type = 'tenant_ai_settings' AND payload ? 'intake_auto_accept_min'"))).scalars().all()
    assert {"before": 0.85, "after": 0.92} in [p["intake_auto_accept_min"] for p in payloads]
    # The tenant row is shared by the other tests of this run: leave the default as found.
    assert (await as_(Role.MANAGING_DIRECTOR).put("/api/v1/admin/intake-settings", json={"auto_accept_min": 0.85})).status_code == 200


async def test_reclassify_and_bulk_reclassify_need_lead_estimator_and_confirm_routes(authed_client, app_engine):
    # Every authed_client() call is a new identity (new sub), and project visibility is by membership.
    estimator = authed_client(frozenset({Role.ESTIMATOR.value}))
    lead = authed_client(frozenset({Role.LEAD_ESTIMATOR.value}))
    project_id, package_id = await _seed_project(app_engine, member_sub=await _sub_of(lead))
    a = await _seed_doc(app_engine, project_id, package_id, doc_class="other", name="a.pdf")
    b = await _seed_doc(app_engine, project_id, package_id, doc_class="other", name="b.pdf")

    estimator = authed_client(frozenset({Role.ESTIMATOR.value}))
    assert (await estimator.post(f"/api/v1/tender-documents/{a}/reclassify", json={"doc_class": "contract"})).status_code == 403
    denied_bulk = await estimator.post(
        f"/api/v1/projects/{project_id}/tender-documents/bulk-reclassify", json={"document_ids": [a], "doc_class": "contract"}
    )
    assert denied_bulk.status_code == 403

    lead = authed_client(frozenset({Role.LEAD_ESTIMATOR.value}))  # a new identity again: make it a member too
    async with AsyncSession(app_engine) as session, session.begin():
        await session.execute(text("SELECT set_config('app.tenant_id', :t, false), set_config('app.is_system', 'on', false)"), {"t": TENANT})
        await session.execute(
            text("INSERT INTO project_members (project_id, user_id, tenant_id) VALUES (:p, :u, :t)"),
            {"p": project_id, "u": await _sub_of(lead), "t": TENANT},
        )
    one = await lead.post(f"/api/v1/tender-documents/{a}/reclassify", json={"doc_class": "contract", "confirm": True, "note": "conditions"})
    assert one.status_code == 200, one.text
    body = one.json()
    assert (body["doc_class"], body["status"], body["routed_kind"], body["classified_by"], body["auto_accepted"]) == ("contract", "routed", "register", "user", False)

    bulk = await lead.post(
        f"/api/v1/projects/{project_id}/tender-documents/bulk-reclassify",
        json={"document_ids": [a, b], "doc_class": "specification", "confirm": True},
    )
    assert bulk.status_code == 200, bulk.text
    assert (bulk.json()["confirmed"], bulk.json()["failed"]) == (2, 0)  # a was already routed (contract): re-routed under the new class
    docs = {d["id"]: d for d in (await lead.get(f"/api/v1/projects/{project_id}/tender-documents")).json()["items"]}
    assert {docs[a]["doc_class"], docs[b]["doc_class"]} == {"specification"} and {docs[a]["status"], docs[b]["status"]} == {"routed"}

    bad = await lead.post(f"/api/v1/tender-documents/{a}/reclassify", json={"doc_class": "drawing", "sub_type": "made_up"})
    assert bad.status_code in (400, 422)
    bad_type = await lead.post(f"/api/v1/tender-documents/{a}/reclassify", json={"doc_class": "boq", "drawing_type": "cross_sections"})
    assert bad_type.status_code in (400, 422)


async def test_the_document_tree_is_visible_to_project_members_only_and_counts_what_needs_a_check(authed_client, app_engine):
    estimator = authed_client(frozenset({Role.ESTIMATOR.value}))
    project_id, package_id = await _seed_project(app_engine, member_sub=await _sub_of(estimator))
    await _seed_doc(app_engine, project_id, package_id, doc_class="specification", status="proposed", name="waits.pdf")
    await _seed_doc(app_engine, project_id, package_id, doc_class="contract", status="routed", name="done.pdf")
    await _seed_doc(app_engine, project_id, package_id, doc_class=None, status="received", name="queued.pdf")

    tree = await estimator.get(f"/api/v1/projects/{project_id}/tender-documents/tree")
    assert tree.status_code == 200, tree.text
    body = tree.json()
    assert "items" not in body  # counts only: the files come from /items, a page at a time
    page = await estimator.get(f"/api/v1/projects/{project_id}/tender-documents/items")
    assert page.status_code == 200 and page.json()["total"] == 3
    by_name = {i["name"]: i for i in page.json()["items"]}
    assert by_name["waits.pdf"]["display_status"] == "needs_check" and by_name["done.pdf"]["display_status"] == "ready"
    assert by_name["queued.pdf"]["display_status"] == "queued"
    summary = body["summary"]
    assert (summary["total"], summary["needs_check"], summary["in_progress"]) == (3, 1, 1)
    assert summary["auto_accept_min"] == 0.85 and isinstance(summary["ai_available"], bool)

    outsider = authed_client(frozenset({Role.ESTIMATOR.value}))
    hidden = await outsider.get(f"/api/v1/projects/{project_id}/tender-documents/tree")
    assert hidden.status_code == 200 and hidden.json()["summary"]["total"] == 0  # RLS: a non-member sees nothing
    assert (await outsider.get(f"/api/v1/projects/{project_id}/tender-documents/items")).json()["items"] == []


async def test_unknown_project_gives_an_empty_tree(authed_client):
    client = authed_client(frozenset({Role.ESTIMATOR.value}))
    resp = await client.get(f"/api/v1/projects/{uuid.uuid4()}/tender-documents/tree")
    assert resp.status_code == 200 and resp.json()["summary"]["total"] == 0
