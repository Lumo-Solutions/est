from __future__ import annotations

import pytest

from app.core.enums import Role

pytestmark = pytest.mark.asyncio


async def test_estimator_cannot_create_vendor(authed_client):
    c = authed_client(frozenset({Role.ESTIMATOR.value}))
    resp = await c.post("/api/v1/vendors", json={"legal_name": "Forbidden Co"})
    assert resp.status_code == 403


async def test_lead_estimator_can_create_and_list_vendors(authed_client):
    c = authed_client(frozenset({Role.LEAD_ESTIMATOR.value}))
    create_resp = await c.post(
        "/api/v1/vendors",
        json={"legal_name": "API Test Vendor LLC", "trade_license_no": "API-001", "primary_email": "a@b.com"},
    )
    assert create_resp.status_code == 201
    body = create_resp.json()
    assert body["legal_name"] == "API Test Vendor LLC"
    assert body["status"] == "draft"

    list_resp = await c.get("/api/v1/vendors")
    assert list_resp.status_code == 200
    listed = list_resp.json()
    assert listed["total"] >= 1
    assert any(v["id"] == body["id"] for v in listed["items"])


async def test_get_single_vendor(authed_client):
    c = authed_client(frozenset({Role.LEAD_ESTIMATOR.value}))
    create_resp = await c.post("/api/v1/vendors", json={"legal_name": "Fetchable Vendor Co"})
    vendor_id = create_resp.json()["id"]

    get_resp = await c.get(f"/api/v1/vendors/{vendor_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["legal_name"] == "Fetchable Vendor Co"


async def test_get_nonexistent_vendor_returns_404(authed_client):
    c = authed_client(frozenset({Role.LEAD_ESTIMATOR.value}))
    resp = await c.get("/api/v1/vendors/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404
    assert resp.json()["type"] == "urn:installtec:not-found"


async def test_near_duplicate_vendor_blocked_without_force(authed_client):
    c = authed_client(frozenset({Role.LEAD_ESTIMATOR.value}))
    first = await c.post(
        "/api/v1/vendors",
        json={"legal_name": "Gulf Construction Services LLC", "trade_license_no": "DUP-100"},
    )
    assert first.status_code == 201

    second = await c.post(
        "/api/v1/vendors",
        json={"legal_name": "Gulf Construction Services", "trade_license_no": "DUP-100"},
    )
    assert second.status_code == 409
    assert second.json()["type"] == "urn:installtec:duplicate-vendor"

    forced = await c.post(
        "/api/v1/vendors?force=true",
        json={"legal_name": "Gulf Construction Services", "trade_license_no": "DUP-100"},
    )
    assert forced.status_code == 201


async def test_duplicate_cost_item_code_returns_clean_409(authed_client):
    """Regression test for the bug where a unique-constraint violation
    surfaced as a bare 500 instead of the RFC 9457 IntegrityError handler
    response -- see app/core/errors.py::integrity_error_handler."""
    c = authed_client(frozenset({Role.LEAD_ESTIMATOR.value}))
    payload = {"code": "API-DUP-ITEM", "description": "Test", "uom": "m3", "item_type": "material"}
    first = await c.post("/api/v1/cost-items", json=payload)
    assert first.status_code == 201

    second = await c.post("/api/v1/cost-items", json=payload)
    assert second.status_code == 409
    assert second.json()["type"] == "urn:installtec:conflict"


async def test_check_duplicates_endpoint_does_not_persist_anything(authed_client):
    c = authed_client(frozenset({Role.LEAD_ESTIMATOR.value}))
    resp = await c.post("/api/v1/vendors:check-duplicates", json={"legal_name": "Preview Only Co"})
    assert resp.status_code == 200
    assert resp.json()["candidates"] == []

    listed = await c.get("/api/v1/vendors")
    assert not any(v["legal_name"] == "Preview Only Co" for v in listed.json()["items"])
