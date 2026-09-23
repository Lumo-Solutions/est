# Keycloak setup and authentication flow

## Realm import

`deploy/keycloak/realm-installtec.json` is imported automatically by
`start-dev --import-realm` (dev compose) on first boot. It defines:

- Realm `installtec`, TOTP MFA policy (`otpPolicyType: totp`), and
  `requiredActions.CONFIGURE_TOTP` with `defaultAction: true` — every new
  user is forced to enrol an authenticator app on first login.
- The 5 SRS roles (`estimator`, `lead_estimator`, `procurement_head`,
  `bd_director`, `managing_director`) as **realm roles**.
- A `/tenants/demo` group carrying the `tenant_id` user attribute
  (`8f14e45f-ceea-4e97-8d0c-3d3b3f3c1a00`), inherited by any user added to
  that group.
- A client scope `installtec-claims` with three protocol mappers: a
  `tenant_id` user-attribute mapper, an audience mapper adding
  `installtec-backend` to `aud`, and a realm-role mapper populating
  `realm_access.roles`. This is the **only** client scope defined — a
  from-scratch realm import does not get Keycloak's normal built-in
  `profile`/`email`/`roles` scopes for free, so `defaultClientScopes` on
  both clients lists only `installtec-claims` (an earlier version listed
  the built-ins too, which just produced import warnings and did nothing).
- Two clients: `installtec-backend` (confidential, standard flow only,
  `directAccessGrantsEnabled: false`) and `installtec-frontend` (public,
  PKCE `S256` required).

Run `make bootstrap-keycloak` after `make up` to set the backend client's
secret from `.env` and seed one demo user per role (via `kcadm.sh`,
idempotent).

## Token validation (`app/security/jwt.py`)

`TokenValidator.validate()`:
- fetches the signing key via `PyJWKClient` (kid-miss triggers one forced
  JWKS refresh, handling Keycloak key rotation without a restart)
- `jwt.decode(..., algorithms=["RS256"], audience=..., issuer=..., leeway=...)`
  with a **hard-coded** algorithm allowlist — never reads `alg` from the
  token header, which is what prevents an `alg: none` downgrade attack
  (verified in `tests/unit/test_jwt_validation.py::test_alg_none_is_rejected`)
- checks `azp` is one of the known clients, extracts and UUID-validates the
  `tenant_id` claim (missing or non-UUID → hard failure, never a silent
  default tenant), and maps `realm_access.roles` through
  `security/roles.py::map_realm_roles()`, which **drops** any role not in
  the known set of 5 (`default-roles-installtec`, `offline_access`,
  `uma_authorization`, etc. never leak into `RequestContext.roles`)

