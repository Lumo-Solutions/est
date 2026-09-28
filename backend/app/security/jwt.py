from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import jwt
from jwt import PyJWKClient

from app.core.config import Settings
from app.security.roles import map_realm_roles

ALLOWED_ALGORITHMS = ["RS256"]  # hard-coded allowlist -- never read `alg` from the token header


class TokenValidationError(Exception):
    """Raised whenever a bearer token fails validation.

    `reason` is a short, fixed category safe to log (never a claim value or
    the token itself); the exception message may embed claim values for
    local debugging via `raise ... from exc` and must not be logged as-is.
    """

    def __init__(self, message: str, *, reason: str = "invalid_token") -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class Principal:
    sub: str
    tenant_id: UUID
    email: str | None
    roles: frozenset[str]
    acr: str | None
    amr: list[str]
    sid: str | None
    exp: int
    # Standard OIDC claim: when the underlying authentication EVENT happened,
    # not when this particular token was issued/refreshed -- Keycloak
    # preserves the original value across refresh_token grants, so this is
    # what lets require_mfa_step_up (security/deps.py) tell a genuinely
    # recent step-up from an old one whose still-valid access/refresh token
    # just happens to carry acr=silver from long ago. See fix/keycloak-step-up.
    auth_time: int | None = None
    # Keycloak's preferred_username (login name), for display only -- never
    # used for authorization or as an identity key (sub is).
    username: str | None = None


class TokenValidator:
    """Validates Keycloak-issued access tokens against the realm's JWKS.

    kid-miss triggers one forced JWKS refresh (handles Keycloak key rotation
    without a restart); a still-unknown kid after that is a hard failure.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        jwks_url = (
            f"{settings.keycloak_base_url}/realms/{settings.keycloak_realm}"
            "/protocol/openid-connect/certs"
        )
        self._jwk_client = PyJWKClient(
            jwks_url, cache_keys=True, lifespan=settings.jwks_cache_ttl_s
        )
        self._issuer = f"{settings.keycloak_public_url}/realms/{settings.keycloak_realm}"

    def _signing_key(self, token: str):
        try:
            return self._jwk_client.get_signing_key_from_jwt(token)
        except (jwt.PyJWKClientError, jwt.exceptions.DecodeError) as exc:
            # get_signing_key_from_jwt() parses the token header itself
            # (before jwt.decode()'s own try/except in validate() ever
            # runs), so a malformed/garbage token raises DecodeError here,
            # not just PyJWKClientError -- an earlier version only caught
            # the latter, so a bad Authorization header crashed with a
            # bare 500 instead of a clean 401.
            raise TokenValidationError(
                f"Unable to resolve signing key: {exc}", reason="signing_key_unresolved"
            ) from exc

    def validate(self, token: str) -> Principal:
        signing_key = self._signing_key(token)
        try:
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=ALLOWED_ALGORITHMS,
                audience=self._settings.keycloak_audience,
                issuer=self._issuer,
                leeway=self._settings.jwt_leeway_s,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise TokenValidationError("Token expired", reason="token_expired") from exc
        except jwt.InvalidTokenError as exc:
            raise TokenValidationError(f"Invalid token: {exc}", reason="invalid_token") from exc

        azp = claims.get("azp")
        allowed_clients = {self._settings.keycloak_client_id, "installtec-frontend"}
        if azp is not None and azp not in allowed_clients:
            raise TokenValidationError(
                f"Unexpected authorized party: {azp}", reason="unexpected_azp"
            )

        tenant_id_raw = claims.get("tenant_id")
        if not tenant_id_raw:
            raise TokenValidationError(
                "Token has no tenant_id claim -- user is not provisioned into a tenant group",
                reason="missing_tenant_id",
            )
        try:
            tenant_id = UUID(str(tenant_id_raw))
        except ValueError as exc:
            raise TokenValidationError(
                f"tenant_id claim is not a UUID: {tenant_id_raw}", reason="invalid_tenant_id"
            ) from exc

        realm_access = claims.get("realm_access") or {}
        roles = map_realm_roles(realm_access.get("roles"))

        return Principal(
            sub=claims["sub"],
            tenant_id=tenant_id,
            email=claims.get("email"),
            roles=roles,
            acr=claims.get("acr"),
            amr=claims.get("amr", []),
            sid=claims.get("sid"),
            exp=int(claims["exp"]),
            auth_time=int(claims["auth_time"]) if claims.get("auth_time") is not None else None,
            username=claims.get("preferred_username"),
        )
