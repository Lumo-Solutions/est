from __future__ import annotations

import pytest

from app.core.enums import Role

pytestmark = pytest.mark.asyncio


async def test_any_authenticated_role_can_list_a_vendors_certificates(authed_client):
    creator = authed_client(frozenset({Role.LEAD_ESTIMATOR.value}))
    create_resp = await creator.post("/api/v1/vendors", json={"legal_name": "Certs API Test Co"})
    vendor_id = create_resp.json()["id"]

    # Read-only, no role restriction (matches every other GET in this
    # router) -- estimator is the lowest-privileged role in the app.
    reader = authed_client(frozenset({Role.ESTIMATOR.value}))
    resp = await reader.get(f"/api/v1/vendors/{vendor_id}/certificates")
    assert resp.status_code == 200
    assert resp.json() == []
