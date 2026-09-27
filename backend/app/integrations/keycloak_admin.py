from __future__ import annotations

import time
from typing import Any

import httpx

from app.core.config import Settings
from app.core.enums import Role

_TOKEN_EXPIRY_SKEW_S = 30
_APP_ROLE_NAMES = frozenset(r.value for r in Role)


class KeycloakAdminClient:
    """Read-only calls to Keycloak's admin REST API, authenticated as
    installtec-backend's own service account (client_credentials grant --
    see deploy/keycloak/bootstrap.sh, which grants it exactly view-users,
    query-users, and query-groups on the realm-management client, nothing
    else, and
    nothing that can write). Used only by GET /users
    (app/api/v1/routes/users.py) to power an "add project member"/"users &
    roles" screen -- never for anything that mutates Keycloak state.

    Tenant-scoped: Keycloak's admin API has no tenant concept of its own,
    so every call here filters to the group whose "tenant_id" attribute
    matches the caller's tenant -- the same attribute
    deploy/keycloak/realm-installtec.json's group-membership mapper puts
    in every user's JWT. This is the one place in the app that talks to
    Keycloak's admin API directly, so the tenant segregation has to be
    enforced here; there is no Postgres RLS to fall back on for this data.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    @property
    def _admin_base(self) -> str:
        return f"{self._settings.keycloak_base_url}/admin/realms/{self._settings.keycloak_realm}"

    async def _access_token(self) -> str:
        if self._token and time.time() < self._token_expires_at - _TOKEN_EXPIRY_SKEW_S:
            return self._token
        token_endpoint = (
            f"{self._settings.keycloak_base_url}/realms/{self._settings.keycloak_realm}"
            "/protocol/openid-connect/token"
        )
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                token_endpoint,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._settings.keycloak_client_id,
                    "client_secret": self._settings.keycloak_client_secret,
                },
            )
        resp.raise_for_status()
        body = resp.json()
        self._token = body["access_token"]
        self._token_expires_at = time.time() + float(body.get("expires_in", 60))
        return self._token

    async def _get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        token = await self._access_token()
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{self._admin_base}{path}", headers={"Authorization": f"Bearer {token}"}, params=params
            )
        resp.raise_for_status()
        return resp.json()

    async def _tenant_group_id(self, tenant_id: str) -> str | None:
        """Walks the group tree breadth-first looking for the group whose
        "tenant_id" attribute matches. GET /groups only returns TOP-LEVEL
        groups (e.g. "tenants") without their subgroups' own attributes
        populated, even with briefRepresentation=false -- confirmed live,
        every actual tenant group here is a child ("/tenants/demo"), so a
        real GET /groups response has to be walked one level (or more, if
        the tree ever grows deeper) via GET /groups/{id}/children, which
        DOES return attributes, to find it."""
        frontier = await self._get("/groups", params={"briefRepresentation": "false"})
        while frontier:
            next_frontier: list[dict[str, Any]] = []
            for group in frontier:
                if group.get("attributes", {}).get("tenant_id", [None])[0] == tenant_id:
                    return group["id"]
                if group.get("subGroupCount", 0) > 0:
                    next_frontier.extend(await self._get(f"/groups/{group['id']}/children"))
            frontier = next_frontier
        return None

    async def list_tenant_users(self, tenant_id: str) -> list[dict[str, Any]]:
        """Returns [{id, username, email, enabled, roles: [str]}] for every
        member of the caller's tenant group, sorted by username. Empty list
        if the tenant's group can't be found -- fails closed, not open."""
        group_id = await self._tenant_group_id(tenant_id)
        if group_id is None:
            return []
        members = await self._get(f"/groups/{group_id}/members")
        users: list[dict[str, Any]] = []
        for member in members:
            role_mappings = await self._get(f"/users/{member['id']}/role-mappings/realm")
            # Keycloak's own composite/default roles (default-roles-<realm>,
            # offline_access, uma_authorization) show up here too -- every
            # user has them, they're not one of this app's Role enum values,
            # and a "users & roles" screen showing them is just noise.
            app_roles = sorted(r["name"] for r in role_mappings if r["name"] in _APP_ROLE_NAMES)
            users.append(
                {
                    "id": member["id"],
                    "username": member.get("username", ""),
                    "email": member.get("email"),
                    "enabled": member.get("enabled", True),
                    "roles": app_roles,
                }
            )
        users.sort(key=lambda u: u["username"])
        return users
