from __future__ import annotations

from app.core.enums import Role
from app.security.roles import KNOWN_ROLES, map_realm_roles


def test_known_roles_matches_enum() -> None:
    assert KNOWN_ROLES == {"estimator", "lead_estimator", "procurement_head", "bd_director", "managing_director"}
    assert KNOWN_ROLES == {r.value for r in Role}


def test_map_realm_roles_drops_unknown_keycloak_roles() -> None:
    raw = ["lead_estimator", "default-roles-installtec", "offline_access", "uma_authorization"]
    mapped = map_realm_roles(raw)
    assert mapped == frozenset({"lead_estimator"})


def test_map_realm_roles_keeps_all_known_roles() -> None:
    raw = ["estimator", "lead_estimator", "procurement_head", "bd_director", "managing_director"]
    assert map_realm_roles(raw) == frozenset(raw)


def test_map_realm_roles_empty_or_none_yields_empty_set() -> None:
    assert map_realm_roles(None) == frozenset()
    assert map_realm_roles([]) == frozenset()


def test_map_realm_roles_all_unknown_yields_empty_set() -> None:
    assert map_realm_roles(["platform_admin", "some_other_role"]) == frozenset()
