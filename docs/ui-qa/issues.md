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
