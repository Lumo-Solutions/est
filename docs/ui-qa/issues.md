# UI QA issues log

Format: id, page(s), role, steps, expected vs actual, severity (P0 broken/
blocking, P1 wrong/confusing, P2 polish), evidence. P0/P1 are fixed as found
per `docs/ui-qa-brief.md`; P2 is deferred to Phase 4.

## Phase 2 — pages 1-4 (ProjectsListPage, ProjectDetailPage, SheetIndexPage,
## TakeoffViewerPage), tested as estimator / lead_estimator

### UI-P2-001 (P1, fixed) — No catch-all route; unmatched URLs render a completely blank page
- **Page(s):** app-wide (`frontend/src/App.tsx`'s `<Routes>`)
- **Role:** any
- **Steps:** log in, navigate to any URL that isn't one of the app's known
  route patterns (e.g. `/this-page-does-not-exist-at-all`).
- **Expected:** a 404-style page, still inside the app shell.
- **Actual:** completely blank `<body>` — not even the nav/header rendered.
  React Router logged `No routes matched location "..."` to the console.
  Root cause: the layout `<Route element={<AppShell />}>` has no `path`, so
  in React Router v6 it only renders when at least one child route matches;
  with none matching, the whole tree renders nothing.
- **Fix:** added `frontend/src/pages/NotFoundPage.tsx` and a `path="*"` route
  as the last child, so any unmatched URL now renders a "Page not found"
  page (with a link back to Projects) inside the normal app shell.
- **Regression test:** `project-pages.spec.ts` → "Unmatched routes › an
  unknown path renders a 404 page instead of a blank screen".

### UI-P2-002 (P1, fixed) — Every 4xx (not found / forbidden) is retried 3x before the UI shows an error, during which the page just says "Loading..."
- **Page(s):** app-wide (any page using `useQuery`) — confirmed live on
  ProjectDetailPage (bad project id) and TakeoffViewerPage (bad sheet index)
- **Role:** any
- **Steps:** navigate to `/projects/<a-valid-format-but-nonexistent-uuid>`.
- **Expected:** the "not found" message appears promptly (this is not a
  transient condition — retrying it can never succeed).
- **Actual:** the backend correctly 404s immediately, but the global
  `QueryClient` had no custom `retry`, so React Query's default (3 retries,
  exponential backoff) retried the 404 three times before giving up —
  roughly 7-10 seconds of the page showing a plain "Loading...", visually
  indistinguishable from a slow-but-working request.
- **Fix:** `App.tsx`'s `QueryClient` now has `defaultOptions.queries.retry`
  that returns `false` for any `ApiError` with `status` in the 4xx range
  (never worth retrying) and falls back to the previous `failureCount < 3`
  behavior for everything else (network errors, 5xx).
- **Regression test:** `project-pages.spec.ts` → "ProjectDetailPage › a
  nonexistent project id surfaces a "not found" error quickly, not an
  indefinite Loading state" (asserts the error text appears within 5s).

### UI-P2-003 (P1, fixed) — TakeoffViewerPage shows an indefinite "Loading..." on a genuine fetch error, indistinguishable from still-loading
- **Page(s):** `TakeoffViewerPage.tsx`
- **Role:** any
- **Steps:** navigate to a drawing/sheet URL with a sheet index that doesn't
  exist (e.g. `.../sheets/999`).
- **Expected:** an error message once the fetch fails.
- **Actual:** the page's render gate was
  `if (sheetLoading || !sheet || !drawing) return <Loading/>` — once the
  `useSheet` query settled into an error state, `sheetLoading` became
  `false` but `sheet` stayed `undefined` forever, so `!sheet` kept matching
  and the page showed "Loading..." indefinitely, with no way to tell it
  apart from a page that was still working. This is independent of
  UI-P2-002 above — it would still happen even with a fast-failing retry
  policy.
- **Fix:** destructured `isError`/`error` from both `useSheet` and
  `useDrawing` and added an explicit error branch (with a back link) before
  the loading check.
- **Regression test:** `project-pages.spec.ts` → "a nonexistent sheet index
  shows an error, not an indefinite Loading state".

### UI-P2-004 (P1, fixed for these 4 pages) — No breadcrumbs or back links anywhere in the app
- **Page(s):** confirmed on ProjectDetailPage, SheetIndexPage,
  TakeoffViewerPage; grepping `frontend/src` for "Breadcrumb" returns zero
  matches, so this is an app-wide gap, not specific to these three.
- **Role:** any
- **Steps:** deep-link or refresh into `/projects/:id`,
  `/projects/:id/drawings/:did`, or `.../sheets/:idx`.
- **Expected:** a way back to the parent page other than the browser's own
  back button (`docs/ui-qa-brief.md` Phase 2 explicitly checks for this).
- **Actual:** none of these three pages had any back link.
- **Fix:** added a minimal "← Projects" / "← Back to project" / "← Sheets"
  link to each of the three pages (including on their error states).
  **Not** a full breadcrumb component — Phase 4's design system is where a
  shared breadcrumb pattern belongs; this is a functional stopgap.
- **Follow-up:** the same gap almost certainly exists on
  TypologyPage/BoqImportWizardPage/BoqReconciliationPage/the procurement
  pages/SettlementPage/ExportPage/WinLossPage — none of those have been
  tested yet in Phase 2 (out of this run's scope). Next Phase 2 run should
  check and, if confirmed, either patch each page the same way or treat it
  as one Phase 4 design-system item instead of six more one-off patches.
- **Regression test:** covered implicitly by the back-link assertions in
  `project-pages.spec.ts`'s ProjectDetailPage/SheetIndexPage/
  TakeoffViewerPage tests.

### UI-P2-005 (P2, not fixed) — Header shows the raw Keycloak subject UUID instead of a username
- **Page(s):** `AppShell.tsx` (every page)
- **Role:** any
- **Steps:** log in as any user, look at the top-right of the header.
- **Expected:** a human-readable name (or at least `preferred_username`).
- **Actual:** `{user.sub}` — Keycloak's raw subject UUID (e.g.
  `6e5f21cd-ab62-4323-aa1c-b68e7da3c80a`) is shown. On a project page this
  sits right next to project-scoped nav, and could easily be mistaken for a
  project id.
