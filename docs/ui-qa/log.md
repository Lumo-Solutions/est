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
**Status: in progress — blocked this run before any page was tested.**

Branch `phase-2-functional-qa` created off `master`.

Environment notes from resuming this session (Docker Desktop was not
running when the session started):
- Restarted Docker Desktop; all `docker compose` containers came back up
  except `installtec_caddy_dev`, which had exited (code 255) shortly
  after the daemon restart (likely started before backend/frontend were
  healthy — not root-caused further since a plain `docker start` fixed
  it and it has stayed up since). Worth a health/depends_on check if it
  recurs.
- The interactive Playwright MCP browser (used for live click-through QA,
  as opposed to the `npm run e2e:real-backend` test suite) had never
  actually been pointed at `https://localhost:8443` before in this
  project's QA history — Phase 0/1's "confirmed live" evidence came from
  running real Playwright *test files* (whose own `playwright.*.config.ts`
  already sets `ignoreHTTPSErrors: true`), not from interactive MCP
  browsing. Doing that for the first time hit `ERR_CERT_AUTHORITY_INVALID`
  against caddy-dev's self-signed cert, exactly the case brief section 0.5
  anticipates. Fixed by adding a project-scoped `.mcp.json`
  (`3113dc1`, branch `phase-2-functional-qa`) that overrides the global
  `playwright` MCP server entry with `--ignore-https-errors`. **This
  requires an MCP reconnect (new session) to take effect** — the
  already-running MCP process for a given session can't pick up new args.
  The Chrome extension (`claude-in-chrome`) was also tried as a fallback
  and is not connected/installed on this machine, so Playwright MCP
  (fixed as above) is the path forward for live browser QA here.

Net effect from that part of the run: no page had been walked through live
yet via the interactive browser.

**Update, same session, later run:** the `.mcp.json` fix did not take
effect for either a fresh subagent fork or the main session itself (both
still hit `ERR_CERT_AUTHORITY_INVALID`) — project-scoped MCP server config
changes need a full Claude Code session restart, which wasn't available.
Trying to work around it by importing caddy-dev's CA cert into the Windows
trust store was correctly blocked by the permission system as a TLS-trust
change. **Pivoted to the sanctioned alternative already used successfully
in Phase 0/1**: driving real Playwright test specs against
`playwright.real-backend.config.ts` (which already sets
`ignoreHTTPSErrors: true` and needs no cert workaround) instead of the
interactive MCP browser tool. This doubles as the regression-test
deliverable rather than being a separate throwaway exploration step.
Interactive MCP/Chrome browsing for this project remains blocked until a
session restart happens naturally; future Phase 2 runs should keep using
the Playwright-test-runner approach rather than retrying the interactive
browser.

**Also discovered and fixed while getting live QA working**: `frontend`'s
Docker image is a static production build (`deploy/docker-compose.yml`'s
`frontend` service has no dev volume mount or hot reload) — source edits
under `frontend/src` do **not** take effect until the image is rebuilt
(`docker compose ... build frontend && ... up -d frontend`). Any future
Phase 2/3/4 run that edits frontend source must rebuild+recreate the
`frontend` container before re-testing, or it will silently test the old
bundle (this is exactly what caused an initial round of test failures in
this run, before the rebuild).

**Pages covered this run**: ProjectsListPage, ProjectDetailPage,
SheetIndexPage, TakeoffViewerPage — as `estimator`. See
`docs/ui-qa/issues.md` for the full write-up. Summary: found and fixed 4
P1s (no catch-all 404 route; every 4xx retried 3x before the UI showed an
error, ~7-10s of misleading "Loading..." app-wide; TakeoffViewerPage's own
additional indefinite-loading-on-error bug; no breadcrumbs/back-links
anywhere in the app, patched on these 4 pages). Logged 2 P2s for Phase 4
(header shows the raw Keycloak subject UUID instead of a username — needs
a backend `RequestContext`/`/auth/me` change, deliberately deferred rather
than folded in here; ProjectsListPage has no empty-state message or
pagination). Reconfirmed the pre-existing `dev-simulate-settlement`
non-idempotency already logged in Phase 0/1 (still non-fatal). Flagged but
did not confirm: GEO-TEST's fixture drawing has been stuck in status
`extracting` since 2026-09-24 despite having sheets/entities already —
possibly just a hand-built fixture that skipped the real status
transition, needs checking against a drawing from real ingestion.

New regression tests: `frontend/e2e/real-backend/project-pages.spec.ts`,
8 tests, all passing against the rebuilt frontend image (verified
individually and as a group: 1 batch of 3 + 5 run singly, all green;
`npx playwright test --config=playwright.real-backend.config.ts
--workers=1 project-pages.spec.ts`).

**Not yet covered** (next Phase 2 run): TypologyPage, BoqImportWizardPage,
BoqReconciliationPage, the 4 procurement pages, SettlementPage, ExportPage,
WinLossPage, AdminPage, AuditPage — as their full role matrix, plus the
cross-cutting nav-hidden-page-still-403s-server-side check from
`coverage.md` §4. The breadcrumb/back-link gap (UI-P2-004) should be
checked on all of them too, and probably resolved as one Phase 4
design-system item rather than N more one-off patches if it's confirmed
everywhere.

### Pages 5-8: TypologyPage, BoqImportWizardPage, BoqReconciliationPage, ProcurementPackagesPage

