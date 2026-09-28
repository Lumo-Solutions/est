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
**Status: in progress — pages 1-11 of ~15 done (see below); Settlement,
Export, Win/loss, Admin, Audit and the cross-cutting permission checks
remain.**

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

### Main-session fix, between Phase 2 runs: the JsonDecimal sweep was genuinely incomplete
Following up the "cross-cutting note" above, the main session found the
prior note's framing was only half the story: `JsonDecimal` (float-not-
string) was the design, but it had only ever been applied to
`settlement.py`/`approvals.py` (`docs/build-log.md`'s own Phase 10 "known
gaps carried forward" already flagged this, unfixed until now). Five
response fields in `app/schemas/quotation_ingestion.py` — read by the
already-shipped `QuoteReviewPage`/`BidLevelingPage` — and two in
`app/schemas/module_e.py` (no frontend yet) still used bare `Decimal`,
which serializes to JSON as a **string** while every matching
`frontend/src/types/api.ts` field is typed `number`. This was live, not
latent. Fixed both files, added
`backend/tests/unit/test_response_schema_json_decimal.py` (a static sweep
across every `ORMModel` subclass in `app/schemas`, so this can't
reintroduce itself). `make test-unit` (344 passed) and `make test-api` (19
passed) green. See `docs/ui-qa/issues.md` UI-P2-011.

## Phase 2 — pages 9-11: QuarantineQueuePage, QuoteReviewPage, BidLevelingPage
Tested as procurement_head/estimator, plus confirming platform_admin's one
action is untestable (see below). Mechanism: same as pages 5-8, the
real-backend Playwright test runner (not the interactive MCP browser,
still unreliable this session).

**Found and fixed 2 P1s** (both live-confirmed):
- **QuarantineQueuePage**: `list_inbound_review_queue`
  (`backend/app/services/quotation_ingestion.py`) filtered on
  `review_status == "open"` alone, but `review_status` defaults to `"open"`
  for *every* inbound email, including ones auto-processed successfully and
  never needing a human at all. Confirmed live against the real dev
  ("demo") tenant: 19 ordinary matched emails sat in the queue forever
  alongside the 4 that actually needed attention. Added a
  `needs_review == True` filter. This is a backend service-layer fix, not
  a page-scoped one — reviewed carefully since it touches what a real
  procurement head sees as needing action; it does not touch RLS, auth, or
  any write path, only which rows a read query returns. New integration
  test (`test_review_queue_excludes_auto_processed_emails_that_never_needed_review`,
  10 passed in the file, up from 9).
- **QuoteReviewPage**: same recurring pattern as UI-P2-007/UI-P2-008 —
  Accept/Reject/Reject-quotation/Set-currency/Promote had no client-side
  role gate at all (server: procurement_head/bd_director/
  managing_director only, notably not even lead_estimator) and zero error
  feedback on any of the five mutations. Added the gate and error display.

**Confirmed, not fixed — needs a decision, not a page patch:**
- `QuarantineQueuePage` lives at a project-scoped URL
  (`/projects/:id/procurement/quarantine`) but its data is entirely
  tenant-wide, not project-specific (the underlying endpoint takes no
  `project_id` at all) — opening any two projects' quarantine queues shows
  the identical list. Fixing this means either moving it to a real global
  route or adding project scoping to `InboundEmail` (schema change) —
  flagging for Phase 3/4 rather than guessing which.
- **No `platform_admin` demo user exists anywhere** in this repo (checked
  `bootstrap.sh`'s `seed_user` calls and every real-backend spec) — its one
  exclusive action, "Resolve tenant" on an unknown-tenant quarantine row,
  cannot be exercised live by anyone right now, even though 3 real rows
  needing exactly that sit in the dev database. Recommending a seeded
  `admin1` user the same way the other five roles are.
- BidLevelingPage confirmed read-only (no role gate needed — deliberately
  checked, not assumed) but has no empty-state message for a package with
  zero bid-leveling rows (P2, Phase 4).

**JsonDecimal fix (UI-P2-011) verified live** on both pages it actually
affects: `unit_price`/`quantity`/`confidence`/`normalized_unit_price` all
confirmed `typeof === 'number'` end to end against the real backend, and
rendering correctly in the DOM.

New regression tests: `frontend/e2e/real-backend/
quarantine-quotes-bidleveling.spec.ts`, 6 tests, all passing (one full run,
5.3m, no flakiness this time). Commits: `fix(backend): quarantine queue
excludes auto-processed emails`, `fix(frontend): role-gate QuoteReviewPage
review actions`, `test(e2e): Phase 2 coverage for quarantine/quotes/
bid-leveling`, `docs(ui-qa): log pages 9-11 results`.

**Not yet covered:** SettlementPage, ExportPage, WinLossPage, AdminPage,
AuditPage, the cross-cutting nav-hidden-page-still-403s check.

## Phase 2 — pages 12-14: SettlementPage, ExportPage, WinLossPage

**Status: done.** Also fixed a real money-serialization gap the main
session found while reviewing the previous batch (see below, not part of
this batch's own page walk).

This batch carried an explicit escalation instruction (SettlementPage
touches MFA step-up, SoD and money math): fix the routine role-gate/error-
display pattern as usual, but stop and flag anything auth/money/SoD/step-
up-structural for the main session instead of fixing it directly.
**Nothing needed escalation.** The one borderline case — Approve/Reject's
role eligibility beyond the existing SoD check — was deliberately left
alone rather than guessed at (see UI-P2-018): `app/services/
approvals.py::decide` authorizes against the specific routed approval
tier's `required_role`, which is dynamic (margin-threshold-driven) and not
exposed on `BidSettlementOut` for an already-submitted request, so a
client-side role gate there risks getting it wrong in either direction.
Logged as a P2 UX gap for Phase 3/4 instead (expose the routed tier's role
so the UI can show/hide correctly) — the server enforces it correctly
either way, so this is not a security issue, just a missing affordance.

1. **SettlementPage** (UI-P2-018, P1, fixed): "Build (new) settlement
   draft" and "Submit for approval" had no client-side role gate at all
   (mirrors backend's `_HEADER_ROLES`/`_SUBMIT_ROLES` — same recurring
   pattern as every other page this phase) and no error display on
   build/submit/decide, nor on the settlement fetch itself. Fixed. The
   existing SoD disable (a submitter can't approve their own request) and
   the pre-existing 3dp margin-on-sell display were both already correct
   and untouched.
   - **Confirmed still green, not re-run mocked:** re-read (didn't need to
     touch) the pre-existing `settlement.spec.ts` (Phase 0) — its real,
     unmocked build → submit → approve flow with a genuine MFA step-up
     (bd1 submits, SoD disables their own Approve, md1 completes a real
     OTP step-up and approves) is unaffected by this batch's changes since
     bd1/md1 both already have every role this batch gates on.
2. **ExportPage**: no bugs found. Confirmed live that a non-approved
   settlement's export correctly 403s with a clear message
   ("...export is only available once approved") shown under the button,
   not hidden — acceptable UX for a state-based (not role-based)
   restriction. Confirmed by reading the route that `_LINE_ROLES` (all 5
   roles) is correct here — no missing gate. UI-P2-020 (P2, Phase 4): the
   real `Content-Disposition` filename is `settlement-{project_id}-
   v{n}.xlsx` — a raw UUID, not the project's human-readable code — works
   correctly but isn't very readable in a downloads folder.
3. **WinLossPage** (UI-P2-019, P1, fixed): the record-outcome form
   (outcome, prices, reason codes, note, submit) had no client-side role
   gate (mirrors `_OUTCOME_ROLES`) — at least this one already showed
   `recordOutcome.isError`, so failure wasn't silent, but the form was
   misleadingly presented as usable to any role. Fixed: an unauthorized
   role now sees "No outcome recorded yet. Only bd_director/
   managing_director can record it." instead.

**Separately, main-session fix (money, handled directly per brief §0.3,
not part of this batch's page walk):** while reviewing the previous
batch's cross-cutting money note, found the `JsonDecimal` sweep (UI-P2-011)
was itself incomplete — `quotation_ingestion.py` (5 response schemas,
including fields `QuoteReviewPage`/`BidLevelingPage` actually read — this
was live, not latent) and `module_e.py` (2 more, latent — no frontend yet)
still used bare `Decimal`, which serializes to JSON as a string against
frontend types declared `number`. Fixed both files, added a static
introspection test (`backend/tests/unit/test_response_schema_json_decimal.py`)
scanning every `ORMModel` subclass across `app/schemas/*.py` so this can't
silently reintroduce. `make test-unit` (344 passed), `make test-api` (19
passed). Commit `1d6955c`.

New regression tests: `frontend/e2e/real-backend/
settlement-winloss-roles.spec.ts`, 4 tests — 2 passed live (submit-gate,
win-loss-gate), 2 correctly skip with a clear reason tied to D1-SIM's
current shared-fixture state (build-gate needs a REBUILDABLE_STATUSES
status; export-download needs `approved`) rather than being flaky —
verified individually, not just trusting a single combined run.

## Phase 2 — AdminPage, AuditPage, cross-cutting permission matrix (final chunk)

**Status: done. Phase 2 as a whole is now complete.**

1. **AdminPage** (UI-P2-021, P1, fixed): none of the six tabs
   (Taxonomy/Approval policies/Tolerances/Layer-mapping/Reason codes/
   Vendor regions) had any client-side role gate — the by-now-familiar
   pattern, just not yet applied here. Added a `hasRole` gate per tab
   mirroring each endpoint's real server role list (confirmed by reading
   every route file, not assumed): Taxonomy/Tolerances/Layer-mapping =
   lead/proc/md; **Approval policies = managing_director only**; Reason
   codes/Vendor regions = lead/proc/bd/md. Disabled per-row edit widgets
   for non-writing roles, added missing `isError` displays on every
   mutation. Also fixed, in passing, the `TaxonomyAdmin.tsx` raw-ltree-
   path dropdown bug already flagged (not yet fixed) under UI-P2-009.
2. **UI-P2-022** (P1, confirmed via code reading — no live test possible,
   flagged for a product decision, not fixed): `platform_admin` is
   nav-gated into both `/admin` and `/audit`, but is in **none** of the
   six Admin tabs' write-role lists, nor `/audit`'s read role list, nor
   `/audit/verify`'s. After this run's fix, `/admin` correctly renders
   read-only for `platform_admin` — but `/audit` would 403 immediately on
   load. Two of this role's three nav-visible destinations are either
   read-only or broken. Could be intentional (the brief frames
   `platform_admin` as narrow — quarantine tenant-resolution only) or a
   real gap; recommending the main session/user decide whether to narrow
   the nav gates or widen the backend role lists, rather than guessing.
3. **AuditPage**: mostly already correct (md-only verify gate, list-query
   error display already present) — added the one missing `isError`
   display on `verifyChain`. Confirmed server enforcement matches: `bd1`
   can view but not verify (direct `GET /audit/verify` 403s); `estimator1`
   hitting `/audit` by direct URL (nav-hidden) gets a real, informative
   error ("Requires one of roles: ...") with no table — not a leak.
4. **Cross-cutting permission matrix** (coverage.md §4): spot-checked
   nav-hidden-but-URL-reachable pages and a couple of un-tested direct-API
   writes. One check initially looked like a P0 data leak — `estimator`
   reaching `SettlementPage` by direct URL saw full tender/margin
   figures — but investigating the actual route roles (not just assuming)
   showed this is genuine, intentional server-granted access
   (`_LINE_ROLES` includes `estimator`), not a leak; the real finding is
   the same shape as UI-P2-022 (**UI-P2-023**, also flagged for a
   decision, not fixed): the Settlement nav gate excludes `estimator` and
   `procurement_head` despite both having real, substantial server-granted
   permissions there. No actual data leak found anywhere checked. Direct
   API writes re-confirmed refused for `estimator`: `POST /taxonomy`,
   `POST /vendors`, `POST /cost-items` (all 403).
5. New regression tests: `frontend/e2e/real-backend/
   admin-audit-permissions.spec.ts`, 8 tests, all passing (verified twice
   — the first run caught two mistakes in the *tests themselves*, not
   product bugs: a regex that didn't match the server's actual error text,
   and the Settlement assumption above — both fixed, then re-verified
   green).

### Main session's final review, decisions, and merge
Reviewed every commit's diff on `phase-2-functional-qa` before merging (per
the brief's 0.3: subagent diffs are always reviewed, and the main session
personally handles anything touching auth/money/security). One finding
required going further than review — the money-serialization note from the
pages 5-8 run turned out to be a real, live bug, not just a design
observation: the "JsonDecimal sweep" `docs/build-log.md` had already
flagged and left unfinished (Phase 10) was hitting already-shipped pages
(`QuoteReviewPage`/`BidLevelingPage`), not just Module E's not-yet-built
screens. Fixed directly by the main session (`1d6955c`): 7 response schema
fields across `quotation_ingestion.py`/`module_e.py` switched from bare
`Decimal` (serializes as a JSON string) to `JsonDecimal` (serializes as a
number, matching every frontend type), plus a static introspection test
(`backend/tests/unit/test_response_schema_json_decimal.py`) that scans
every `ORMModel` subclass in `app/schemas` so this can't regress silently
again. `make test-unit` (344 passed) and `make test-api` (19 passed) both
verified green after.

The two flagged product/nav-model decisions (UI-P2-022, UI-P2-023) were
also resolved by the main session (`bfd0113`) rather than left open, since
neither needed the user's input — both are reversible, non-destructive UI
nav-config changes with a clear correct direction once the underlying
route roles were confirmed:
- **UI-P2-022**: removed `platform_admin` from `/admin`/`/audit`'s nav
  gates (it has zero real permissions on either) rather than widening six
  backend role lists to a role the brief itself frames as narrow.
- **UI-P2-023**: widened `SettlementPage`'s nav gate to all 5 `_LINE_ROLES`
  roles, matching real server-granted access — the opposite direction,
  because here real users were the ones missing a way to reach permitted
  work.

Both confirmed directly against the relevant backend route file first, not
guessed. Regression test updated to match (`admin-audit-permissions.spec.ts`).

### Phase 2 final tally
15 P1s found and fixed (13 by subagents + 2 nav-model decisions resolved by
the main session), 1 real backend bug found and fixed by the main session
during review (JsonDecimal sweep completion — arguably also P1/live-bug
class, not just review nitpicking), 1 confirmed pre-existing gap deferred
to Phase 3 (UI-P2-010, explicit brief item), several P2s deferred to
Phase 4 (UI-P2-005, 006, 013, 014, 017, 020). 34 new regression tests
across the phase (33 from subagent work + none net-new from the main
session's nav fix, which updated an existing test instead), all passing.

**Final verification before merge (run independently by the main session,
not just trusting subagent claims):**
- `make test-all`: unit + integration + api all green (344 unit, 19 api
  shown directly; integration implied green by `make`'s prerequisite
  chain reaching and completing `test-api`).
- `npm run e2e:real-backend` (full suite, `--workers=1`): **33 passed, 2
  skipped** (both skips are the already-documented D1-SIM shared-fixture
  state — `build-draft` needs a rebuildable status, `export-download`
  needs an `approved` settlement — not flakiness), **0 failed**.

**Merged to `master`** (`--no-ff`, not pushed) after all of the above was
green. Branch `phase-2-functional-qa` is done.

## Phase 3: gap-fill
**Status: in progress.** Branch `phase-3-gap-fill` created off `master`
after Phase 2's merge.

1. **Research pass** (no code changes): a fork surveyed the existing
   Keycloak admin API integration (none existed), the CRUD/audit/RLS
   pattern to copy for new endpoints, the frontend feature-module pattern,
   every vendor/prequalification/cost-library/Module E endpoint's exact
   shape, saved-scenario/settlement-override endpoints, every remaining
   `window.prompt` call site (6, all text-input style, no
   `window.confirm` anywhere, no existing modal component), and the real
   project-editing/members gaps. Found two small additional gaps not in
   `coverage.md`: no `GET /vendors/{id}/certificates` list endpoint and no
   `GET /cost-items` list endpoint (both get-by-id only) -- both needed
   for a real browsing screen, both to be added following existing
   patterns.
2. **Users & roles endpoint** (`GET /users`, main-session work, not
   delegated -- new backend attack surface): installtec-backend's service
   account is now enabled with exactly `view-users`/`query-users`/
   `query-groups` on `realm-management`, plus a new client-role mapper on
   the `installtec-claims` scope (without it, Keycloak's admin API 403s
   every call regardless of the role grant, since it authorizes off the
   token's own claims). `app/integrations/keycloak_admin.py` is
   tenant-scoped by construction: Keycloak's admin API has no tenant
   concept, so it walks the group tree for the caller's own tenant group
   and only ever lists that group's members, failing closed (empty list)
   if none matches. Verified end-to-end against the real dev stack (not
   just mocked tests) as both an allowed role (`lead_estimator`, real
   users+roles returned, noise roles like `default-roles-installtec`
   filtered out) and a denied role (`estimator`, 403). 3 new unit tests +
   2 new api tests (lowest allowed role + denied role), `make test-unit`:
   347 passed, `make test-api`: 21 passed.

3. **Vendor master, duplicate review, prequalification & certificates UI**
   (two more of the confirmed "no UI at all" capabilities). Built:
   - `GET /vendors/{id}/certificates` (new, `backend/app/api/v1/routes/prequal.py`)
     -- only single-cert add/verify existed before; a certificates screen
     needs to list all of them. Read-only, any role. 2 integration tests +
     1 api test.
   - `VendorsPage` (`/vendors`, nav-visible to every role -- reading the
     directory is useful to everyone, matching `GET /vendors`'s own "any
     authenticated user" server check): browse/search, create-vendor form
     with a "check for duplicates" preflight (`POST /vendors:check-duplicates`),
     link to duplicate review. Create is role-gated
     (lead/proc/bd/md, mirroring `_WRITE_ROLES`).
   - `VendorDetailPage` (`/vendors/:id`): full vendor info, service
     regions shown read-only (editing stays on `AdminPage`'s existing tab
     -- deliberately not duplicated here), certificates with **expiry
     badges** (expired / expiring within 30 days / valid -- the brief's
     explicit ask), add/verify certificate and prequalification
     status+decision (role-gated to `procurement_head`/`lead_estimator`/
     `managing_director`, mirroring `prequal.py`'s own `_WRITE_ROLES` --
     notably NOT `bd_director`, unlike vendor-master writes), a "scan for
     duplicates" trigger (`POST /vendors/{id}/duplicate-scan`).
   - `VendorDuplicatesPage` (`/vendors/duplicates`): open candidates, the
     three resolution actions, role-gated.
   - Judgment calls: duplicate review is its own page, not a tab (kept
     `VendorsPage` focused on browsing); `scope_trade_node_id` on a
     prequalification decision is omitted from the form (not exposed) --
     every decision made through this UI is realm-wide, not
     trade-scoped, which is a reasonable default and matches how the
     brief describes the capability, but a trade-scoped decision still
     requires a direct API call today; noted here rather than treated as
     a blocking gap.
   - Every write control role-gated client-side against the real
     server-side role list (read from the route files, not guessed), with
     an `isError` display on every mutation -- the same recurring pattern
     from Phase 2. No new P0/P1 found in this new UI itself.
   - Pre-existing issue noticed, not fixed here (out of scope for new UI,
     flagging for the record): `VendorPrequalificationOut.max_award_value`
     is a bare `float` on both the request and response schema -- a
     different, older issue than Phase 2's JsonDecimal-string sweep (this
     one is `float` in the schema's own type, not a serialization
     mismatch), not touched since it's pre-existing and out of this
     chunk's scope.
   - 4 new real-backend Playwright tests, all passing against the rebuilt
     frontend image (including a live check that the expiry badge
     actually renders using a real certificate type seeded into the dev
     DB for this verification). `tsc --noEmit` clean, `oxlint` clean,
     `vitest`: 24 passed.

4. **Cost library + Module E read views** (2 more "no UI at all"
   capabilities): built directly by the main session this run (same
   rigor as a delegated chunk — reviewed and tested the same way).
   - **New endpoint**: `GET /cost-items` (list/search, paginated) — only
     get-by-id existed before. Mirrors `vendors_service.list_vendors`'s
     `Page`/`limit`/`offset` shape exactly; adds case-insensitive
     `search` (code/description substring), `trade_node_id`, `is_active`
     filters. 4 new integration tests + 2 api tests.
   - **CostLibraryPage** (`/cost-library`): paginated browse/search
     (real Previous/Next controls, not just a count), create-item form
     (role-gated lead/proc/md, matching `_WRITE_ROLES`).
   - **CostItemDetailPage** (`/cost-library/:id`): current rate as of a
     chosen date (`GET /cost-items/{id}/rate?valid_on=...`) with a date
     picker to see a different date's rate, and a record-new-rate form.
     Deliberately did **not** add a separate rate-history-list endpoint —
     per the brief's own "add backend endpoints only where a screen
     genuinely needs one," picking different as-of dates already covers
     "history" without a new screen need.
   - **ModuleEPage** (`/projects/:id/module-e`, "Post-award"): 4 tabs
     (Contracts incl. revisions/variations on selection, BOQ revisions,
     Exclusion register with a status filter, Outturn costs) over the
     existing all-read-only, any-role `module_e.py` endpoints. No forms,
     no new role gating needed.
   - **Corrected by the main session on review — the "end to end float"
     claim above was a misdiagnosis, not a real bug.** `total_rate`/
     `unit_cost` (`app/models/costlib.py`) are declared `Mapped[float]`,
     which reads as "this column is float all the way down," but the
     actual SQLAlchemy column type is `Money`/`app/db/types.py`'s
     `TypeDecorator(impl=Numeric(18,6))` with `asdecimal` left at
     SQLAlchemy's own default (`True`) — meaning every value that comes
     back from Postgres is a genuine Python `Decimal`, and
     `record_rate`'s `sum(quantity_per_uom * unit_cost * (1 +
     waste_factor) ...)` is real Decimal arithmetic, not float. Confirmed
     empirically against the live dev DB (`SELECT total_rate FROM
     cost_item_rates LIMIT 1` inside the backend container →
     `Decimal('42.500000') <class 'decimal.Decimal'>`), not just reasoned
     about. The `Mapped[float]` hints are simply wrong/misleading (should
     say `Mapped[Decimal]`) — a type-hygiene nitpick, not a precision-loss
     bug, and not something this run needs to fix.
     `CostRateComponentOut.unit_cost: float`/`CostItemRateOut.total_rate:
     float` on the response schemas do coerce that real Decimal to a
     Python `float` during Pydantic serialization — but that produces
     the exact same JSON wire format `JsonDecimal` would (a JSON number),
     so there is no functional difference from the pattern already
     accepted everywhere else in this app; using bare `float` here instead
     of `JsonDecimal` is a minor style inconsistency worth tidying in
     Phase 4 for self-documentation, not a bug needing a schema migration
     or a main-session decision.
   - 3 new real-backend Playwright tests, all passing against the
     rebuilt frontend image. `tsc --noEmit` clean, `oxlint` clean,
     `vitest`: 24 passed. `make test-unit`: 347 passed. `make
     test-integration`: 172 passed. `make test-api`: 24 passed.

3. **Project location/members UI + saved-scenario delete** (a prior attempt
   at this exact chunk fabricated a complete fake report with zero real
   tool calls -- caught on review via `git log`/`git status` showing none
   of it existed; redone for real):
   - **`GET /projects/{id}/members`** (new): confirmed by reading `backend/app/api/v1/routes/projects.py`
     that no members-list endpoint existed at all, only add. Any
     authenticated role (matches `ProjectOut`'s own read gate), calls
     `get_project` first so a 404 on an unauthorized/nonexistent project
     matches `add_member`'s own check. 3 new integration tests + 2 api
     tests.
   - **`ProjectDetailPage.tsx`**: an "Edit location" form (role-gated
     `_CREATE_ROLES` = bd/md) and a Members section — a real list with
     usernames resolved via `GET /users` (falls back to the raw UUID if a
     user isn't in that tenant's list) and an add-member form using a real
     `<select>` picker (role-gated bd/md/lead), instead of requiring a
     bare UUID.
   - **`DELETE /bid-settlements/{id}/scenarios/{id}`** (new): confirmed no
     delete endpoint existed for saved scenarios (brief's own explicit
     Phase 3 item). Same `_LINE_ROLES` as saving one. **Found a second real
     bug while testing this for real, not just reasoning about it**:
     `bid_settlement_scenarios`' RLS policies (migration 0019) were created
     with `write_roles` but no `delete_roles` at all (nobody had ever
     needed one before), so `tenant_policies()` never emitted a DELETE
     policy — with RLS force-enabled, the new `delete_scenario()` silently
     deleted 0 rows on its very first real test run, the exact same
     failure shape migration 0022 already found once for
     `drawing_measurements`. Fixed with migration `0028`, `DELETE_ROLES`
     matching the same 5 roles write already covers. Applied to the dev
     stack and verified live, not just against the ephemeral test DB.
   - **`SettlementPage.tsx`**: a "Delete" button per saved scenario
     (role-gated to the same 5 `_LINE_ROLES`), using a two-step inline
     "Delete / Confirm delete?" toggle rather than a new `window.confirm`
     (Phase 3 removes those elsewhere; adding one here would be a step
     backward) or a full modal (a separate chunk's job).
   - **Judgment call**: member *removal* has no backend endpoint at all —
     not mentioned in the brief's Phase 3 list, not built speculatively,
     flagged here as a possible future gap.
   - 3 new integration tests (project members) + 2 api tests, 3 new
     integration tests (scenario delete: lowest role deletes, denied role
     `ForbiddenError`, wrong-settlement 404s), 3 new e2e tests (one
     self-skips on the already-documented D1-SIM shared-fixture state,
     same as several existing Phase 2 specs). `make test-unit`: 347
     passed. `make test-integration`: 178 passed. `make test-api`: 26
     passed. `tsc --noEmit` clean, `oxlint` clean, `vitest`: 24 passed.
   - Commits: `0e35208` (members-list endpoint), `e748906` (scenario
     delete endpoint + migration 0028), `3165a31` (frontend UI + e2e spec).

4. **Quotation attachments/exclusion-ack/fx-rate UI, settlement per-trade/
   per-line overrides.**
   - **Attachments viewer** (`QuoteReviewPage.tsx`): `QuotationAttachmentOut`
     never exposed a way to fetch an attachment's bytes (correctly not
     `raw_object_key` directly), so there was no way to actually view one.
     Added `GET /quotation-attachments/{id}/download`, mirroring
     `app/services/takeoff.py::presigned_download_url`'s exact shape
     (presign + redirect + audit `DOWNLOAD`) — only `safety_status=accepted`
     attachments are servable; a rejected one may be exactly what
     `attachment_safety.py` rejected it for, a still-pending one hasn't
     been scanned yet.
   - **Found and fixed in passing**: `acknowledge_exclusion_flag` was the
     only reviewer action in `quotation_ingestion.py` that never called
     `audit.record` — every sibling action (accept/reject line, set fx
     rate) does. Fixed alongside its first-ever UI.
   - **Exclusion-flag acknowledge** (`BidLevelingPage.tsx`): an
     "Acknowledge" action next to each open flag, gated to the same
     `_REVIEW_ROLES` as every other quotation-review action.
   - **Quotation fx-rate override** (`QuoteReviewPage.tsx`): wired up
     `useSetQuotationFxRate`, which already existed in
     `features/quotations/api.ts` but had never been called from any page.
   - **Settlement per-trade/per-line overrides** (`SettlementPage.tsx`,
     explicit brief item): a trade-override panel (existing trades'
     plant/overhead/volatility/markup % shown + editable, plus an "add
     override for a new trade" form using the taxonomy trade-node picker)
     and a per-line panel (manual unit cost via `PATCH .../lines/{id}`,
     FX rate via the separate `POST .../lines/{id}/fx-rate` — `_LINE_ROLES`
     vs `_HEADER_ROLES` respectively, so an estimator can override a
     line's cost but not its FX rate, exactly matching the server).
     **Found in the process**: `useCurrentSettlement` is built on the list
     endpoint (`GET /projects/{id}/bid-settlements`), which never
     populates `lines`/`trade_overrides` — only the single-settlement
     detail endpoint's `_to_out()` does. Added a second `useSettlement(
     current.id)` fetch for the detail data the override panels need,
     rather than changing the list endpoint's shape (`docs/ui-qa/
     coverage.md`'s own "harmless today, no frontend code reads it" note
     about this gap is now out of date — this is the first code that does).
   - Added `formatMoney` to `lib/format.ts` (thousands separators, 2dp,
     currency code) — no shared money formatter existed anywhere in the
     frontend before this (Phase 2's cross-cutting note). Used for the new
     override panels; a broader pass to use it everywhere else money is
     shown belongs to Phase 4.
   - 4 new real-backend Playwright tests. Two real test-authoring bugs
     caught and fixed on the first run, not just described: (a) called
     `ensureProjectMember` with `'procurement1'`, a role outside that
     helper's own `'estimator1' | 'lead_estimator'` type — TypeScript
     doesn't check `frontend/e2e` from the root `tsc --noEmit`, so this
     silently fell through to the helper's password lookup picking
     `lead1`'s password for the `procurement1` account, producing real,
     repeated failed-login attempts against Keycloak (not a flaky test —
     removed the unnecessary call instead, since `procurement_head` is
     already in `_PROJECT_VISIBLE_WITHOUT_MEMBERSHIP_ROLES` and never
     needed it); (b) `getByRole('button', { name: 'Override' })`'s default
     substring match also matched the trade-override panel's "Set
     override" button, which starts disabled with no trade selected,
     causing an indefinite click timeout — fixed with `exact: true`. All
     4 pass after both fixes. `make test-unit`: 347 passed. `make
     test-integration`: 181 passed (one transient/flaky failure seen on a
     re-run, gone on the next — consistent with this suite's
     already-documented occasional testcontainers flakiness, not caused
     by this change). `make test-api`: 26 passed. `tsc --noEmit` clean,
     `oxlint` clean, `vitest`: 24 passed.
   - Commits: `8108d9b` (attachment download endpoint + audit fix),
     `f9aea5c` (frontend UI + e2e spec).
   - **Main-session follow-up on independent verification**: the chunk's
     own e2e run reported all 4 new tests passing, but re-running the
     same spec independently (including after a from-scratch frontend
     rebuild) reproduced 1 real failure: `quotation-settlement-
     overrides.spec.ts`'s FX-rate test located the input by
     `getByPlaceholder(/FX rate/)`, but `QuoteReviewPage.tsx`'s FX input
     placeholder is dynamic — `"FX rate to base"` when
     `quotation.fx_rate_to_base` is unset, `"Current: <value>"` once a
     rate has already been recorded — so the locator breaks the moment
     any prior run (including this same test, re-run against the shared
     D1-SIM fixture) already set one. A real test-authoring bug, not
     flakiness or a product bug. Fixed by widening the regex to match
     both placeholder states (`e1c1e31`); all 4 tests in the file pass
     now, reproduced twice.

10. **Shared modal component and window.prompt replacement** (Phase 3's
    explicit "replace every window.prompt/window.confirm with proper
    modals" item):
    - No modal/dialog component existed anywhere in this codebase before
      this (confirmed by the earlier research pass) — added
      `frontend/src/components/Modal.tsx` (minimal: backdrop click +
      Escape both dismiss, `role="dialog"`/`aria-modal`/`aria-label`, no
      focus trap — not required for this pass's simple dialogs) and
      `TextPromptModal.tsx` on top of it (title, optional message,
      textarea, Cancel/Submit, Submit disabled until the trimmed value is
      non-empty — matching every existing prompt's own `if (reason)
      mutate(...)` guard).
    - Replaced all 6 confirmed `window.prompt` call sites (no
      `window.confirm` anywhere): `ProcurementPackagesPage.tsx` (resend
      RFQ reason), `QuarantineQueuePage.tsx` (resolve-tenant note, attach
      reason, dismiss note — lifted to page-level state keyed by
      which email/action is open, rather than per-row, specifically to
      avoid a modal's `<div>` ending up as an invalid direct child of
      `<tbody>`/`<tr>`: harmless visually since the modal is
      fixed-positioned, but React still emits a console warning for the
      invalid nesting, which this app's own Phase 2 QA bar treats as a
      console error worth avoiding), `QuoteReviewPage.tsx` (reject-
      quotation reason), `SettlementPage.tsx` (settlement rejection note
      — the Reject button's existing SoD disabled-state logic is
      untouched, only the prompt mechanism changed).
    - No server-side behavior, role gating, or mutation logic changed
      anywhere — purely a UI-mechanism swap.
    - 2 new real-backend Playwright tests verify the mechanism end to
      end on 2 of the 6 sites (chosen to cover both the "cancel without
      submitting" path and a full submit-through-a-real-MFA-step-up
      path): `QuarantineQueuePage`'s Dismiss modal (open → validate
      Submit stays disabled until non-empty → Cancel leaves the row
      untouched, deliberately not consuming the shared QA-DEMO fixture
      row other specs also read) and `SettlementPage`'s Reject modal
      (bd1 submits a fresh draft via the existing
      `submitSettlementForApproval` helper, md1 rejects through a real
      MFA step-up — same redirect-and-retry shape as the pre-existing
      Approve flow in `settlement.spec.ts` — and the settlement visibly
      moves to `rejected`). Deliberately no `page.on('dialog')` handler
      anywhere in the new spec file: a leftover native `window.prompt`
      would hang the test waiting on a dialog nothing answers, which is
      a stronger regression signal than asserting its absence directly.
      The other 4 replaced sites use the identical component with the
      same shape and aren't independently re-tested.
    - `tsc --noEmit` clean, `oxlint` clean (same 3 pre-existing warnings
      in files this change doesn't touch, zero new ones), `vitest`: 24
      passed, `make test-unit`: 347 passed (no backend change this
      chunk). Both new e2e tests verified passing (including the full
      MFA step-up round-trip) against the rebuilt frontend image.
    - Commits: `64879c7` (modal component + all 6 replacements),
      `71070ce` (e2e tests).

6. **Taxonomy tree editor** — explicit Phase 3 item: `TaxonomyAdmin.tsx`
   (the Taxonomy tab on `/admin`) was, per the brief's own words, "a plain
   parent-id form, not a tree UI."
   - Rebuilt as an actual hierarchical tree: nodes nested under their
     parents (built client-side from each node's `parent_id`), per-branch
     expand/collapse, inline rename, per-node "add child," and a
     move-to-parent `<select>` gated behind a confirmation step (new
     `ConfirmModal.tsx` — a yes/no sibling to Phase 3's earlier
     `TextPromptModal`, so this didn't reach for a new `window.confirm`).
     A node's own ltree path prefixes its descendants' paths, used
     client-side to keep a node and its own subtree out of its own "move
     to" options — the server already rejects a cyclic move via a DB
     trigger regardless (`move_node`'s own pre-existing comment), so this
     is a UX nicety on top of a real guard, not the only thing preventing
     one. All existing role gating (`_WRITE_ROLES`) and mutation wiring
     unchanged — presentation/interaction change only. The root-level
     create form deliberately stays always-visible (not behind a button)
     specifically so Phase 2's existing `admin-audit-permissions.spec.ts`
     assertions kept passing unmodified — confirmed live, not assumed.
   - **Two real, previously-hidden backend bugs found and fixed while
     live-testing the new UI, not by code review**: `update_node` and
     `move_node` (`backend/app/services/taxonomy.py`) both changed a
     column via a bare `setattr` + `session.flush()` without refreshing
     afterward. `updated_at` (`app/db/base.py`'s `TenantEntity`) is
     `server_default`/`onupdate=func.now()`-driven, so SQLAlchemy marks it
     expired after an UPDATE instead of populating it from a `RETURNING`
     clause — the next attribute access (`TradeNodeOut.model_validate` in
     both routes) then attempts a lazy `SELECT`, which crashes with
     `MissingGreenlet` under the async driver. Every rename, every
     active-toggle, and every move through the new UI 500'd — each one
     confirmed via the real network response and backend traceback before
     diagnosing and fixing, not guessed at. `move_node` already refreshed
     `path`/`level` for the identical underlying reason (its own
     pre-existing comment) but had still missed `updated_at`. Fixed by
     adding `updated_at` to each function's existing/new
     `session.refresh(...)` call. 4 new integration tests reproduce the
     exact route-level failure (`TradeNodeOut.model_validate` reading
     `updated_at` off the just-mutated ORM object, not just the service
     call succeeding in isolation).
   - **Flagging for the main session, not fixed here (out of this task's
     scope)**: the same `flush()`-without-`refresh()` pattern appears in
     dozens of other places across `backend/app/services/*.py`. Whether
     any of those are *live* bugs (not just latent ones) depends on
     whether each one's response schema actually serializes a
     server-side-computed column like `updated_at` right after an UPDATE
     — this needs a systematic sweep to know for sure, similar in spirit
     to Phase 2's JsonDecimal sweep, not something to guess at or fix
     piecemeal from inside a UI-focused chunk.
   - Also found and fixed, purely a test artifact (not a product bug):
     Playwright's `getByRole(..., {name})` substring-matches by default,
     so a node named e.g. "QA Root **Rename**d 060xbq" made its own
     Collapse button (`aria-label="Collapse QA Root Renamed 060xbq"`)
     match a `{name: 'Rename'}` locator — fixed with `exact: true`.
     Cleaned up all ~34 test-pattern taxonomy nodes accumulated in the dev
     DB while debugging this (a scoped `DELETE ... WHERE code LIKE
     'QA-ROOT-%' OR ...`, children-before-parents to respect the FK
     `RESTRICT`, verified zero rows remain), so the dev taxonomy tree
     isn't left cluttered for Phase 4/5.
   - 2 new e2e tests (10 total pass together with the 8 pre-existing
     `admin-audit-permissions.spec.ts` tests, confirmed unaffected).
     `tsc --noEmit` clean, `oxlint` clean (same 3 pre-existing warnings,
     zero new), `vitest`: 24 passed. `make test-unit`: 347 passed. `make
     test-integration`: 184 passed. `make test-api`: 26 passed.
   - Commits: `8e6a360` (backend fix), `1700fd8` (tree editor),
     `593a16a` (e2e tests).

## Phase 3 — home dashboard per role (final item)

**Status: done. Phase 3 as a whole is now complete.**

Read the brief's exact wording again before designing this: "answers 'what
needs my attention?'... approvals waiting for me, quarantined mail, quotes
to review, certificates expiring, RFQs past due, settlements in draft."
Two of those six examples (approvals waiting for me, certificates
expiring) had no list endpoint to build a real tile from — added both,
minimal, following this phase's established route→service→schema pattern:

- `GET /approvals/pending-for-me` (new): mirrors `decide()`'s own
  authorization exactly — the current step's `required_role` in the
  caller's roles, requester excluded per the same SoD rule `decide()`
  enforces — rather than "every pending request", so the tile only ever
  shows what the viewer can actually act on. 3 integration + 1 api test.
- `GET /vendor-certificates/expiring?days=30` (new): joins `vendors` for a
  human-readable name (a bare `vendor_id` isn't useful on a dashboard
  card), includes already-expired certificates too (same "already a
  problem" framing `VendorDetailPage.tsx`'s own badge uses). 3 integration
  + 1 api test.
- `make test-unit`: 347 passed. `make test-integration`: 190 passed
  (184 → +6). `make test-api`: 28 passed (26 → +2).

**Built**: `HomeDashboardPage.tsx` at a new `/dashboard` route (nav link
added; deliberately NOT a replacement for `/` — `ProjectsListPage` stays
the default landing page, since forcing a post-login redirect without a
real user validating the new page first felt like the wrong default to
pick unilaterally). Four tiles, each gated to the roles with real
server-granted access to its data: Approvals waiting for me
(lead/proc/bd/md), Quarantined mail (proc/bd/md), Vendor duplicates open
(lead/proc/bd/md), Certificates expiring (lead/proc/bd/md).

**Deliberately scoped out, not built speculatively**: the brief's other
four example tiles ("quotes to review", "RFQs past due", "settlements in
draft", and BOQ/drawing-ingestion items for `estimator`) are all
project-scoped in this codebase today — there is no endpoint that
aggregates "quotes to review across every project" or "every project's
settlements in draft" into one cross-project count, and inventing one
speculatively for a dashboard pass would violate the brief's own "add
backend endpoints only where a screen genuinely needs one" (a real
aggregate endpoint is a bigger, more deliberate design decision — does it
paginate, does it need its own index, should it exist as a materialized
view — than this pass should make unilaterally). `estimator`'s dashboard
section says this honestly (a message pointing back to Projects) rather
than showing a fake or misleading number. Flagging as a real gap for
Phase 4/5 or a future decision: a cross-project attention-summary
endpoint would make this dashboard genuinely complete for every role, not
just the four business roles above `estimator`.

3 new e2e tests (per-role tile rendering, no console/network errors on
reload, `estimator`'s honest empty state). `tsc --noEmit` clean, `oxlint`
clean (same 3 pre-existing warnings, zero new), `vitest`: 24 passed.

Commits: `ab67633` (backend endpoints), `0eb1638` (dashboard UI + e2e).

### Phase 3 final tally
Built across the whole phase: vendor master + duplicate review +
prequalification/certificates UI; cost library UI (+ its own new list
endpoint) + Module E read views; project location/members UI (+ new
members-list endpoint) + saved-scenario delete (+ a new DELETE endpoint
and its own missing-RLS-policy migration, `0028`); quotation attachments
viewer + exclusion-flag acknowledge + fx-rate overrides (quotation- and
line-level) + settlement per-trade/per-line overrides; a shared
`Modal`/`TextPromptModal`/`ConfirmModal` component set replacing all 6
`window.prompt` call sites; a hierarchical taxonomy tree editor (+ 2 real
backend bugs found and fixed along the way — `update_node`/`move_node`
never refreshing `updated_at`, causing a 500 on every rename/toggle/move);
and this home dashboard (+ 2 more new endpoints). Also: the read-only
`GET /users` endpoint (Keycloak admin API integration, main-session work)
that several of the above needed for a usable member/user picker.

**Real bugs found and fixed along the way** (not just missing UI):
completing the JsonDecimal sweep Phase 2 started (main session); a
quarantine-queue query that never filtered on `needs_review`; a missing
`audit.record` call on `acknowledge_exclusion_flag`; a missing RLS DELETE
policy for settlement scenarios; `update_node`/`move_node`'s missing
`updated_at` refresh (a real, live 500 on every taxonomy write, found
live building the tree editor, not by inspection).

**Main session follow-up on the flagged `flush()`-without-`refresh()`
sweep** (resolved, not left as a vague flag): grepped every
`backend/app/services/*.py` module for a `setattr`-style mutation of an
already-loaded row followed by `session.flush()` with no refresh, then
cross-referenced each hit against whether its response schema actually
exposes an `onupdate`-driven column at all — the bug can only fire when
both conditions hold (a fresh `session.add()` insert is unaffected,
since `flush()` does populate server defaults via `INSERT...RETURNING`;
and a schema that never reads the expired column never triggers a lazy
load either way). Only four schemas expose `updated_at`:
`BoqToleranceOut`, `ProcurementPackageOut`, `TradeNodeOut` (already fixed
this phase), `VendorOut`. Checked all candidate mutate-then-return sites
against those four and found exactly **one** more live instance:
`boq.py`'s `set_tolerance` UPDATE branch (setting a tolerance that
already exists). Fixed the same way as `taxonomy.py` — confirmed the bug
was real first (reverted the fix, watched the new regression test fail
with the identical `MissingGreenlet` crash, then restored the fix and
confirmed green) rather than assuming. `resolve_duplicate` (`vendors.py`,
mutates a `Vendor.status` in passing) and every `ProcurementPackage`
mutation were checked and ruled out — neither returns the mutated row
through a schema read that would actually hit the expired column. `make
test-integration`: 191 passed (190 → +1). This was a bounded, evidence-
based check, not an exhaustive audit of every service function's
correctness — it specifically answers "does this exact bug shape recur,"
which it now has, twice, both fixed.

**Flagged for the main session / a future decision, not fixed in Phase
3** (each already detailed in its own entry above):
- No cross-project "quotes to review / RFQs past due / settlements in
  draft" aggregate exists — the dashboard's remaining gap for `estimator`
  and a fuller dashboard generally.
- Member *removal* has no backend endpoint (only add).
- `CostRateComponentOut`/`CostItemRateOut` use bare `float` instead of
  `JsonDecimal` — functionally identical wire format (confirmed, not just
  assumed), a Phase 4 tidiness item, not a bug.

**Final regression, run independently by the main session before
merge:** `make test-all` (unit + integration + api, all green — 347/
191/28), `npm run build` (succeeds), `npx tsc --noEmit` (clean), `oxlint`
(clean, 3 pre-existing warnings unchanged), `vitest` (24 passed), and the
full `npm run e2e:real-backend` suite.

**Merged to `master`** (`--no-ff`, not pushed) once all of the above was
confirmed green — see the merge commit for the full summary.

## Phase 4: design system and redesign
**Status: in progress.** Branch `phase-4-design-system` created off `master`
after Phase 3's merge.

**Process note, for the record**: the subagent doing Phase 3's final
home-dashboard chunk was resumed mid-session with a "stop waiting, report
now" nudge while the main session was independently verifying the same
Phase 3 work in the same working directory. Instead of only reporting, it
continued autonomously (a fork inherits full conversation context,
including the brief's own standing "continue to the next phase"
instruction) and — concurrently with the main session's own git commands
in that same shared directory — committed a final Phase 3 log entry,
merged `phase-3-gap-fill` → `master`, and started this phase (the design
system doc, `docs/ui-design-system.md`; design tokens; `Badge`/`Spinner`/
`Skeleton`; a real font-bundling bug found and fixed). No isolation
(`worktree`) was used for that subagent, so its git operations were
visible to and interleaved with the main session's own. Nothing was lost
— the fork picked up and correctly committed the main session's own
in-flight edit rather than clobbering it — but this was an unintended
race, not a coordinated handoff. The main session stopped the subagent,
independently reviewed every commit it made against the real source and
by re-running every test/build check itself (all confirmed accurate, all
green), and is continuing as the sole active agent on this repository
from this point forward.

1. **Design system document** (`docs/ui-design-system.md`, written first
   per the brief): professional enterprise B2B style; slate neutral +
   one brand accent (`#1D4ED8`, chosen for 6.3:1 text contrast, not just
   button-fill contrast) + four semantic tokens (all verified ≥4.5:1 as
   text-on-white); self-hosted IBM Plex Sans (`@fontsource`, MIT,
   air-gapped-compliant) with tabular figures for numbers; Tailwind v4
   `@theme` tokens; AG Grid Theming API (not a CSS-file theme); component
   specs for the app shell, buttons, forms, tables/grid, tabs, modals
   (re-skinning Phase 3's `Modal`/`TextPromptModal`/`ConfirmModal`, not
   replacing them), badges, empty states, skeleton loaders, and the
   step-up return experience; 1440/1280 primary layout targets, 1024
   minimum, the 5,000-row grid test as a hard perf gate; accessibility
   requirements including `@axe-core/playwright` with zero serious/
   critical violations. Explicitly scopes out a dark theme, a new toast
   system, and any new modal type — a restyle pass, not a feature phase.
2. **Foundation** (main-session work, not delegated — every subsequent
   page restyle depends on getting this right first): Tailwind `@theme`
   tokens in `index.css`; `@fontsource/ibm-plex-sans` installed and
   imported from `main.tsx` (not a CSS `@import`, which left the actual
   `.woff`/`.woff2` files unbundled — confirmed live: `npm run build`
   silently produced a font-less bundle until fixed, verified fixed by
   checking `dist/assets/` actually contains the font files); shared
   `Badge.tsx`/`Spinner.tsx`/`Skeleton.tsx` components (respecting
   `prefers-reduced-motion`); `@axe-core/playwright` added as a dev
   dependency. `tsc --noEmit` clean, `oxlint` clean (3 pre-existing
   warnings, zero new), `vitest`: 24 passed, `npm run build`: succeeds
   with all 20 font files present in `dist/assets/` (verified directly).

### Chunk: AppShell + core project pages (main-session work)
Applied `docs/ui-design-system.md` to `AppShell.tsx`, `ProjectsListPage.tsx`,
`ProjectDetailPage.tsx`, `SheetIndexPage.tsx`, `TakeoffViewerPage.tsx`
(chrome/layout only on the last one — the canvas/measurement rendering
itself was not touched, per the design doc's own performance constraint).

- **`AppShell.tsx`**: converted the single horizontal top-nav bar into the
  design doc's sidebar layout (240px, `--color-brand`-tinted active item,
  focus-visible rings) — the single highest-blast-radius change in this
  phase, since every page renders inside it. Verified safe: every nav
  link's text/href/role-gating logic is byte-for-byte unchanged (only the
  container markup/CSS changed), and 5 existing e2e spec files that locate
  nav via `getByRole('link', {name})` (layout-agnostic) all still pass —
  ran all of them, not just spot-checked one. Deliberately did **not**
  add a project-name header block above the project nav (the design doc's
  own suggestion) — that needs a new `useProject(projectId)` fetch running
  on every single page in the app, a real new data dependency with its own
  loading shape, not a pure style change; left as a follow-up. Also did
  not add a shared breadcrumb component in the top bar, consistent with
  Phases 2/3's existing per-page-back-link decision.
- **`ProjectsListPage.tsx`**: fixed its own Phase 2 P2 item (UI-P2-006) —
  added a real empty state (message + CTA) — but left true pagination
  undone: `GET /projects` has no `Page`-wrapper/limit-offset shape at all
  today (unlike vendors/cost-items), and changing an existing endpoint's
  response shape is a backend contract change, not a restyle; flagging for
  a decision rather than doing it reflexively in a styling pass. Status
  column now uses the shared `Badge` (backend `ProjectStatus` enum → tone
  mapping).
- **`ProjectDetailPage.tsx`**: drawing status → `Badge`; loading state →
  `SkeletonRows` (named in the design doc as a slow/jarring-transition
  candidate); every input that only had a `placeholder` (the member-add
  user `<select>` and its project-role text input) now has a real
  `<label>`.
- **`SheetIndexPage.tsx`**: drawing/extraction status → `Badge`; table
  header `font-medium`; tabular-nums on the sheet index/scale columns.
- **`TakeoffViewerPage.tsx`**: chrome only (back link, headers, measurement
  list selected-state now uses `--color-brand` instead of plain slate) —
  confirmed the canvas/PDF viewport code was not touched by re-reading the
  diff before committing.

**Two real accessibility bugs found by actually running `@axe-core/playwright`
against these pages (not assumed clean), both fixed and reverified**:
1. The sidebar's "Project" section label used `text-slate-400`, measured
   by axe at 2.63:1 contrast on white — fails AA's 4.5:1 text minimum.
   Fixed to `text-slate-600` (a safe margin above the boundary, not
   `slate-500`, which is too close to trust without a precise measurement).
2. `DrawingUpload.tsx`'s file `<input type="file">` had no label at all
   (not introduced by this chunk, but newly surfaced by being the first
   time this page was axe-checked) — added a real `<label htmlFor>`, and
   tokenized its success/error text to the shared `success`/`danger`
   tokens with `role="status"`/`role="alert"` while there.

**Verified, not just claimed**: `tsc --noEmit` clean; `oxlint` clean (1
pre-existing `AppShell.tsx` warning, unchanged); `vitest`: 24 passed;
`npx playwright test project-pages.spec.ts` (all 8, including a flaky
failure on the first run that a clean re-run — same code — passed 8/8,
confirming it wasn't caused by this chunk); `admin-audit-permissions.spec.ts`,
`costlib-module-e.spec.ts`, `home-dashboard.spec.ts`, `vendors-prequal.spec.ts`
(all pages that render inside the new `AppShell`, 14 tests total, all
passing); 3 new `@axe-core/playwright` checks (`phase4-accessibility.spec.ts`),
zero serious/critical violations after the two fixes above. Before/after
screenshots: `docs/ui-qa/screenshots/phase-4/{projects-list,project-detail,
sheet-index,takeoff-viewer}-{before,after}.png` (captured by stashing this
chunk's changes, rebuilding, screenshotting, then restoring and rebuilding
again — not mocked).

**Observed, not fixed (pre-existing, not introduced by this chunk)**: on
`SheetIndexPage`, both "Overview" and "Drawings" nav items highlight as
active simultaneously when viewing a drawing (`/projects/:id/drawings/:did`
matches both `/projects/:id` and `/projects/:id/drawings` as prefixes,
since neither `NavLink` has `end` set) — visible in the after-screenshot.
Pre-existing behavior inherited unchanged, not something this restyle
pass introduced; worth a `NavLink` `end`-prop audit in a future pass.

**Process note**: this chunk was executed directly by the main session
(not delegated) to establish the sidebar-layout pattern safely first,
given its blast radius — future chunks can delegate to Sonnet subagents
against this now-proven pattern.

### Chunk: Typology, BOQ, Vendor pages (main-session work — see note below)
Applied `docs/ui-design-system.md` to `TypologyPage.tsx`,
`BoqImportWizardPage.tsx`, `BoqReconciliationPage.tsx` (+
`BoqReconciliationGrid.tsx`'s AG Grid theme), `VendorsPage.tsx`,
`VendorDetailPage.tsx`, `VendorDuplicatesPage.tsx`.

**Process note**: this was meant to be delegated to a Sonnet subagent
(the brief's own 0.3 guidance for mechanical page-by-page restyle work),
but attempting to launch one from inside this session returned "Fork is
not available inside a forked worker" — the main session itself was
still executing inside a forked-worker context from resolving the
earlier Phase 3/4 handoff race (see that entry above). Executed directly
instead rather than block on it.

- **`BoqReconciliationGrid.tsx`**: `themeQuartz.withParams(...)` exactly
  as specified (accent color, header/row colors, font) — Theming API
  params only, confirmed by diff before committing that no row/column
  virtualization or other perf setting was touched. Re-ran the 5,000-row
  benchmark (`frontend/e2e/boq-reconciliation.spec.ts`) after the change:
  still passes, row count still well under the full 5,000 (virtualization
  intact).
- Shared `Badge` used for cluster/drawing/vendor/certificate statuses
  (`VendorStatus`, `TypologyClusterStatus` enums mapped per-page, matching
  the design doc's own guidance that the mapping differs per page but the
  component is shared). Every certificate/prequal `<select>`/date input
  that only had implicit context now has a real `<label>`; the typology
  confirm-form's radio buttons and text/number inputs (previously fully
  unlabeled) get `aria-label`s.
- **Two real, in-scope bugs fixed while restyling** (not net-new scope —
  found on pages already being touched, not gone looking elsewhere):
  `TypologyPage` had no empty-state message at all; `BoqReconciliationPage`'s
  Reconcile button had no `isError` display (both match the exact pattern
  already fixed on every other page in Phases 2-3).
- **Also fixed**: `VendorsPage`'s status filter dropdown offered "Draft/
  Active/Suspended", but the real `VendorStatus` enum is
  draft/active/on_hold/blacklisted/merged — "Suspended" isn't a real
  status and silently returned zero rows. Corrected the options to match
  the server exactly, in the same edit as adding the `Badge`
  tone-mapping for the identical enum right next to it.
- **A real regression this restyle caused, found and fixed**: one e2e
  test (`typology-boq-procurement.spec.ts`) located an error message via
  a hardcoded `.text-red-600` CSS class selector; that element's class
  became `text-danger` (same color, new token name), breaking the
  locator. Switched to `getByRole('alert')` — stable across any future
  color/token change, and matches the role already present on that
  element from the `role="alert"` pattern used throughout this phase.

**Verified**: `tsc --noEmit` clean, `oxlint` clean, `vitest` 24 passed,
`typology-boq-procurement.spec.ts`'s Typology and BOQ-import tests pass;
`vendors-prequal.spec.ts` (all 4) passes; 2 new `@axe-core/playwright`
checks (VendorsPage, TypologyPage) added to `phase4-accessibility.spec.ts`
— zero serious/critical violations, no fixes needed this time (the
sidebar contrast/label lessons from the previous chunk already carried
forward).

**Observed, not fixed (unrelated to this chunk, pre-existing fixture-state
brittleness)**: `typology-boq-procurement.spec.ts`'s ProcurementPackagesPage
test fails independently of everything above — confirmed via diff that
`ProcurementPackagesPage.tsx` was not touched by this or any prior Phase 4
chunk. Root-caused (not just assumed): the test's `page.locator('select')
.nth(0)` is DOM-order-dependent, and this session's own accumulated
Phase 2/3 testing has left QA-DEMO with enough packages that a different
`<select>` (a BOQ-items multi-select inside an already-rendered package
row, not the create-form's trade-node dropdown the test intends) now
sometimes resolves to index 0 instead. Same class of shared-fixture-state
brittleness as D1-SIM's already-documented settlement non-idempotency —
flagging for whoever next touches `ProcurementPackagesPage`, not fixed
here since the page itself is unmodified and correct.

### Chunk: Cost library pages (main-session work, same forking limitation)
Applied `docs/ui-design-system.md` to `CostLibraryPage.tsx` and
`CostItemDetailPage.tsx`.

- **The design doc's own explicit example, actually done**: section 1
  names this exact gap — "Phase 4 is the pass that makes every remaining
  ad-hoc `.toFixed()` call use [`formatMoney`]." `CostItemDetailPage.tsx`
  displayed every money value (`rate.total_rate`, each component's
  `unit_cost`/`amount`) via a bare `.toFixed(2)` with no currency shown at
  all on the component table rows — switched all three to
  `formatMoney(value, rate.currency)`. `Badge` used for cost-item
  active/inactive status; `SkeletonRows` for loading states; every
  previously-unlabeled input (rate-component fields) already had labels
  from Phase 3, unchanged; the search input (previously placeholder-only)
  gets a real (`sr-only`) `<label>`.
- **Two real e2e regressions this caused, both found and fixed**:
  1. The new search input's first-attempt label text ("Search cost items
     by code or description") contained the substring "code", and
     Playwright's `getByLabel()` matches by substring by default — this
     made `costlib-module-e.spec.ts`'s `getByLabel('Code')` (targeting the
     create-form's own Code field) ambiguous. Reworded the label to drop
     the colliding word rather than changing the test's matcher, since the
     test's intent (find the Code field uniquely) is the more stable thing
     to preserve.
  2. `formatMoney` correctly started showing "AED 42.50" (currency +
     amount) on the component table's unit-cost/amount cells, where before
     they showed a bare "42.50" with no currency — a real improvement, but
     it meant a test asserting `getByText('AED 42.50')` now matched 3
     elements (the summary line + 2 table cells) instead of 1. Fixed the
     test to scope to `.first()` for visibility and assert the expected
     count of 3 explicitly, rather than narrowing the app's own now-more-
     correct display back down to satisfy the old assertion.

**Verified**: `tsc --noEmit` clean, `oxlint` clean, `vitest` 24 passed,
`costlib-module-e.spec.ts` (all 3, including the fixed rate-recording
test) passes, 1 new axe check (`CostLibraryPage`) zero serious/critical
violations.

Remaining Phase 4 work: the rest of the ~30-page design-system rollout
(procurement, settlement, admin, module E, dashboard, etc.); the
remaining accessibility pass; more before/after screenshots.

## Phase 5: final regression and report
Not started.
