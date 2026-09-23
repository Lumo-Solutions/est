from __future__ import annotations

from app.core.enums import Role

KNOWN_ROLES = frozenset(r.value for r in Role)


def map_realm_roles(realm_roles: list[str] | None) -> frozenset[str]:
    """Intersect the Keycloak realm_access.roles claim with our known role
    set. Unknown roles (platform_admin, offline_access, etc.) are dropped
    rather than propagated -- an authenticated user with zero known roles
    still gets 403'd downstream (require_roles), not silently treated as
    privileged."""
    if not realm_roles:
        return frozenset()
    return frozenset(r for r in realm_roles if r in KNOWN_ROLES)
