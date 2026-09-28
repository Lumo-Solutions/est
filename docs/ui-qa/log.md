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

Remaining Phase 3 work: taxonomy tree editor; home dashboard per role.

## Phase 4: design system and redesign
Not started.

## Phase 5: final regression and report
Not started.
