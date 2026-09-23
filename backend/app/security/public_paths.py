"""Paths reachable without an existing authenticated session/token.

Only the OIDC entry points that MUST work pre-authentication belong here --
login initiates the flow, callback completes it, logout must work even for
an expired/invalid session so the user can always get back to a clean
state. Anything else under /api/v1/auth/ (notably /auth/me and
/auth/step-up) requires a valid session, so do NOT widen this to a bare
"/api/v1/auth/" prefix -- that previously (and incorrectly) exempted
/auth/me from authentication entirely.
"""

from __future__ import annotations

INFRA_PREFIXES = ("/healthz", "/docs", "/openapi.json", "/redoc")

AUTH_ENTRY_POINTS = (
    "/api/v1/auth/login",
    "/api/v1/auth/callback",
    "/api/v1/auth/logout",
)

PUBLIC_PREFIXES = INFRA_PREFIXES + AUTH_ENTRY_POINTS
