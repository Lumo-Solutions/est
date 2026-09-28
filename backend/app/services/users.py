from __future__ import annotations

from typing import Any

from app.core.config import Settings
from app.core.context import RequestContext
from app.integrations.keycloak_admin import KeycloakAdminClient


async def list_tenant_users(ctx: RequestContext, settings: Settings) -> list[dict[str, Any]]:
    client = KeycloakAdminClient(settings)
    return await client.list_tenant_users(str(ctx.tenant_id))
