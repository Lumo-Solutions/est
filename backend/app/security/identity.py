from __future__ import annotations

from uuid import UUID, uuid5

# Namespace for deriving a stable UUID from a non-UUID Keycloak `sub` (some
# federated/legacy user stores don't use UUID subs). Keycloak's own local
# users always have UUID subs, so this fallback should be rare in practice.
_SUB_UUID_NAMESPACE = UUID("6f6f6f6f-0000-4000-8000-000000000000")


def derive_user_id(sub: str) -> UUID:
    """The local `users.id` IS the Keycloak sub when it's already a UUID
    (the default), so RLS's app.user_id GUC can be set without a DB round
    trip on every request. `users` rows are upserted best-effort elsewhere
    for display purposes; this identity mapping is what RLS actually keys on."""
    try:
        return UUID(sub)
    except ValueError:
        return uuid5(_SUB_UUID_NAMESPACE, sub)
