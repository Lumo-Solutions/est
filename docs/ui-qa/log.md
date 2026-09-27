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

**Status: done.**

1. **Coverage matrix**: `docs/ui-qa/coverage.md` — every frontend route
   (from `App.tsx`/`AppShell.tsx`) cross-referenced against every backend
   endpoint (`backend/app/api/v1/routes/`), by role and action.

2. **No-UI capabilities confirmed** (all 6 of the brief's candidates,
   verified by grepping `frontend/src` for each resource, not assumed):
   vendor master + duplicate review, prequalification & certificates, cost
   library, and Module E all have real backend endpoints and zero frontend
   page. **Users & roles has no backend endpoint at all yet** — not just
   missing UI; Phase 3 needs a new read-only endpoint calling Keycloak's
   admin API. Saved-scenario delete has neither a UI nor a backend
   endpoint (Phase 3 adds the endpoint, per the brief). Smaller gaps also
   recorded: project edit/members, quotation attachments viewer,
   exclusion-flag acknowledge, fx-rate overrides, BOQ item delete,
   settlement per-trade/per-line overrides — endpoint exists, page exists,
   action doesn't.

3. Two new findings from the route walk itself (not in the brief's list):
   **no catch-all/404 route** in `App.tsx` (an already-built but unused
   `PlaceholderPage.tsx` looks like it was meant for this); and **no
   route-level role guard** beyond authentication — a nav-hidden page is
   still fully reachable by direct URL, relying entirely on its own data
   calls to 403 server-side. Both flagged for a live check in Phase 2.

4. **Demo data seeded**:
   - `make dev-simulate-e2e` (re-run clean after the auth_time fix below):
     full lifecycle, `won` outcome, on E2E-SIM.
   - New `make dev-seed-qa-demo-data` (`python -m app.cli
     seed-qa-demo-data`): its own QA-DEMO project with a **rejected**
     settlement and a **lost**-outcome settlement (D1-SIM already
     accumulates draft/submitted/approved from repeated
     `simulate-settlement` runs, but never rejected/lost, and reusing
     D1-SIM risked its documented non-idempotency gap — see below); a
     vendor **duplicate-candidate pair** (same trade license, near-
     identical names); and a vendor with **3 certificates** (expired,
     expiring in 10 days, valid+verified) for Phase 3's future
     prequalification UI. Idempotent; extended `make dev-clean-demo-data`
     to remove all of it alongside E2E-SIM. Verified: ran twice, second
     run correctly skipped already-seeded vendors/certs.

5. **Real regression found and fixed while seeding**: `make
   dev-simulate-e2e` and `make dev-simulate-settlement` started failing
   with `StepUpRequiredError` right after Phase 0's merge —
   `app/cli.py`'s synthetic `acr="silver"` `RequestContext`s never set
   `auth_time`, which `has_recent_step_up` (correctly) fails closed on.
   Fixed by adding `auth_time=int(time.time())` alongside every
   `acr="silver"` construction, plus a static regression test
   (`test_cli_stepup_contexts.py`) scanning `app/cli.py`'s own source for
   the same mistake in any future `simulate_*`. Committed directly to
   `master` (`abd8b94`) since it broke already-merged tooling, not new
   Phase 1 work. `make test-unit`: 343 passed (342 + 1 new).

### Pre-existing issue re-confirmed, not fixed (already logged under Phase 0)
D1-SIM's settlement pipeline isn't idempotent against its own leftover
state (`make dev-simulate-settlement` still fails this way if run without
a clean start) — this is why Phase 1's new settlement-status coverage
uses its own QA-DEMO project instead of building on D1-SIM.

## Phase 2: functional QA
Not started.

## Phase 3: gap-fill
Not started.

## Phase 4: design system and redesign
Not started.

## Phase 5: final regression and report
Not started.
