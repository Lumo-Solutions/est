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