**Status: done.** Tested as estimator/lead_estimator (the roles that reach
these pages). See `docs/ui-qa/issues.md` UI-P2-007 through UI-P2-010 for
full writeups; summary here.

Found and fixed 3 P1s, all the same class of bug the prior run's UI-P2-001/
002 already established (an action a role can't perform stayed fully
visible/enabled instead of hidden, and failed 100% silently on a real
403):
- **TypologyPage**: "Detect clusters"/"Review and confirm"/"Reject" had no
  role gate at all, though the server restricts them to lead_estimator/
  procurement_head/managing_director (notably **not** estimator or
  bd_director, unlike most other project pages). Added the gate; also wired
  up `detect.isError`/`reject.isError` display, and (defensively, not
  independently live-triggered) fixed `useTypologyClusters`'s fetch-error
  case falling through to an empty list.
- **ProcurementPackagesPage**: "Create package" had no role gate (server:
  lead/proc/bd/md, not estimator) and zero error feedback anywhere except
  "Draft RFQs". Added the gate plus error display on create/add-items/
  dispatch/resend, and disabled Dispatch/Resend while pending (was letting
  a double-click fire two dispatch attempts).
- **ProcurementPackagesPage**, separately: the trade-node dropdown rendered
  `TradeNodeOut.path` — a Postgres ltree built from node **ids**
  (`n073ec3ef_6b2f_...`), meant only for hierarchical queries, not display
  — instead of `.name`. Fixed. **Same bug spotted (not fixed, out of this
  run's page scope) in `TaxonomyAdmin.tsx`'s two dropdowns** — flagging for
  whoever QAs `/admin`.

**Significant gap surfaced, not fixed here (Phase 3's call):** writing the
lead_estimator regression test above hit "Not a member of project ..." —
none of the CLI's simulate/seed fixtures ever add the *real* Keycloak dev
users (`estimator1`, `lead1`, ...) as `ProjectMember`, only their own
synthetic ids. Combined with the already-known "no add-member UI" gap
(Phase 1's `coverage.md` §2), **a real lead_estimator or estimator cannot
be given access to an existing project through the product at all.**
Added `frontend/e2e/real-backend/helpers.ts`'s `ensureProjectMember()` as
a tested workaround so later Phase 2 runs (settlement, BOQ reconciliation
actions, etc.) don't hit the same wall blind — every remaining
estimator/lead_estimator write-path test will need it. Recommending this
get a higher priority than a generic Phase 3 item, since it currently
blocks realistic QA of most of the product as those two roles.

**Confirmed, not fixed (explicit Phase 3 item):** still no delete-BOQ-item
UI on `BoqReconciliationPage` (`DELETE /boq-items/{id}` exists, unused).

**Cross-cutting note for Phase 4 / whoever QAs Settlement/Quotes/Export:**
`backend/app/schemas/common.py`'s `JsonDecimal` serializes every money/
percentage field to a JSON **number** (`float(v)`), not the string the
brief's §0.2 assumes arrives from the API — precision loss, if any, already
happens server-side, before any frontend `parseFloat` could touch it. Also
confirmed **no shared money-formatting utility exists anywhere in the
frontend** — every money display so far is ad-hoc `.toFixed(2)`, no
thousands separator, no "AED" prefix. Neither is a Phase-2-page-scoped fix;
flagging for a deliberate decision rather than fixing in passing.

Breadcrumb/back-link gap (`UI-P2-004`) reconfirmed on all 4 of these pages
too — still not patched one-off, per the prior run's recommendation (one
shared Phase 4 component instead).

New regression tests: `frontend/e2e/real-backend/typology-boq-procurement.spec.ts`,
6 tests. Every test across both files (`project-pages.spec.ts`'s 8 plus
these 6) has passed individually and in small groups. Running all 14
together sequentially, back to back, is flaky: two separate full-combined
runs each saw 1-2 failures, but never the same test twice, and every
"failure" passed cleanly on an immediate isolated re-run with no code
changes in between (one `ECONNRESET` on the first `GET /api/v1/projects`
of a run; separately a `SheetIndexPage` test and the `BoqImportWizardPage`
upload test each failed once, both green on retry). This points to the
dev stack (backend connection pool, or Keycloak's own session/rate
handling) not comfortably sustaining 14 back-to-back real logins +
full-page navigations in one `--workers=1` run, not a real regression in
any of the fixes above. Worth root-causing if it gets worse as more
Phase 2 specs accumulate, but not blocking — `npm run e2e:real-backend`'s
CI-facing run should be watched for the same pattern.

Commits this run: `chore(qa): configure Playwright MCP...` and
`docs(ui-qa): log Phase 2 start...` were from the earlier
interactive-MCP-blocker investigation (see above); this pages-5-8 work is
`fix(frontend): role-gate Typology and ProcurementPackages writes, fix
trade-name display, add missing error feedback`, `test(e2e): Phase 2
real-backend coverage for typology/BOQ/procurement`, and a `docs(ui-qa):`
log/issues update.

**Not yet covered** (next Phase 2 run): SettlementPage, ExportPage,
WinLossPage, the remaining procurement pages (quarantine, quotes,
bid-leveling), AdminPage, AuditPage, plus the cross-cutting
nav-hidden-page-still-403s-server-side check from `coverage.md` §4. Any
run testing estimator/lead_estimator writes should use the new
`ensureProjectMember()` helper up front.

## Phase 3: gap-fill
Not started.

## Phase 4: design system and redesign
Not started.

## Phase 5: final regression and report
Not started.
