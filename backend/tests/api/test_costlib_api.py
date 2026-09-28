from __future__ import annotations

import pytest

from app.core.enums import Role

pytestmark = pytest.mark.asyncio


async def test_estimator_cannot_create_cost_item(authed_client):
    c = authed_client(frozenset({Role.ESTIMATOR.value}))
    resp = await c.post("/api/v1/cost-items", json={"code": "API-1", "description": "x", "uom": "m3"})
    assert resp.status_code == 403


async def test_any_authenticated_role_can_list_cost_items(authed_client):
    creator = authed_client(frozenset({Role.LEAD_ESTIMATOR.value}))
    create_resp = await creator.post(
        "/api/v1/cost-items", json={"code": "API-LIST-1", "description": "Cost library API test item", "uom": "m3"}
    )
    assert create_resp.status_code == 201

    reader = authed_client(frozenset({Role.ESTIMATOR.value}))
    resp = await reader.get("/api/v1/cost-items", params={"search": "API-LIST-1"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["code"] == "API-LIST-1"
