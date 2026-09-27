# UI QA and Redesign — running log

Tracks progress against `docs/ui-qa-brief.md`. Resume by reading the last
unfinished phase below.

## Phase 0: finish the Keycloak step-up branch (`fix/keycloak-step-up`)

**Status: done, merged to `master`.**

The branch's core feature work (real LoA-based step-up flow, `auth_time`
freshness check) was already built and committed before this run
(`090ba29`, `5a4791b`, `42aebff`, `a7deb6c`). This run finished the
remaining review item — proving the freshness signal against the real
dev stack — and merged.

1. **Which signal Keycloak 26 actually updates on an OTP-only step-up:**
   `auth_time` (via the `oidc-usersessionmodel-note-mapper` on the
   `installtec-claims` scope, added in `5a4791b`), not `acr` alone and not
   the token's own `iat`. Confirmed live: Level 2's OTP-only execution
   updates the session's `AUTH_TIME` note, which is what
   `has_recent_step_up` (`backend/app/security/deps.py`) reads via
   `(now - ctx.auth_time) <= settings.step_up_max_age_s`.

2. Ran `bash deploy/keycloak/test-stepup-freshness.sh` (lowers Keycloak's
   Level 2 `loa-max-age` and the backend's `STEP_UP_MAX_AGE_S` to 20s for
   the duration, restores 300s afterwards via trap regardless of outcome).
   All three cases in `frontend/e2e/real-backend/step-up-freshness.spec.ts`
   passed on the first run of this session (1 test, 3 assertions, 2.4m):
   - (a) stale LOGIN-time `auth_time`, then a step-up that just
     happened → **approval succeeds** (pass — the step-up itself refreshes
     `auth_time`, so a user who took a while to get around to approving
     something can still step up).
   - (b) that same freshness goes stale after `STEP_UP_MAX_AGE_S` →
     **step-up required again** (pass).
   - (c) a silent SSO re-authorize (`/api/v1/auth/login`, no
     `acr_values`, cookie reattach only, no OTP form shown) →
     **still blocked, not accepted as fresh silver** (pass).
   Settings were restored to the real 300s default afterwards (script's
   own trap; verified in the run's own output).
   No fix was needed — (a) passed on the first run, so no root-cause
   session-note/claim-mapper change was required this time.

3. `make test-all`: **526 passed** (342 unit + 165 integration + 19 API),
   0 failed. `npm run e2e:real-backend -- --workers=1`: **3 passed**
   (`login.spec.ts`, `procurement.spec.ts`, `settlement.spec.ts` — the
   last completing a full real MFA step-up approval), 0 failed.

4. Merged `fix/keycloak-step-up` → `master` (`--no-ff`), not pushed.

Commits made this run (in-progress work found uncommitted at the start of
this session, reviewed and committed):
- `fix(auth): fail closed on demo credential seeding outside dev/test` —
  replaced a deny-list `APP_ENV != production` check with an allow-list
  (`lib-env-guard.sh`'s `is_dev_or_test_env`, exactly `dev`/`test`) around
  seeding known passwords/TOTP secrets and disabling direct grant's
  Conditional OTP, so an unset or misspelled `APP_ENV` refuses instead of
  defaulting to "seed anyway". Also added the admin `kcadm` runbook for
  lost TOTP/password reset to `docs/keycloak-setup.md` (account-console is
  disabled, so this is the only path).
- `test(auth): prove auth_time is the freshness signal Keycloak 26
  refreshes on step-up` — the freshness spec/scripts above, plus a
  pre-existing `completeMfaStepUp` bug fix (it filled a `#password` field
  that Keycloak's Level 2 page never shows, since Level 1 already
  reattached via the Cookie authenticator — this hung until the test's own
  timeout rather than failing fast).

### Pre-existing issue noted, not fixed here (out of Phase 0's scope)
`make dev-simulate-settlement` (and the equivalent step in
`global-setup.ts`) fails on a stack that already has a resolved D1-SIM
settlement fixture from a prior run: "Every settlement line needs a
resolved cost before submission". `global-setup.ts` already tolerates this
non-fatally ("continuing anyway") and both runs this session still passed,
so it isn't blocking, but it means `make dev-simulate-settlement` isn't
idempotent against its own leftover state. Candidate for Phase 1/2 cleanup
(`make dev-clean-demo-data` before re-running, or make the CLI command
itself idempotent).

## Phase 1: inventory and demo data
Not started.

## Phase 2: functional QA
Not started.

## Phase 3: gap-fill
Not started.

## Phase 4: design system and redesign
Not started.

## Phase 5: final regression and report
Not started.
