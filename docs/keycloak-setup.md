# Keycloak setup and authentication flow

## Realm import

`deploy/keycloak/realm-installtec.json` is imported automatically by
`start-dev --import-realm` (dev compose) on first boot. It defines:

- Realm `installtec`, TOTP MFA policy (`otpPolicyType: totp`), and
  `requiredActions.CONFIGURE_TOTP` with `defaultAction: true` — every new
  user is forced to enrol an authenticator app on first login. The realm
  file is shared with production, so it always ships this **secure** default
  (Level 1 `auth-otp-form` `REQUIRED`); see "Turning MFA off in dev/test"
  below for the only way MFA is ever switched off.
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

## RESOLVED: "Cookie not found" over plain HTTP (Phase 10)

Running Keycloak via `start-dev` directly on `http://localhost:8080` (no
TLS-terminating reverse proxy in front) causes Keycloak to mark its
`AUTH_SESSION_ID`/`KC_RESTART` login-flow cookies `Secure; SameSite=None` —
which browsers (correctly) refuse to send back over plain HTTP, so the
interactive login form itself fails with "Cookie not found. Please make
sure cookies are enabled in your browser," even though cookies **are**
enabled. This reproduces with a scripted Authorization Code + PKCE flow
against a bare `docker run` Keycloak, and is unrelated to `sslRequired`
(tested with both `external` and `none` — no effect) — it's driven by
Keycloak/Quarkus's own HTTP layer, not the realm's SSL policy. Chrome
treating `http://localhost` as a secure *context* for Web APIs does not
change this: the `Secure` cookie attribute requires the transport itself to
be TLS, not just an origin browsers are willing to trust.

**This did not affect direct-grant token issuance** (used for admin
scripting) or the resource-server side (JWT validation of an already-issued
token) — only the interactive browser login form specifically, when
accessed without TLS. Fixed in Phase 10 by giving dev a real (if
self-signed) TLS hop, the same shape as prod — see the next section.

## Interactive browser login in dev

`make up` now also starts `caddy-dev` (`deploy/docker-compose.override.dev.yml`
+ `deploy/caddy/Caddyfile.dev`), a `tls internal` (locally-generated,
self-signed) reverse proxy in front of both Keycloak and the frontend on
**one** origin, `https://localhost:8443`, path-routed exactly like
`deploy/caddy/Caddyfile` routes prod (`/realms/*` etc. → Keycloak, `/api/*`
→ backend, everything else → frontend). This is what makes the interactive
login form work: the browser's connection to Keycloak's login pages is now
genuinely TLS, so its `Secure` cookies round-trip correctly.

