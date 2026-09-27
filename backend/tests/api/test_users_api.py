from __future__ import annotations

import httpx
import pytest
import respx

from app.core.enums import Role

pytestmark = pytest.mark.asyncio

# Matches authed_client's fixed tenant_id (tests/api/conftest.py).
TENANT_ID = "8f14e45f-ceea-4e97-8d0c-3d3b3f3c1a00"

_TOP_LEVEL_GROUPS = [{"id": "tenants-parent", "path": "/tenants", "subGroupCount": 1, "attributes": {}}]
_TENANT_GROUPS = [{"id": "demo-group", "path": "/tenants/demo", "subGroupCount": 0, "attributes": {"tenant_id": [TENANT_ID]}}]
_MEMBERS = [{"id": "kc-user-1", "username": "estimator1", "email": "estimator1@demo.local", "enabled": True}]


def _mock_keycloak_admin_api() -> None:
    respx.post("http://keycloak:8080/realms/installtec/protocol/openid-connect/token").mock(
        return_value=httpx.Response(200, json={"access_token": "svc-token", "expires_in": 60})
    )
    respx.get("http://keycloak:8080/admin/realms/installtec/groups").mock(
        return_value=httpx.Response(200, json=_TOP_LEVEL_GROUPS)
    )
    respx.get("http://keycloak:8080/admin/realms/installtec/groups/tenants-parent/children").mock(
        return_value=httpx.Response(200, json=_TENANT_GROUPS)
    )
    respx.get("http://keycloak:8080/admin/realms/installtec/groups/demo-group/members").mock(
        return_value=httpx.Response(200, json=_MEMBERS)
    )
    respx.get("http://keycloak:8080/admin/realms/installtec/users/kc-user-1/role-mappings/realm").mock(
        return_value=httpx.Response(200, json=[{"name": "estimator"}, {"name": "default-roles-installtec"}])
    )


@respx.mock
async def test_estimator_cannot_list_users(authed_client):
    c = authed_client(frozenset({Role.ESTIMATOR.value}))
    resp = await c.get("/api/v1/users")
    assert resp.status_code == 403


@respx.mock
async def test_lead_estimator_can_list_users(authed_client):
    _mock_keycloak_admin_api()
    c = authed_client(frozenset({Role.LEAD_ESTIMATOR.value}))
    resp = await c.get("/api/v1/users")
    assert resp.status_code == 200
    body = resp.json()
    assert body == [
        {"id": "kc-user-1", "username": "estimator1", "email": "estimator1@demo.local", "enabled": True, "roles": ["estimator"]}
    ]
