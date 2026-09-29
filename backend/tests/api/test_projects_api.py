from __future__ import annotations

import pytest

from app.core.enums import Role

pytestmark = pytest.mark.asyncio


async def test_lead_estimator_can_add_and_list_members(authed_client):
    md = authed_client(frozenset({Role.MANAGING_DIRECTOR.value}))
    create_resp = await md.post("/api/v1/projects", json={"code": "PMAPI-1", "name": "PM API Test"})
    assert create_resp.status_code == 201
    project_id = create_resp.json()["id"]

    lead = authed_client(frozenset({Role.LEAD_ESTIMATOR.value}))
    add_resp = await lead.post(
        f"/api/v1/projects/{project_id}/members", json={"user_id": "11111111-1111-1111-1111-111111111111", "project_role": "estimator"}
    )
    assert add_resp.status_code == 204

    list_resp = await lead.get(f"/api/v1/projects/{project_id}/members")
    assert list_resp.status_code == 200
    body = list_resp.json()
    assert any(m["user_id"] == "11111111-1111-1111-1111-111111111111" and m["project_role"] == "estimator" for m in body)


async def test_estimator_cannot_add_a_member(authed_client):
    md = authed_client(frozenset({Role.MANAGING_DIRECTOR.value}))
    create_resp = await md.post("/api/v1/projects", json={"code": "PMAPI-2", "name": "PM API Test 2"})
    project_id = create_resp.json()["id"]

    estimator = authed_client(frozenset({Role.ESTIMATOR.value}))
    resp = await estimator.post(
        f"/api/v1/projects/{project_id}/members", json={"user_id": "22222222-2222-2222-2222-222222222222"}
    )
    assert resp.status_code == 403


async def test_lead_estimator_can_remove_a_member_and_it_is_audited(authed_client):
    md = authed_client(frozenset({Role.MANAGING_DIRECTOR.value}))
    project_id = (await md.post("/api/v1/projects", json={"code": "PMAPI-3", "name": "PM API Test 3"})).json()["id"]
    user_id = "33333333-3333-3333-3333-333333333333"

    lead = authed_client(frozenset({Role.LEAD_ESTIMATOR.value}))
    assert (await lead.post(f"/api/v1/projects/{project_id}/members", json={"user_id": user_id})).status_code == 204

    resp = await lead.delete(f"/api/v1/projects/{project_id}/members/{user_id}")
    assert resp.status_code == 204
    members = (await lead.get(f"/api/v1/projects/{project_id}/members")).json()
    assert all(m["user_id"] != user_id for m in members)

    # Removing someone who is no longer a member is a 404, not a silent no-op.
    assert (await lead.delete(f"/api/v1/projects/{project_id}/members/{user_id}")).status_code == 404

    # The audit API does not expose payloads; the payload itself is asserted in
    # tests/integration/test_project_member_removal.py.
    events = (await md.get("/api/v1/audit/events", params={"entity_type": "project", "entity_id": project_id})).json()
    assert any(e["action"] == "delete" for e in events)


async def test_estimator_cannot_remove_a_member(authed_client):
    md = authed_client(frozenset({Role.MANAGING_DIRECTOR.value}))
    project_id = (await md.post("/api/v1/projects", json={"code": "PMAPI-4", "name": "PM API Test 4"})).json()["id"]
    user_id = "44444444-4444-4444-4444-444444444444"
    assert (await md.post(f"/api/v1/projects/{project_id}/members", json={"user_id": user_id})).status_code == 204

    estimator = authed_client(frozenset({Role.ESTIMATOR.value}))
    resp = await estimator.delete(f"/api/v1/projects/{project_id}/members/{user_id}")
    assert resp.status_code == 403

    members = (await md.get(f"/api/v1/projects/{project_id}/members")).json()
    assert any(m["user_id"] == user_id for m in members)


async def test_lead_estimator_can_create_a_project_and_becomes_its_owner(authed_client):
    # Item 3 of the logout/mjs/lead-create fix: lead_estimator joins bd/md as
    # a project creator. This goes through the real RLS policy (migration
    # 0029 widened projects' INSERT policy), not just the API role check.
    lead = authed_client(frozenset({Role.LEAD_ESTIMATOR.value}))
    resp = await lead.post("/api/v1/projects", json={"code": "PMAPI-LEAD-1", "name": "Created by a lead"})
    assert resp.status_code == 201, resp.text
    project_id = resp.json()["id"]

    members = (await lead.get(f"/api/v1/projects/{project_id}/members")).json()
    assert [m["project_role"] for m in members] == ["owner"]
    # ...and the creator can immediately read the project back (RLS SELECT).
    assert (await lead.get(f"/api/v1/projects/{project_id}")).status_code == 200


async def test_estimator_cannot_create_a_project(authed_client):
    estimator = authed_client(frozenset({Role.ESTIMATOR.value}))
    resp = await estimator.post("/api/v1/projects", json={"code": "PMAPI-EST-1", "name": "should be refused"})
    assert resp.status_code == 403


async def test_procurement_head_still_cannot_create_a_project(authed_client):
    proc = authed_client(frozenset({Role.PROCUREMENT_HEAD.value}))
    resp = await proc.post("/api/v1/projects", json={"code": "PMAPI-PROC-1", "name": "should be refused"})
    assert resp.status_code == 403


async def test_lead_estimator_still_cannot_edit_a_projects_location(authed_client):
    # Only *creation* was widened; editing location stays bd/md.
    md = authed_client(frozenset({Role.MANAGING_DIRECTOR.value}))
    project_id = (await md.post("/api/v1/projects", json={"code": "PMAPI-LOC-1", "name": "loc"})).json()["id"]
    lead = authed_client(frozenset({Role.LEAD_ESTIMATOR.value}))
    resp = await lead.patch(f"/api/v1/projects/{project_id}/location", json={"emirate": "Dubai"})
    assert resp.status_code == 403