`deploy/.env.example`'s defaults follow this: `KEYCLOAK_PUBLIC_URL` and
`KEYCLOAK_HOSTNAME` both point at `https://localhost:8443` (`KEYCLOAK_HOSTNAME`
takes a full URL, not just a bare hostname, on Keycloak 26's hostname-v2
provider — this is what makes every issued token's `iss` match
`KEYCLOAK_PUBLIC_URL` regardless of which port a token *request* actually
arrived on), and `COOKIE_SECURE=true` (the backend's own `__Host-`-prefixed
session/CSRF cookies hard-require `Secure` too — `COOKIE_SECURE=false`, the
old default from when dev had no TLS anywhere, meant the browser was
silently dropping them on every login, a second pre-existing bug
independent of Keycloak's own cookies; see the Phase 10 build-log entry).
Bearer-token/API/CLI access (`make dev-token`, `curl localhost:8001/...`)
is unaffected and keeps working over the existing plain-HTTP ports —
`deploy/keycloak/dev-token.sh` deliberately still talks to Keycloak's own
`:8080` directly, not through `caddy-dev`, since a password-grant request
doesn't need TLS and the issuer Keycloak stamps into the token is fixed by
`KEYCLOAK_HOSTNAME` regardless of which port the request arrived on.
**`dev-token.sh` only works when `APP_ENV` is `dev` or `test`**: it relies
on `bootstrap.sh` having both created the demo user with a known password
*and* disabled direct grant's "Conditional OTP" subflow, and `bootstrap.sh`
now only does either under that same guard (`deploy/keycloak/lib-env-guard.sh`)
— outside dev/test there's no known password to use, and a plain
password-grant request 400s the moment the target user has a real OTP
credential, which every seeded demo user does.

**First time hitting `https://localhost:8443`**, Chrome will show a
certificate warning (the cert is self-signed, generated locally by
`caddy-dev` and cached in the `caddy_dev_data` volume across restarts) —
click through it (Advanced → Proceed) once per browser profile; Playwright
tests instead pass `ignoreHTTPSErrors: true`
(`frontend/playwright.real-backend.config.ts`).

**Every demo user already has a working login** (`make bootstrap-keycloak`,
also run automatically by `frontend/e2e/real-backend`'s Playwright global
setup): a permanent password and a dev-fixed TOTP credential, seeded
directly rather than through the enrolment UI, so `estimator1` /
`Estimator1Pass!` (see `deploy/keycloak/bootstrap.sh` for the rest) plus its
6-digit code work immediately at `https://localhost:8443`. Each user's
raw TOTP secret and its base32 form (for a real authenticator app, or
`otplib` — see `frontend/e2e/real-backend/totp.ts`'s `DEMO_TOTP_SECRETS`,
which must match `bootstrap.sh`'s `seed_totp` calls) are dev/test only,
guarded there by `APP_ENV`, and printed by `bootstrap.sh`'s own output.

**To instead test genuine QR-code enrolment** as a human would (the SRS's
actual first-login experience): run
`deploy/keycloak/dev-reset-totp-user.sh <user> <pass>` first, which removes
that user's seeded credential and puts `CONFIGURE_TOTP` back, then:

1. Go to `https://localhost:8443`, click "Sign in", enter the username and
   the password just given to the reset script.
2. Keycloak shows a QR code to configure an authenticator app (Google
   Authenticator, Authy, etc.) — scan it, or click "Unable to scan?" for
   the raw secret to enter manually — then enter the 6-digit code it
   produces and submit.
3. You land back in the app, logged in.

Re-run `make bootstrap-keycloak` afterwards to put the dev-fixed credential
back (its own idempotency handles this correctly either way).

**Approving anything needs a step further still**: a real MFA step-up
(`acr=silver`, `fix/keycloak-step-up`) — Approve/Reject/RFQ-dispatch all
403 with `urn:installtec:step-up-required` the first time in a session,
which `lib/api.ts` turns into a full-page redirect through Keycloak's
`browser-stepup` flow (`deploy/keycloak/realm-installtec.json`): the Cookie
authenticator reattaches the existing bronze session, so this is just the
incremental OTP step (the same dev-fixed secret), not password again. It
must be entered again within `STEP_UP_MAX_AGE_S` (default 300s,
`app/core/config.py`) of the last time, matching the flow's own
`loa-max-age=300` for level 2, so a stale-but-still-valid `acr=silver`
session/token can't be reused indefinitely (`app/security/deps.py::has_recent_step_up`
checks `auth_time`, not just `acr`, for exactly this reason). See
docs/build-log.md's `fix/keycloak-step-up` entry for the full design and
the gap it closes (an `acr.loa.map` with no flow behind it, which meant no
real login could ever reach `acr=silver` at all before this).

**The built-in Keycloak account console is disabled** (`bootstrap.sh`
disables the `account`/`account-console` clients) — this app has its own
frontend and never links to it, and it would otherwise let a user delete
their only OTP credential and step around the step-up requirement.

## Turning MFA off in dev/test (`DEV_DISABLE_MFA`)

A dev/test-only switch, off by default (`DEV_DISABLE_MFA=false` in
`deploy/.env.example`). It turns off **both** MFA layers together:

- **Login OTP** — `deploy/keycloak/bootstrap.sh` sets Level 1's
  `auth-otp-form` to `DISABLED` and `CONFIGURE_TOTP`'s `defaultAction` to
  `false`, but **only** when `APP_ENV` is exactly `dev` or `test` **and**
  `DEV_DISABLE_MFA=true`. Any other `APP_ENV`, `APP_ENV` unset, or any other
  value of the flag fails closed: OTP `REQUIRED`, `CONFIGURE_TOTP` default —
  and re-running the script restores that on an already-configured realm.
  `realm-installtec.json` is never changed by the switch.
- **Step-up** — `has_recent_step_up` (`backend/app/security/deps.py`) passes
  without a genuine step-up, logs a `mfa_step_up_bypassed` WARNING, and the
  audit event of the guarded action (approval decision, RFQ dispatch/resend)
  gets `mfa_bypassed_dev: true` in its payload. A genuine step-up is never
  flagged. The backend and every worker **refuse to start** if
  `DEV_DISABLE_MFA=true` while `APP_ENV` is not explicitly `dev`/`test`.
- The frontend shows a persistent **"DEV: MFA disabled"** banner (from
  `GET /auth/me` → `mfa_disabled_dev`).

Flip it with `make dev-mfa-off` / `make dev-mfa-on`
(`deploy/keycloak/dev-set-mfa.sh`: sets the key in `deploy/.env`, re-runs the
Keycloak bootstrap, recreates the backend/workers). The seeded dev TOTP
secrets stay, so turning MFA back on needs no re-enrolment.

Tests: `login.spec.ts` fails if Keycloak and the backend disagree about the
mode. Specs that complete a step-up adapt (`settlement.spec.ts`,
`modal-replacements.spec.ts`); `step-up-freshness.spec.ts` skips loudly with
MFA off, and `deploy/keycloak/test-stepup-freshness.sh` turns MFA on for its
run and restores the previous value afterwards.

## Admin runbook: lost TOTP / password reset (account console disabled)

With `account`/`account-console` disabled (above), a user has **no
self-service** way to reset a lost authenticator or change their own
password — every case below is an admin action via `kcadm.sh` (the same CLI
`bootstrap.sh`/`dev-token.sh` already use), either from a shell with network
access to Keycloak's admin API, or via `docker exec` into the Keycloak
container as these examples do for the dev container name. Substitute the
real container/host and an admin session for that environment; nothing
below is dev-specific.

```bash
KCADM="/opt/keycloak/bin/kcadm.sh"
REALM="installtec"          # or the real realm name
USERNAME="someone"          # the affected user

# One-time per shell: authenticate the CLI against Keycloak's admin API.
docker exec -it installtec_keycloak $KCADM config credentials \
    --server http://localhost:8080 --realm master \
    --user "$KEYCLOAK_ADMIN" --password "$KEYCLOAK_ADMIN_PASSWORD"

USER_ID=$(docker exec installtec_keycloak $KCADM get users -r "$REALM" \
    -q username="$USERNAME" -q exact=true --fields id --format csv --noquotes | tr -d '\r')
```

**Lost TOTP device** (user can still log in with their password but has no
working authenticator): delete their `otp` credential(s) and re-require
enrolment on next login — Keycloak will show them a fresh QR code
automatically, no admin involvement needed after this:

```bash
docker exec installtec_keycloak $KCADM get "users/${USER_ID}/credentials" -r "$REALM" \
    --fields id,type --format csv --noquotes | tr -d '\r' | grep ,otp$
# for each matching credential id:
docker exec installtec_keycloak $KCADM delete "users/${USER_ID}/credentials/<credential-id>" -r "$REALM"

docker exec installtec_keycloak $KCADM update "users/${USER_ID}" -r "$REALM" \
    -s 'requiredActions=["CONFIGURE_TOTP"]'
```

Also clear any brute-force lockout left over from the failed attempts that
likely prompted this (harmless no-op if there isn't one):

```bash
docker exec installtec_keycloak $KCADM delete "attack-detection/brute-force/users/${USER_ID}" -r "$REALM"
```

**Forgotten/compromised password**: set a new one directly. `--temporary`
(the default when `-p`/`--new-password` is omitted from an interactive
prompt) forces a change on next login instead of handing the user a
permanent one outright — prefer that unless the new password is already
being communicated to the user out-of-band right before they log in:

```bash
docker exec installtec_keycloak $KCADM set-password -r "$REALM" \
    --username "$USERNAME" --new-password "<temporary-value>" --temporary
```

If they've also lost their TOTP device, combine both: run the credential
deletion above first, then the password reset — they'll be prompted for a
new password (if temporary) followed immediately by fresh TOTP enrolment on
their next login, exactly the SRS's original first-login sequence.

`deploy/keycloak/dev-reset-totp-user.sh` automates this exact sequence but
is **dev/test only** (it sets a known, non-temporary password and is meant
for resetting the seeded demo users between Playwright runs, not for a real
user in a real environment) — use the commands above directly against any
other environment.

## What was actually verified end-to-end (Phase 8a, Phase 10, fix/keycloak-step-up)

Phase 8a, against a real, freshly-imported Keycloak 26 container: realm
import (roles/groups/clients created correctly via the Admin REST API),
password grant token issuance with `tenant_id` + `realm_access.roles`
claims present, and a full `create vendor → list vendors` round trip
through the real FastAPI app, real Postgres (with RLS), and a real
Keycloak-issued, cryptographically validated JWT. The interactive
Authorization Code browser flow was blocked by the cookie issue above and
not completed live at the time.

Phase 10 completed the login itself live: a real Playwright browser
driving the actual Keycloak login form end to end
(`frontend/e2e/real-backend/login.spec.ts`, `npm run e2e:real-backend`),
plus real-backend happy paths for procurement (package → RFQ draft) and
settlement up through submit (submitter blocked by segregation of duties).

`fix/keycloak-step-up` completed the rest: `settlement.spec.ts` now runs
the whole lifecycle live, including a different real user (`md1`) actually
completing a real MFA step-up (password already satisfied via the reattached
session, a fresh OTP code from the same dev-fixed credential) and the
settlement reaching `approved` for real — no mocks, no synthetic
`RequestContext(acr="silver")` shortcuts anywhere in that path.