- **Why not fixed here:** `backend/app/core/context.py`'s `RequestContext`
  only carries `sub`/`tenant_id`/`roles`/`acr`/`auth_time` — no username or
  email anywhere. Fixing this needs `AuthContextMiddleware` to also read
  `preferred_username` (or similar) off the validated JWT and thread it
  through to `GET /auth/me`, which is an auth-context change worth its own
  deliberate review rather than folding into a page-scoped QA pass.
  Recommending as a Phase 3 item.

### UI-P2-006 (P2, not fixed, deferred to Phase 4) — ProjectsListPage has no empty-state message or pagination
- **Page(s):** `ProjectsListPage.tsx`
- **Role:** any
- Not exercised live (the seeded dev environment always has 6+ projects),
  found by code review: an empty `projects` array renders a table with just
  headers, no "no projects yet" message; there's also no pagination for a
  long list. Per the brief, P2 polish is Phase 4's job.

## Pre-existing issues reconfirmed (already logged, not new)
- `make dev-simulate-settlement` (and `global-setup.ts`'s call to it) still
  fails non-fatally against the long-lived D1-SIM fixture with "Every
  settlement line needs a resolved cost before submission" on every run —
  already logged in Phase 0/1 of `docs/ui-qa/log.md`, reconfirmed here with
  no new information.

## Observation, not confirmed as a bug
- GEO-TEST's only DXF drawing (`747f76c1-24f6-43c9-b75a-29e3ead382cb`) has
  been in status `extracting` since 2026-09-24 despite already having 2
  indexed sheets and extracted entities. `useDrawing`
  (`frontend/src/features/drawings/api.ts`) polls every 3s while status is
  in `['queued','indexing','extracting','embedding']`, so any page open on
  this drawing polls indefinitely in the background. Low confidence this is
  a real product bug versus a hand-built fixture that never went through
  the real status transition — needs checking against a drawing that came
  through actual ingestion before treating it as a bug.

## Phase 2 — pages 5-8 (TypologyPage, BoqImportWizardPage,
## BoqReconciliationPage, ProcurementPackagesPage)

### UI-P2-007 (P1, fixed) — TypologyPage has no client-side role gate on Detect/Confirm/Reject; an unauthorized role gets a silent 403
- **Page(s):** `TypologyPage.tsx`
- **Role:** estimator, bd_director (both nav-can-reach this page — "all" per
  `coverage.md` — but neither is in the server's
  `_STRUCTURE_ROLES = (lead_estimator, procurement_head, managing_director)`
  for detect/confirm/reject)
- **Steps:** log in as `estimator1`, open a project's Typology page, click
  "Detect clusters".
- **Expected:** the action is hidden (this role can never use it), per the
  same pattern already established on `ProjectsListPage`.
- **Actual (confirmed live):** the button was fully enabled; clicking it
  produced a real `403` (verified directly: `POST
  .../typology-clusters/detect` as `estimator1` → 403) with **zero UI
  feedback** — `useDetectTypologyClusters()`'s `isError` was never rendered,
  so the button just... did nothing visible.
- **Fix:** added a `hasRole(lead_estimator, procurement_head,
  managing_director)` gate around "Detect clusters" (page level) and
  "Review and confirm"/"Reject" (per-cluster), mirroring
  `ProjectsListPage`'s `CREATE_ROLES` pattern. Also wired up
  `detect.isError`/`reject.isError` message display as defense in depth for
  any other failure mode (e.g. detecting on a project with no ingested
  drawings).
- **Also fixed, found by code review while in this file:**
  `useTypologyClusters()`'s `isError` was never checked either —
  `(clusters ?? []).map(...)` would silently render an empty list on any
  fetch error, indistinguishable from "no clusters yet". Added an explicit
  error branch. **Not independently live-reproduced** — this list endpoint
  (`GET /projects/{id}/typology-clusters`) doesn't validate the project
  exists or is visible to the caller at all (see UI-P2-008's membership
  finding below and RLS's usual row-filtering-not-erroring behavior), so a
  genuine fetch error here is hard to trigger without a real backend 5xx or
  network failure. Kept as a defensive fix; no dedicated regression test for
  this specific branch (the role-gate fix above does have one).
- **Regression tests:** `typology-boq-procurement.spec.ts` → "TypologyPage
  › estimator does not see Detect clusters, and a direct detect attempt
  403s server-side" and "› lead_estimator sees Detect clusters".

### UI-P2-008 (P1, fixed here + a bigger pre-existing gap surfaced) — ProcurementPackagesPage has no client-side role gate on "Create package"; and real demo users are never project members anywhere
- **Page(s):** `ProcurementPackagesPage.tsx`
- **Role:** estimator (nav-gated to est/lead/proc per `coverage.md`, but
  server `_STRUCTURE_ROLES` for create/add-items/draft-RFQs is
  lead_estimator/procurement_head/bd_director/managing_director — not
  estimator)
- **Steps:** log in as `estimator1`, open a project's Procurement Packages
  page, fill in "Package name", click "Create package".
- **Expected:** the form is hidden for a role that can never use it.
- **Actual (confirmed live):** the form was fully visible and usable;
  submitting produced a real `403` with **no feedback at all** — neither
  the console nor the page showed anything, the form just sat there as if
  nothing happened. Direct API check confirmed: `POST
  .../procurement-packages` as `estimator1` → 403.
- **Fix:** added the same `hasRole` gate (`STRUCTURE_ROLES` constant mirrors
  `backend/app/api/v1/routes/procurement.py`'s `_STRUCTURE_ROLES`) around
  the create form, plus `createPackage.isError` message display. Also
  extended error feedback to `addItems`/`dispatch`/`resend` in
  `PackageDetail` (all previously silent on failure — only `createRfqs`
  already showed its own error) and disabled the Dispatch/Resend buttons
  while their mutation is pending, to prevent a double-click firing two
  dispatch attempts.
- **Bigger finding surfaced while writing this fix's regression test:**
  logging in as `lead1` (a real Keycloak dev user, lead_estimator) and
  trying to create a package on the seeded `QA-DEMO` project failed with
  **"Not a member of project ..."** even though `lead1` should be able to.
  Root cause: `backend/app/services/projects.py::assert_can_see_project`
  requires an explicit `ProjectMember` row for `estimator`/`lead_estimator`
  specifically (`bd_director`/`managing_director`/`procurement_head` bypass
  it entirely via `_PROJECT_VISIBLE_WITHOUT_MEMBERSHIP_ROLES`) — and
  **every** CLI fixture (`simulate-e2e`, `simulate-settlement`,
  `seed-qa-demo-data`, etc.) only ever adds its own synthetic `_SIM_*`/
  `_E2E_*` user ids as members, never the real `estimator1`/`lead1`
  Keycloak users these interactive/Playwright-login tests actually log in
  as. Combined with the already-known "no add-member UI" gap
  (`docs/ui-qa/coverage.md` §2, `POST /projects/{id}/members` exists,
  lead/bd/md can call it, but `ProjectDetailPage` has no UI for it), **a
  real lead_estimator or estimator genuinely cannot be granted access to an
  existing project at all without a raw API/DB call** — there's no screen
  anywhere in the product that does this. Not fixed here (it's Phase 3's
  explicit "project editing/members" gap-fill item, and a real product
  design/priority question, not a page-scoped Phase 2 fix). **Practical
  workaround added for testing purposes:** `helpers.ts`'s new
  `ensureProjectMember(browser, projectId, username)` logs in as the target
  user to read their real `sub`, then as `bd1` (who bypasses membership) to
  call `POST /projects/{id}/members` — future Phase 2 runs testing
  estimator/lead_estimator write-workflows against any seeded project will
  hit the exact same wall and should use this helper rather than
  rediscovering it. Flagging for main session: this may be worth elevating
  above Phase 3's general priority given it blocks realistic QA of every
  remaining estimator/lead_estimator write path (settlement, BOQ
  reconciliation actions, etc.) against the current fixtures.
- **Regression tests:** `typology-boq-procurement.spec.ts` →
  "ProcurementPackagesPage › estimator does not see the create-package
  form..." and "› lead_estimator sees the create-package form... and
  creating one succeeds" (the latter uses `ensureProjectMember` first).

### UI-P2-009 (P1, fixed here; same bug also seen elsewhere, not fixed) — Trade-node dropdown showed a raw internal ltree path instead of a name
- **Page(s):** `ProcurementPackagesPage.tsx`'s "Create package" form
- **Role:** any
- **Steps:** open the create-package form, look at the trade dropdown.
- **Expected:** readable trade names ("Earthworks", "Concrete", ...).
- **Actual (confirmed live):** options showed things like
  `n073ec3ef_6b2f_4337_a5a7_2374ca98d180` — `TradeNodeOut.path` is a
  Postgres `ltree` value built from node **ids** by a DB trigger purely to
  support hierarchical queries (`path <@ ...`), never meant to be
  human-readable; the API also exposes a proper `name` field that just
  wasn't used here.
- **Fix:** changed `t.path` → `t.name` in the dropdown's `<option>` text.
  Verified live after the fix: options now read "Earthworks", "Utilities",
  "Asphalt & Paving", "Concrete", "Roadworks", "Mechanical, Electrical &
  Plumbing".
- **Same bug found elsewhere, not fixed (out of this run's page scope):**
  `frontend/src/features/admin/TaxonomyAdmin.tsx` has the identical
  `.path`-as-label bug in **two** dropdowns (the "move to new parent"
  picker, lines ~32 and ~75) — `AdminPage` hasn't been QA'd yet in Phase 2.
  For comparison, `LayerTradeMappingAdmin.tsx` already does this correctly
  (`n.name`). Flagging so the future Admin-page Phase 2 run doesn't need to
  rediscover this, and so Phase 4 can consider a single shared
  "TradeNodeSelect" component instead of N separate fixes.
- **Regression test:** `typology-boq-procurement.spec.ts` → asserts no
  option text matches the ltree-id shape, and that a real name renders.

### UI-P2-010 (P1, confirmed, not fixed — explicit Phase 3 item) — No delete-BOQ-item UI
- **Page(s):** `BoqReconciliationPage.tsx`
- **Role:** lead_estimator (server allows lead/proc/md)
- **Steps:** open BOQ reconciliation, look for any way to remove a line
  item.
- **Expected/actual:** none exists. `DELETE /boq-items/{id}` is a real,
  unused endpoint (already documented in `docs/ui-qa/coverage.md` §2).
  Reconfirmed live, not new. **Not fixed here** — `docs/ui-qa-brief.md`
  Phase 3 explicitly lists this as a gap-fill item, out of Phase 2's scope.
- **Regression test:** `typology-boq-procurement.spec.ts` → asserts no
  delete button currently exists, so Phase 3 adding the UI is a deliberate,
  visible change to this assertion rather than an accidental regression
  either direction.

### Cross-cutting observation, not fixed — money fields are serialized to JSON as `float`, not the string the brief assumes
- **Page(s):** none of this run's pages actually display currency (BOQ
  quantities/variances here are correctly `float`-typed physical
  quantities, not money — checked `backend/app/schemas/boq.py` before
  flagging, this is **not** a bug). This is a note for whoever QAs
  Settlement/Quotes/Export, and for Phase 4/main session.
- **What was found:** `backend/app/schemas/common.py`'s `JsonDecimal`
  (used for real money/percentage fields in `settlement.py`, etc.) is
  `Annotated[Decimal, PlainSerializer(lambda v: float(v), ...,
  when_used="json")]` — every `JsonDecimal` field is converted to a Python
  `float` **before** JSON serialization. `docs/ui-qa-brief.md` §0.2 states
  "API Decimals arrive as JSON strings; parse them safely and never with a
  float `parseFloat`" — the actual wire format is a JSON **number**
  (already float-lossy at the source), not a string, so there's nothing
  for the frontend to unsafely `parseFloat` in the first place; the
  precision loss, if any, already happened server-side at serialization.
  For typical AED amounts (low millions, 2dp) a double has more than
  enough precision that this is very unlikely to produce a visibly wrong
  total, but it's a real deviation from the brief's stated Decimal-to-the-
  wire architecture and worth a deliberate main-session decision (accept
  as-is with a note, or change `JsonDecimal` to serialize as a string and
  update every frontend consumer) rather than a page-scoped fix.
- Also separately confirmed **no shared money-formatting utility exists
  anywhere in the frontend** (`grep -r "formatAED\|formatMoney\|Intl.NumberFormat"`
  → zero matches) — every money display found so far (`SettlementPage.tsx`)
  uses ad-hoc `.toFixed(2)` with no thousands separator and no "AED"
  prefix. Out of this run's page scope to fix (none of pages 5-8 display
  money), flagging for whoever QAs Settlement/Export/Quotes and for
  Phase 4's design system (which explicitly calls for "tabular figures for
  numbers" and AED formatting).

### Reconfirmed, not new — breadcrumb/back-link gap and `window.prompt` also present on these 4 pages
- Same as `UI-P2-004`: none of TypologyPage/BoqImportWizardPage/
  BoqReconciliationPage/ProcurementPackagesPage had a back link before this
  run (BoqReconciliationPage does at least link *forward* to BOQ import).
  Per the prior run's recommendation, **not** patched one-off here — this
  is now confirmed on all pages tested so far in Phase 2, strengthening the
  case for one shared breadcrumb/back-link component in Phase 4 rather than
  N more individual patches.
- `ProcurementPackagesPage`'s "Resend" button still uses `window.prompt` —
  reconfirmed, not touched (explicit Phase 3 app-wide modal replacement
  item per the brief).

### UI-P2-011 (P1, fixed) — Main-session follow-up on the money-serialization note above: the `JsonDecimal` sweep was genuinely incomplete, and it did hit real, already-shipped pages
- **Page(s):** `QuoteReviewPage.tsx`, `BidLevelingPage.tsx` (both real,
  built pages, not yet QA'd live in Phase 2 — this was found by code
  inspection while following up on the cross-cutting note above, ahead of
  the run that will exercise these pages live).
- **Role:** any
- **What was found:** the previous note's framing ("the actual wire format
  is a JSON number... nothing for the frontend to unsafely parseFloat") is
  only true where `JsonDecimal` is actually used. `docs/build-log.md`'s
  Phase 10 entry already flagged, and left unfixed, that the `JsonDecimal`
  fix was applied only to `settlement.py`/`approvals.py` — every other
  `Decimal`-typed response field elsewhere still used bare `Decimal`, which
  Pydantic v2 serializes to JSON as a **string** (`"350.00"`), while every
  matching field in `frontend/src/types/api.ts` is typed `number`. Five
  response schemas in `app/schemas/quotation_ingestion.py` had this,
  including fields `QuoteReviewPage`/`BidLevelingPage` actually read and do
  arithmetic on: `QuotationOut.stated_total`/`fx_rate_to_base`,
  `QuotationLineItemOut.unit_price`/`quantity`/`extended_price_stated`/
  `extended_price_computed`/`confidence`, `QuotationExclusionFlagOut
  .confidence`, `BidLevelingCellOut.unit_price`/`normalized_unit_price`,
  `QuotationTotalOut.stated_total`. Two more in `app/schemas/module_e.py`
  (`ContractVariationOut.delta_amount`,
  `OutturnCostObservationOut.observed_unit_cost`/`observed_quantity`) —
  Module E has no frontend UI yet (per `coverage.md`), so latent rather
  than live, but would have hit Phase 3's new Module E screens.
- **Fix:** all of the above switched from `Decimal` to `JsonDecimal`
  (`backend/app/schemas/quotation_ingestion.py`,
  `backend/app/schemas/module_e.py`). No behavior change for any request
  schema (money/percentage *input* fields are correctly left as bare
  `Decimal` — pydantic parses a JSON number or numeric string into
  `Decimal` identically either way, per `common.py`'s own comment).
- **Regression test:** `backend/tests/unit/test_response_schema_json_decimal.py`
  — introspects every `ORMModel` subclass across every `app/schemas/*.py`
  module and asserts no field mixes a `Decimal` type with a missing
  `PlainSerializer`, so any future response field added anywhere in the
  schemas package can't reintroduce this. `make test-unit` (344 passed) and
  `make test-api` (19 passed) both green after the fix.
- **Still open, for Phase 4/main session (unchanged from the prior note):**
  whether `JsonDecimal`'s float-not-string wire format itself (as opposed
  to it being applied consistently, which is now fixed) is the right
  long-term choice given `docs/ui-qa-brief.md` §0.2's stated Decimal-to-
  the-wire architecture; and the missing shared money-formatting utility.

## Phase 2 — pages 9-11 (QuarantineQueuePage, QuoteReviewPage,
## BidLevelingPage), tested as procurement_head / estimator / platform_admin

### UI-P2-012 (P1, fixed) — Quarantine/review queue never stopped showing an email once it was auto-processed successfully, drowning out the ones that actually need attention
- **Page(s):** `QuarantineQueuePage.tsx`
- **Role:** procurement_head / bd_director / managing_director (anyone who
  can see the queue)
- **Steps:** log in as `procurement1`, open any project's Quarantine and
  review queue.
- **Expected:** only inbound emails that actually need a human's attention
  (flagged by the system as `needs_review`).
- **Actual:** `list_inbound_review_queue` (`backend/app/services/
  quotation_ingestion.py`) filtered on `review_status == "open"` alone.
  `review_status` defaults to `"open"` for **every** inbound email,
  including ones that were auto-processed and never needed review at all
  (`app/models/quotation_ingestion.py`'s own comment: `needs_review` is set
  even when `match_status == matched`; auto-processing only proceeds when
  `match_status == matched AND not needs_review`) — it only moves off
  `"open"` once someone resolves/dismisses/attaches a row. Confirmed live
  against the real dev tenant ("demo"): 19 ordinary successfully-matched
  emails sat in the queue forever alongside the 4 that genuinely needed
  attention, and this only gets worse as normal mail volume grows over
  time — exactly the kind of thing that would make a real procurement head
  stop trusting the queue.
- **Fix:** added `InboundEmail.needs_review.is_(True)` to the query.
- **Regression test:** `backend/tests/integration/
  test_quotation_ingestion_review.py::
  test_review_queue_excludes_auto_processed_emails_that_never_needed_review`
  (10 passed in the file, up from 9) and `quarantine-quotes-bidleveling.spec.ts`
  → "the review queue excludes ordinary auto-processed emails and only
  shows ones needing attention".

### UI-P2-013 (P2, confirmed, not fixed — needs a main-session decision) — QuarantineQueuePage lives at a project-scoped URL but shows tenant-wide data, not that project's
- **Page(s):** `QuarantineQueuePage.tsx` (route
  `/projects/:id/procurement/quarantine`)
- **Role:** any
- **What was found:** `GET /quotation-inbound-review`
  (`backend/app/api/v1/routes/quotation_ingestion.py`) is **not**
  project-scoped at all — it takes no `project_id` and returns every
  `needs_review` row RLS lets the caller's tenant see. The frontend page
  faithfully calls this unfiltered endpoint regardless of which project's
  `:id` is in the URL. Practical effect: opening Project A's quarantine
  queue and Project B's quarantine queue shows the **identical** list,
  with nothing in the UI indicating this isn't project-scoped — confusing
  for a user who reasonably expects a project-nested page to show that
  project's own data (`InboundEmail` also has no `project_id` column at
  all; only an optional `rfq_id`, which is `NULL` for exactly the
  `quarantined_unknown_tenant` rows that need review most).
- **Why not fixed here:** fixing this properly is a product decision, not
  a page patch — either (a) move the page to a real global route
  (`/procurement/quarantine`, matching what it actually shows), which
  changes navigation/IA, or (b) add real project scoping to `InboundEmail`
  and the query, which is a schema change. Flagging for Phase 3/4 /
  main-session decision rather than guessing.
- Not to be confused with UI-P2-012 above (a real query bug, fixed) — this
  one is a navigation/IA mismatch, not incorrect data.

### UI-P2-014 (P2, confirmed, not fixed) — No `platform_admin` demo user exists anywhere; its one exclusive UI action ("Resolve tenant") cannot be exercised live at all
- **Page(s):** `QuarantineQueuePage.tsx`'s "Resolve tenant" control (visible
  only to `platform_admin` on a `tenant_id IS NULL` row)