**Regression note**: `_signing_key()` originally only caught
`jwt.PyJWKClientError`, but `PyJWKClient.get_signing_key_from_jwt()` parses
the token header itself (before `jwt.decode()`'s own try/except ever runs),
so a garbage/malformed `Authorization: Bearer ...` header raised an
uncaught `jwt.exceptions.DecodeError` — a 500, not the intended 401. Fixed
by also catching `DecodeError` there; see
`tests/api/test_auth_flow.py::test_malformed_bearer_token_returns_401`.

## Session model (the "BFF" pattern, decision A4)

The browser never sees an access or refresh token — only an opaque,
`HttpOnly`+`Secure`+`SameSite=Lax` session-id cookie
(`__Host-ins_sid`). `app/security/sessions.py::SessionStore` keeps the real
tokens server-side in Redis, keyed by that opaque id. A separate
non-`HttpOnly` cookie (`__Host-ins_csrf`) carries a CSRF token the frontend
echoes back as an `X-CSRF-Token` header on mutating requests
(`security/csrf.py`, double-submit pattern) — bearer-token requests
(`Authorization: Bearer ...`) are exempt, since CSRF only matters when the
browser is auto-attaching credentials.

`GET /auth/login` → PKCE challenge + `state`/`nonce` stashed in Redis →
redirect to Keycloak. `GET /auth/callback` exchanges the code, validates the
access token, and creates the Redis session. `POST /auth/logout` revokes it
and does an RP-initiated logout redirect. `GET /auth/step-up` re-runs the
same flow with `acr_values=silver&prompt=login` for MFA re-verification
immediately before a sensitive action (see `security/deps.py::require_mfa_step_up`
and `services/approvals.py::decide()`, which both check `ctx.acr`).

**Only `/auth/login`, `/auth/callback`, and `/auth/logout` are
unauthenticated** (`security/public_paths.py::AUTH_ENTRY_POINTS`). An
earlier version exempted the whole `/api/v1/auth/` prefix from
`AuthContextMiddleware`, which meant `GET /auth/me` — which genuinely needs
an authenticated context — silently never got one and always returned 401
regardless of a valid session. Caught by
`tests/api/test_auth_flow.py::test_auth_me_without_token_returns_401` (which
now also has a positive counterpart proving it returns 200 with a valid
token).

## RLS context per request

`AuthContextMiddleware` resolves either the `Authorization: Bearer` header
or the session cookie into a `RequestContext` bound to a `ContextVar`.
`RequestContext.user_id` is the Keycloak `sub` claim parsed directly as a
UUID (`security/identity.py::derive_user_id`) — Keycloak's local users
always have UUID subs by default, so this avoids a DB round-trip per
request just to resolve "who is this" for the RLS `app.user_id` GUC. A
`users` table row is still upserted best-effort for display purposes
(name/email), but authorization and RLS never depend on it.

**Important**: `db/session.py::get_session()` reads the `RequestContext`
via the `current_context()` `ContextVar` directly, *not* via
`Depends(get_current_context)`. This matters for testing — overriding just
the `get_current_context` FastAPI dependency (e.g. via
`app.dependency_overrides`) does **not** reach `get_session()`, which would
raise `LookupError`. `tests/api/conftest.py::authed_client` instead
monkeypatches `TokenValidator.validate()` and sends a dummy Bearer header,
which runs through the real middleware and sets the real ContextVar.

## Known local-dev limitation: "Cookie not found" over plain HTTP

Running Keycloak via `start-dev` directly on `http://localhost:8080` (no
TLS-terminating reverse proxy in front) causes Keycloak to mark its
`AUTH_SESSION_ID`/`KC_RESTART` login-flow cookies `Secure; SameSite=None` —
which browsers (correctly) refuse to send back over plain HTTP, so the
interactive login form itself fails with "Cookie not found. Please make
sure cookies are enabled in your browser," even though cookies **are**
enabled. This reproduces with a scripted Authorization Code + PKCE flow
against a bare `docker run` Keycloak, and is unrelated to `sslRequired`
(tested with both `external` and `none` — no effect) — it's driven by
Keycloak/Quarkus's own HTTP layer, not the realm's SSL policy.

**This does not affect direct-grant token issuance** (used for admin
scripting and this doc's own testing) or the resource-server side (JWT
validation of an already-issued token) — only the interactive browser login
form specifically, when accessed without TLS. **Production deployments are
unaffected**: `deploy/docker-compose.prod.yml` puts Caddy in front with real
TLS, at which point Keycloak sees genuine HTTPS and the cookies work
normally. For **local development** that needs to click through an actual
login page, put a TLS-terminating reverse proxy (even a self-signed one, or
`deploy/caddy/Caddyfile` pointed at `localhost`) in front of Keycloak rather
than hitting its HTTP port directly.

## What was actually verified end-to-end during development

Against a real, freshly-imported Keycloak 26 container: realm import
(roles/groups/clients created correctly via the Admin REST API), password
grant token issuance with `tenant_id` + `realm_access.roles` claims
present, and — after fixing the bugs described above — a full
`create vendor → list vendors` round trip through the real FastAPI app,
real Postgres (with RLS), and a real Keycloak-issued, cryptographically
validated JWT. The interactive Authorization Code browser flow was blocked
by the cookie issue above and was not completed live; the code path itself
(`security/oidc.py`) is unit-adjacent tested via
`tests/unit/test_jwt_validation.py` and is otherwise unchanged from the
manually-verified direct-grant/password-grant validation path (both go
through the same `TokenValidator.validate()`).
