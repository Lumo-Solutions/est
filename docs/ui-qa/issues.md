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
