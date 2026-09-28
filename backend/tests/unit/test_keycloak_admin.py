"""KeycloakAdminClient (app/integrations/keycloak_admin.py) -- Phase 3
(docs/ui-qa-brief.md) gap-fill: GET /users needs the backend to call
Keycloak's admin API directly, which has no tenant concept of its own, so
the tenant segregation has to be enforced here. Mocks Keycloak's admin API
with respx rather than hitting a real Keycloak -- fast, deterministic, and
exercises the one thing that actually matters: does a caller in tenant A
ever see tenant B's users."""

from __future__ import annotations

import httpx
import respx

from app.core.config import Settings
from app.integrations.keycloak_admin import KeycloakAdminClient

_REQUIRED = dict(
    APP_DATABASE_URL="postgresql://x/y",
    MIGRATOR_DATABASE_URL="postgresql://x/y",
    S3_ENDPOINT="http://s3.test",
    VLLM_API_BASE="http://vllm.internal:8000/v1",
    KEYCLOAK_BASE_URL="http://keycloak.test",
    KEYCLOAK_REALM="installtec",
    KEYCLOAK_CLIENT_ID="installtec-backend",
    KEYCLOAK_CLIENT_SECRET="test-secret",
)

TENANT_A = "8f14e45f-ceea-4e97-8d0c-3d3b3f3c1a00"
TENANT_B = "9f14e45f-ceea-4e97-8d0c-3d3b3f3c1a00"

# Real shape, confirmed live against the dev Keycloak: GET /groups only
# returns TOP-LEVEL groups (here, "tenants") with no attributes populated on
# them even with briefRepresentation=false -- every actual tenant group is
# one level down ("/tenants/a", "/tenants/b"), only visible via
# GET /groups/{parent_id}/children, which is where "attributes" actually
# appears. A first version of this test mocked a flat /groups response
# matching neither shape, which passed against the mock but 403'd for a
# different reason (a missing role) and then returned an empty list against
# the real stack once that was fixed, for THIS reason -- fixed here to match
# reality, not just to make the mock convenient.
_TOP_LEVEL_GROUPS = [{"id": "tenants-parent", "path": "/tenants", "subGroupCount": 2, "attributes": {}}]
_TENANT_GROUPS = [
    {"id": "group-a", "path": "/tenants/a", "subGroupCount": 0, "attributes": {"tenant_id": [TENANT_A]}},
    {"id": "group-b", "path": "/tenants/b", "subGroupCount": 0, "attributes": {"tenant_id": [TENANT_B]}},
]
_GROUP_A_MEMBERS = [
    {"id": "user-1", "username": "estimator1", "email": "estimator1@demo.local", "enabled": True},
    {"id": "user-2", "username": "lead1", "email": "lead1@demo.local", "enabled": True},
]


def _settings() -> Settings:
    return Settings(**_REQUIRED)  # type: ignore[arg-type]


def _mock_common(router: respx.Router) -> None:
    router.post("http://keycloak.test/realms/installtec/protocol/openid-connect/token").mock(
        return_value=httpx.Response(200, json={"access_token": "svc-token", "expires_in": 60})
    )
    router.get("http://keycloak.test/admin/realms/installtec/groups").mock(
        return_value=httpx.Response(200, json=_TOP_LEVEL_GROUPS)
    )
    router.get("http://keycloak.test/admin/realms/installtec/groups/tenants-parent/children").mock(
        return_value=httpx.Response(200, json=_TENANT_GROUPS)
    )


@respx.mock
async def test_list_tenant_users_only_returns_the_matching_tenants_group_members():
    _mock_common(respx.mock)
    respx.mock.get("http://keycloak.test/admin/realms/installtec/groups/group-a/members").mock(
        return_value=httpx.Response(200, json=_GROUP_A_MEMBERS)
    )
    # Every real Keycloak role-mappings response also includes its own
    # composite/default roles (default-roles-<realm>, offline_access,
    # uma_authorization) alongside the app's actual roles -- included here
    # to prove they get filtered out, not just omitted from the fixture.
    respx.mock.get("http://keycloak.test/admin/realms/installtec/users/user-1/role-mappings/realm").mock(
        return_value=httpx.Response(
            200, json=[{"name": "estimator"}, {"name": "default-roles-installtec"}, {"name": "offline_access"}]
        )
    )
    respx.mock.get("http://keycloak.test/admin/realms/installtec/users/user-2/role-mappings/realm").mock(
        return_value=httpx.Response(
            200, json=[{"name": "lead_estimator"}, {"name": "estimator"}, {"name": "default-roles-installtec"}]
        )
    )

    client = KeycloakAdminClient(_settings())
    users = await client.list_tenant_users(TENANT_A)

    assert [u["username"] for u in users] == ["estimator1", "lead1"]
    assert users[0]["roles"] == ["estimator"]
    assert users[1]["roles"] == ["estimator", "lead_estimator"]  # sorted, noise roles dropped


@respx.mock
async def test_list_tenant_users_never_calls_the_members_endpoint_for_a_different_tenants_group():
    """The actual security property: tenant A's caller must never even
    fetch tenant B's group membership, let alone return it."""
    _mock_common(respx.mock)
    members_route = respx.mock.get("http://keycloak.test/admin/realms/installtec/groups/group-b/members").mock(
        return_value=httpx.Response(200, json=[{"id": "user-9", "username": "other-tenant-user", "enabled": True}])
    )
    respx.mock.get("http://keycloak.test/admin/realms/installtec/groups/group-a/members").mock(
        return_value=httpx.Response(200, json=[])
    )

    client = KeycloakAdminClient(_settings())
    users = await client.list_tenant_users(TENANT_A)

    assert users == []
    assert members_route.call_count == 0


@respx.mock
async def test_list_tenant_users_fails_closed_when_no_group_matches_the_tenant():
    _mock_common(respx.mock)

    client = KeycloakAdminClient(_settings())
    users = await client.list_tenant_users("00000000-0000-0000-0000-000000000000")

    assert users == []