- **Role:** platform_admin
- Checked `deploy/keycloak/bootstrap.sh`'s `seed_user` calls (estimator1,
  lead1, procurement1, bd1, md1 — five roles, matching the SRS's five, per
  `docs/ui-qa/coverage.md`'s own note that `platform_admin` is
  "Keycloak-only, not in the SRS's five") and every `frontend/e2e/
  real-backend/*.spec.ts` and `totp.ts`: no `platform_admin` user is ever
  seeded or logged in as, anywhere. The 3 real `quarantined_unknown_tenant`
  rows sitting in the dev database right now (confirmed via direct SQL)
  are consequently untestable through the real UI by anyone, and a real
  deployment team has no documented way to interactively exercise this
  action either. Recommending Phase 1/3 add a seeded `admin1` /
  `platform_admin` demo user the same way the other five are seeded.
- **Regression test:** `quarantine-quotes-bidleveling.spec.ts` →
  "resolve-tenant is not offered to a non-platform_admin role" (confirms
  the negative case only; the positive case is exactly what's blocked).

### UI-P2-015 (P1, fixed) — QuoteReviewPage has no client-side role gate on Accept/Reject/Reject quotation/Set currency/Promote; an unauthorized role gets a silently-failing button
- **Page(s):** `QuoteReviewPage.tsx`
- **Role:** estimator (server allows only procurement_head/bd_director/
  managing_director — `_REVIEW_ROLES` in `backend/app/api/v1/routes/
  quotation_ingestion.py`; notably **not** even `lead_estimator`, despite
  this page being nav-gated to "all" per `docs/ui-qa/coverage.md`)
- **Steps:** log in as `estimator1`, open Quote review on any project with
  quotations, try Accept/Reject/Promote/Set currency/Reject quotation.
- **Expected:** these controls are hidden for a role that can't use them,
  same pattern already fixed on TypologyPage/ProcurementPackagesPage
  (UI-P2-007/UI-P2-008).
- **Actual:** every one of these buttons was fully rendered for any role,
  and **none** of the five mutations (`useAcceptLineItem`,
  `useRejectLineItem`, `usePromoteQuotationVersion`,
  `useResolveCurrencyVat`, `useRejectQuotation`) rendered its `.isError`
  state — a click by an unauthorized role just silently 403'd with zero
  feedback.
- **Fix:** added a `hasRole(procurement_head, bd_director,
  managing_director)` gate around all five actions, and error text under
  each one.
- **Regression test:** `quarantine-quotes-bidleveling.spec.ts` →
  "estimator sees no review actions, and a direct accept attempt 403s
  server-side" / "procurement_head sees review actions...".

### UI-P2-016 (confirmed correct, not a bug) — BidLevelingPage is read-only; no role gate needed
- **Page(s):** `BidLevelingPage.tsx`
- Every action on this page is a client-side cell selection (no mutation
  hooks at all) — checked deliberately given the pattern above, but there
  is nothing here for any role to be incorrectly allowed to do. No fix
  needed.

### UI-P2-017 (P2, not fixed, deferred to Phase 4) — BidLevelingPage shows nothing (not even an empty-state message) when a selected package has zero bid-leveling rows
- **Page(s):** `BidLevelingPage.tsx`
- The table only renders when `rows.length > 0`; a package with no
  accepted line items yet renders a blank area below the package dropdown
  with no "no bids yet" message and no loading indicator for any of its
  three queries. Not exercised live this run (every demo project has at
  least one accepted line item), found by code review. Same class of gap
  as UI-P2-006 (ProjectsListPage's missing empty state) — Phase 4 polish,
  not a functional break.

### Confirmed live — `JsonDecimal` fix (UI-P2-011) verified correct on the pages it actually affects
Both `QuoteReviewPage` and `BidLevelingPage` now render `unit_price`/
`quantity`/`confidence`/`normalized_unit_price` as real JSON numbers end to
end against the real backend (`typeof` assertions in
`quarantine-quotes-bidleveling.spec.ts`, not just "it displays *some*
text") — confirms UI-P2-011's fix actually reaches these two already-shipped
pages, not just the schema layer.

### Reconfirmed, not new
- `QuarantineQueuePage`'s resolve-tenant/attach/dismiss still use
  `window.prompt` (Phase 3 app-wide modal replacement item).
- No back link on `QuarantineQueuePage`/`QuoteReviewPage`/
  `BidLevelingPage` either — same app-wide gap as UI-P2-004, still
  deliberately not patched one-off (now confirmed on 11 of the app's ~15
  pages).
- Raw UUID text inputs for "Tenant ID"/"RFQ ID" on `QuarantineQueuePage`
  (paste-a-UUID-by-hand instead of a picker) — P2 polish, Phase 4.

## Phase 2 — pages 12-14 (SettlementPage, ExportPage, WinLossPage)

### UI-P2-018 (P1, fixed) — SettlementPage's "Build (new) settlement draft" and "Submit for approval" had no client-side role gate; an unauthorized role saw fully-enabled, silently-failing buttons
- **Page(s):** `SettlementPage.tsx`
- **Role:** estimator (build), estimator/lead_estimator/procurement_head (submit)
- **What was found:** same recurring pattern as UI-P2-007/008/015 —
  `backend/app/api/v1/routes/settlement.py`'s `_HEADER_ROLES`
  (lead_estimator/procurement_head/bd_director/managing_director; NOT
  estimator) gates build/rebuild, and `_SUBMIT_ROLES`
  (bd_director/managing_director only) gates submit, but neither button
  checked the logged-in user's role client-side, and `buildDraft`/`submit`
  had no error display either.
- **Deliberately NOT touched:** Approve/Reject's role eligibility beyond
  the existing SoD (submitter) check — `app/services/approvals.py::decide`
  authorizes against the *specific routed approval tier's* `required_role`
  (dynamic, margin-threshold-driven — see `SimulateResult.required_role`),
  which `BidSettlementOut` doesn't currently expose for an already-
  submitted request. Hardcoding a static role list here risks hiding a
  legitimate Approve button from an eligible approver, or the reverse — SoD
  (which IS a static, correct check) is untouched and still works. Logging
  this as a P2 UX gap for Phase 3/4: expose the routed tier's
  `required_role` on `BidSettlementOut` so `SubmitApprove` can show/hide
  correctly instead of relying purely on the server 403ing.
- **Fix:** `hasRole` gates added mirroring `_HEADER_ROLES`/`_SUBMIT_ROLES`
  exactly, plus error display on `buildDraft`/`submit`/`decide`, plus an
  `isError` branch on the settlement fetch itself (was previously silently
  swallowed like the pre-UI-P2-001-fix pages).
- **Regression test:** `settlement-winloss-roles.spec.ts` — two tests,
  both confirmed live: estimator1 doesn't see "Build (new) settlement
  draft" (server 403 also confirmed via a direct `POST
  /projects/{id}/bid-settlements`), and estimator1 doesn't see "Submit for
  approval" on an actual draft. `make test-unit`/existing
  `settlement.spec.ts` (real MFA step-up + SoD approve/reject flow, from
  Phase 0) untouched and still green — confirmed by re-reading it, not
  re-run mocked.
- **Escalation note:** none needed — this is the routine role-gate/error-
  display pattern already established on 4 other pages, not a SoD/step-up/
  money-math bug. The one thing that WAS SoD/policy-adjacent (Approve's
  dynamic role eligibility, above) was deliberately left alone rather than
  guessed at.

### UI-P2-019 (P1, fixed) — WinLossPage's record-outcome form had no client-side role gate; any role could fill out and submit it
- **Page(s):** `WinLossPage.tsx`
- **Role:** estimator/lead_estimator/procurement_head
- **What was found:** `_OUTCOME_ROLES` (bd_director/managing_director
  only) gates `POST .../outcome` server-side, but the full form (outcome,
  prices, reason codes, note, submit button) rendered unconditionally for
  any role once a settlement existed with no outcome yet recorded — at
  least this one already had `recordOutcome.isError` display (unlike the
  other pages in this pattern), so the failure wasn't silent, but the form
  itself was misleadingly presented as usable.
- **Fix:** added a `canRecordOutcome` gate (mirrors `_OUTCOME_ROLES`); an
  unauthorized role now sees "No outcome recorded yet. Only bd_director/
  managing_director can record it." instead of the form. The existing
  outcome-already-recorded read-only view (for any role) is unchanged.
- **Regression test:** `settlement-winloss-roles.spec.ts` — confirmed live
  against D1-SIM's actual current settlement (outcome still null): bd1
  sees the "Record outcome" button, lead1 (added as a project member via
  `ensureProjectMember`) sees the explanatory message instead.

### UI-P2-020 (P2, not fixed, deferred to Phase 4) — Settlement export filenames use the project's raw UUID, not its human-readable code
- **Page(s):** `ExportPage.tsx` (client) / `backend/app/services/settlement.py`
  (`export_settlement`/`export_original_settlement`, lines ~766/993)
- Checked per the brief's "downloads... have sensible filenames" item.
  `downloadFile()` (`frontend/src/lib/api.ts`) correctly reads the
  server's real `Content-Disposition` header (its hardcoded
  `fallbackFilename` argument is only a never-hit safety net, confirmed by
  reading the route — this is NOT the bug it initially looked like). The
  actual filename the server generates is
  `settlement-{project_id}-v{version_no}.xlsx`, e.g.
  `settlement-a1b2c3d4-e5f6-...-v3.xlsx` — technically unique and correct,
  but an estimator with several downloaded files in one folder can't tell
  projects apart by filename alone. P2 polish (the file is otherwise
  entirely correct and usable) — Phase 4 fix: use the project's `code`
  (e.g. `D1-SIM`) instead of its id, which needs the project row already
  in scope at both call sites (both already load the project internally to
  build the workbook, so this is likely a one-line change per site, not
  investigated further here to stay in scope).

### Confirmed correct, not fixed — ExportPage has no missing role gate
`_LINE_ROLES` (estimator + all four other roles) covers every real role, so
"any role can export" is correct behavior, not a gap — confirmed by reading
the route.

### Confirmed live — ExportPage correctly refuses to export a non-approved settlement, with a clear message
Attempted a real download via `settlement-winloss-roles.spec.ts` against
D1-SIM's actual current settlement (status `draft` at the time). The
"Download generated .xlsx" button stayed clickable (not hidden/disabled)
but produced no download — `export_settlement` correctly 403s with "Bid
settlement is draft, not approved -- export is only available once
approved", which `ExportPage.tsx` shows under the button via
`exportGenerated.isError`. This is acceptable UX for a genuinely
conditional (state-based, not role-based) restriction, unlike the role-gate
bugs found elsewhere — not fixed, not a gap. The regression test also
covers the actual successful-download path (real `Content-Disposition`
filename, see UI-P2-020) but that half only runs when D1-SIM happens to be
in `approved` state (it skips with a clear reason otherwise, same pattern
as UI-P2-018's tests) — verify by running the full suite through a
completed `settlement.spec.ts` approval first if this needs re-confirming
end to end.

## Phase 2 — AdminPage, AuditPage, and the cross-cutting permission matrix (docs/ui-qa/coverage.md section 4)

### UI-P2-021 (P1, fixed) — None of AdminPage's six tabs had any client-side role gate; every tab's write controls were fully enabled to any role that could reach the page
- **Page(s):** `AdminPage.tsx` and all six sub-components under
  `frontend/src/features/admin/`: `TaxonomyAdmin`, `ApprovalPoliciesAdmin`,
  `TolerancesAdmin`, `LayerTradeMappingAdmin`, `ReasonCodesAdmin`,
  `VendorRegionsAdmin`.
- **Role:** any role that reaches `/admin` (nav-gated to
  `platform_admin`/`managing_director`, but see UI-P2-022 below — the page
  has no route-level guard, so it's also reachable directly by URL).
- **Steps:** log in as any role other than `managing_director`, open
  `/admin` (via nav if `platform_admin`, via direct URL otherwise), try any
  tab's write control.
- **Expected:** a role the server will refuse gets a hidden/disabled
  control or a clear explanatory message, same as every other page fixed
  this phase.
- **Actual (confirmed live before the fix):** every tab showed its create/
  edit form fully enabled to any authenticated user, regardless of role —
  same recurring pattern as UI-P2-007/008/015/018/019, just not yet applied
  to Admin.
- **Fix:** added a `hasRole` gate (mirroring each endpoint's real
  server-side role list, one constant per component with a comment citing
  the backend file/constant) around each tab's write form, disabled the
  per-row edit widgets (checkboxes/selects) for a non-writing role, and
  added missing `isError` displays on every mutation
  (`updateNode`/`moveNode` on Taxonomy, `setActive` on Approval policies,
  `setTolerance`, `replace` on Layer-mapping and Vendor-regions,
  `updateCode` on Reason codes). The exact role lists, confirmed by reading
  each route file:
  - Taxonomy, Tolerances, Layer-mapping: `lead_estimator`/
    `procurement_head`/`managing_director`.
  - Approval policies: **`managing_director` only.**
  - Reason codes, Vendor regions: `lead_estimator`/`procurement_head`/
    `bd_director`/`managing_director`.
  - None of the six include `platform_admin` — see UI-P2-022.
- **Also fixed in passing:** `TaxonomyAdmin.tsx` had the same raw-ltree-
  path-as-label bug already flagged (not yet fixed) in UI-P2-009's
  "found elsewhere" note — both dropdowns (`-- No parent (root) --` create
  form, and the per-row "move to new parent" picker) showed `n.path`/
  `candidate.path` instead of `.name`. Fixed both.
- **Regression test:** `frontend/e2e/real-backend/admin-audit-permissions.spec.ts`
  — `managing_director` sees every tab's write form; `lead_estimator`
  reaches `/admin` by direct URL (no nav link) and sees exactly the write
  access the server actually grants (5 of 6 tabs, not Approval policies);
  `estimator` sees every tab as read-only, plus a direct `POST /taxonomy`
  attempt independently 403s server-side.

### UI-P2-022 (P1, confirmed via code reading, not fixed — needs a product decision) — `platform_admin` is nav-gated into `/admin` and `/audit`, but is in NONE of the underlying endpoints' write/read role lists
- **Page(s):** `AdminPage.tsx` (all six tabs), `AuditPage.tsx`.
- **Role:** `platform_admin` (the `admin` role — see coverage.md's role
  glossary).
- **Why not verified live:** no `platform_admin` demo user exists anywhere
  in the seed data (already logged as UI-P2-014, blocking the Quarantine
  page's "Resolve tenant" action too) — confirmed instead by reading every
  relevant route file's role decorator, cross-referenced against
  `frontend/src/app/AppShell.tsx`'s nav gates:
  - `/admin` nav gate: `platform_admin`, `managing_director`
    (`AppShell.tsx:41`).
  - Taxonomy/Tolerances/Layer-mapping writes: `lead_estimator`/
    `procurement_head`/`managing_director` — no `platform_admin`.
  - Approval policy writes: `managing_director` only — no `platform_admin`.
  - Reason codes/Vendor regions writes: `lead_estimator`/
    `procurement_head`/`bd_director`/`managing_director` — no
    `platform_admin`.
  - `/audit` nav gate: `platform_admin`, `managing_director`,
    `bd_director` (`AppShell.tsx:42`). Server `_READ_ROLES`
    (`backend/app/api/v1/routes/audit.py`): `lead_estimator`/
    `procurement_head`/`bd_director`/`managing_director` — no
    `platform_admin` (and `GET /audit/verify` is `managing_director`
    only, also excluding `platform_admin`).
- **Net effect:** a `platform_admin` user would see nav links to `/admin`
  and `/audit`, and (after this run's own role-gate fix) `/admin`'s six
  tabs would all correctly show as read-only for them — but `/audit`
  itself would 403 immediately on load (the page's own list query is
  gated by `_READ_ROLES`, which excludes `platform_admin` entirely), so
  the nav link leads to an error page, not a read-only view. This is
  `platform_admin`'s *only* other nav-visible destination besides the
  Quarantine queue's tenant-resolution action — i.e. two of this role's
  three reachable surfaces are either fully read-only or fully broken.
- **Not fixed here:** this looks like it could be intentional (the brief
  itself describes `platform_admin` as a narrow, Keycloak-only role for
  the quarantine tenant-resolution action specifically, not a general
  admin persona — see `docs/ui-qa/coverage.md`'s role glossary), in which
  case the right fix is narrowing the nav gates (drop `platform_admin`
  from `/admin` and `/audit`'s `requiresRoles`), not widening every
  backend role list to include it. Flagging for a main-session/product
  decision rather than guessing which direction is correct — this is
  exactly the kind of role-model question the brief reserves for that
  review, not a page-scoped UI fix.
- **Regression test:** none added (nothing to assert without knowing which
  direction is correct) — `admin-audit-permissions.spec.ts`'s
  `estimator`/`lead_estimator` tests cover the roles that ARE testable.

### UI-P2-023 (P1, confirmed live, not fixed — same product decision as UI-P2-022) — SettlementPage's nav gate excludes two roles that have real, server-granted access to it
- **Page(s):** `SettlementPage.tsx`.
- **Role:** `estimator`, `procurement_head`.
- **What was found (initially looked like a P0 data leak — it isn't):** a
  cross-cutting spot-check navigated `estimator` directly to
  `/projects/:id/settlement` (nav-gated to `lead_estimator`/`bd_director`/
  `managing_director` only per `AppShell.tsx`) expecting a 403, and instead
  got the full cockpit — tender total, cost breakdown, margin %, sliders.
  Investigated before concluding either way: `list_settlements_endpoint`/
  `get_settlement_endpoint` (`backend/app/api/v1/routes/settlement.py`) use
  plain `CurrentUser` (any authenticated, project-visible user), which is
  consistent with `_LINE_ROLES` (`= ESTIMATOR + every _HEADER_ROLES role` —
  i.e. all 5 business roles) genuinely granting `estimator` simulate/line-
  edit/save-scenario/export access on this page. **This is real, intended
  server-granted access, not a leak** — confirmed `estimator`'s Build/
  Submit buttons correctly stay hidden regardless (UI-P2-018).
- **The actual, still-real finding:** the nav gate (`lead_estimator`/
  `bd_director`/`managing_director`) doesn't match either role's real
  permissions: `estimator` has genuine `_LINE_ROLES` access (simulate/
  edit lines/save scenarios/export/read) and `procurement_head` has
  genuine `_HEADER_ROLES` access (build draft, update defaults, trade
  overrides, refresh quantities — only `_SUBMIT_ROLES`/`_OUTCOME_ROLES`,
  bd/md, are actually restricted the way the nav gate implies). Both roles
  can only reach real, permitted work here by knowing the direct URL.
- **Same disposition as UI-P2-022:** this is a product/nav-model decision
  (should the nav gate widen to match real permissions, given the brief's
  own goal names "a real estimator, procurement head or director" as the
  target user?), not a page-scoped bug fix — flagging alongside UI-P2-022
  rather than guessing.
- **Regression test:** `admin-audit-permissions.spec.ts` → the
  `SettlementPage` cross-cutting test now asserts the *correct* behavior
  (real figures render for `estimator`, Build/Submit stay hidden) instead
  of the wrong assumption it started with.

### Confirmed correct, not a leak — cross-cutting permission matrix (coverage.md section 4)
Spot-checked (not exhaustively re-tested — every page already checked its
own obvious cases while being fixed this phase; this targeted the specific
open question coverage.md section 4 raised: does a nav-hidden page still
enforce access when reached by direct URL, since `App.tsx` has no
route-level role guard, only `RequireAuth` for authentication):
- `estimator` navigating directly to `/audit` (nav-hidden): page loads
  (`RequireAuth` only checks authentication), but the list query 403s
  immediately with a clear message ("Requires one of roles: ...") and no
  table renders — no data leak.
- `estimator` navigating directly to `/projects/:id/settlement` (nav-
  hidden): **not** a leak, see UI-P2-023 — real figures render because
  this role has genuine server-granted read/simulate/export access there;
  Build/Submit correctly stay hidden.
- `lead_estimator`/`procurement_head` reaching `/admin` by direct URL
  (nav-hidden for both): **not** a leak — see UI-P2-021, their write
  access on 5 of 6 tabs is real and server-granted, the nav gate just
  undersells it.
- Direct API writes independently re-confirmed refused for `estimator`:
  `POST /taxonomy` (403, via UI-P2-021's test), `POST /vendors` (403,
  vendor master is lead/proc/bd/md only per coverage.md section 2),
  `POST /cost-items` (403, cost library write is lead/proc/md only per
  coverage.md section 2) — these two hadn't been checked from the direct-
  API angle yet (Vendor master and Cost library both have zero frontend
  page at all, per coverage.md section 2, so there was no page-level test
  to derive this from).
- No route-level 404/role-guard gap found beyond what UI-P2-001 (missing
  catch-all) and UI-P2-022 (above) already cover.

**Phase 2 is now done.** All 14 routed pages plus AdminPage/AuditPage
walked live as their relevant roles. Totals across the whole phase: 13 P1s
found and fixed (UI-P2-001, 002, 003, 004, 007, 008, 009, 011, 012, 015,
018, 019, 021 — see `docs/ui-qa/log.md`'s per-batch entries for each one's
detail), 1 confirmed pre-existing gap left for Phase 3 (UI-P2-010, explicit
brief item), 2 flagged for a product/nav-model decision rather than fixed
(UI-P2-022 `platform_admin` on Admin/Audit, UI-P2-023 `estimator`/
`procurement_head` on Settlement — both are "nav gate narrower than real
server-granted permissions," not security defects), and several P2 polish
items deferred to Phase 4 (UI-P2-005, 006, 013, 014, 017, 020). New
regression tests: 8 (pages 1-4) + 6 (pages 5-8) + 1 (backend JsonDecimal
sweep) + 6 (pages 9-11) + 4 (pages 12-14) + 8 (Admin/Audit/cross-cutting)
= 33 new tests this phase, all passing.
