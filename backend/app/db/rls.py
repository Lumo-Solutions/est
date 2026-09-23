from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import RequestContext

# GUC contract (see docs/security-rls.md). Every business-table RLS policy
# reads these via the app_tenant_id()/app_user_id()/app_has_role()/
# app_is_system() SQL helper functions created in migration 0001.
_SET_GUCS_SQL = text(
    "SELECT set_config('app.tenant_id', :tenant_id, true), "
    "       set_config('app.user_id', :user_id, true), "
    "       set_config('app.roles', :roles, true), "
    "       set_config('app.is_system', :is_system, true)"
)


async def set_rls_context(session: AsyncSession, ctx: RequestContext) -> None:
    """Sets the transaction-local (SET LOCAL semantics via set_config(..., true))
    GUCs that every RLS policy checks. Must be called inside an open transaction
    on the connection the caller is about to run business queries on -- it resets
    automatically on COMMIT/ROLLBACK, which is what makes this pool-safe."""
    await session.execute(
        _SET_GUCS_SQL,
        {
            "tenant_id": str(ctx.tenant_id),
            "user_id": str(ctx.user_id) if ctx.user_id else "",
            "roles": ",".join(sorted(ctx.roles)),
            "is_system": "on" if ctx.is_system else "off",
        },
    )
    import os
    if os.environ.get("RLS_DEBUG"):
        from sqlalchemy import text as _t
        r = await session.execute(_t("SELECT current_setting('app.tenant_id', true), current_setting('app.roles', true), current_setting('app.is_system', true)"))
        print("RLS_DEBUG set_rls_context ->", r.first(), flush=True)
