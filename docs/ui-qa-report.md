# UI QA, Gap-Fill and Redesign — Final Report

Covers the full run against `docs/ui-qa-brief.md` (Phases 0–4, summarized in
`docs/v2.md`) and this finish run against `docs/finish-brief.md` (saving the
dev MFA switch, closing and merging Phase 4, the small v2 gaps, and this
Phase 5 final regression). The detailed running narrative for every phase is
`docs/ui-qa/log.md`; every individual QA finding from Phases 0–4 is in
`docs/ui-qa/issues.md`. Nothing has been pushed.

## Where things stand

Everything is merged to `master`: Phases 0–3 (from the original run),
`phase-4-design-system` (`75984a3`), `feat/dev-mfa-switch` (`ba545dc`), and
`feat/v2-gaps` (`61cfe1b`), plus a handful of main-session fixes and the
Phase 5 walkthrough's own fix, all as commits directly on `master` after the
merges. The dev MFA switch (`DEV_DISABLE_MFA`) is a new, permanent dev/test
capability, not a leftover — it stays.

**Subagents:** none were used in this finish run (steps 1–3, the Phase 4
close-out and Phase 5 were all done directly by the main session), so
rule A7's per-branch verification has no agent branches to check against.
The original brief's Phases 0–4 *did* use subagents; that verification is
recorded in `docs/ui-qa/log.md`'s own "Process notes" and "Main session's
final review" sections.

## Coverage matrix

`docs/ui-qa/coverage.md` — every frontend route × role × action mapped to
its backend endpoint(s), built from a full walk of `frontend/src` and every
`backend/app/api/v1/routes/` file. Every page listed there was walked live
through the real UI, as every role that can reach it, across Phase 2
(page-by-page) and the cross-cutting permission-matrix pass at the end of
Phase 2 — see `docs/ui-qa/log.md`'s Phase 2 section for the page-by-page
detail. This finish run's own lifecycle walkthrough (below) re-confirmed
several of those live, on a brand-new project rather than the seeded
fixtures.

## Issues found and fixed, by severity

Full detail and ids are in `docs/ui-qa/issues.md` (Phases 0–4) and
`docs/ui-qa/log.md` (this finish run). Summary:

**P0:** none found anywhere in the app. One suspected P0 (an `estimator`
reaching full settlement figures by direct URL) was investigated and found
to be genuine, intentional server-granted access, not a leak (UI-P2-023 in
`issues.md`).

**P1 — fixed (15 across Phases 0–4, listed in `issues.md`; plus this finish
run's own):**
- Phases 0–4: no catch-all 404 route; 4xx retried 3× before showing an
  error; `TakeoffViewerPage` indefinite loading on error; no back-links;
  role gates missing on Typology/Procurement/QuoteReview/Settlement/
  WinLoss/Admin write actions (the single most repeated bug class across
  the whole QA run — an action a role can't perform stayed fully enabled
  and failed 100% silently); raw ltree path shown instead of a trade name;
  the `JsonDecimal` sweep left 7 real response fields serializing as JSON
  strings against frontend types declared `number`; quarantine queue never
  filtered out auto-processed mail.
- **This finish run:** `SettlementPage`'s per-line manual-cost override had
  no field to enter the required reason (`source_note`), so every attempt
  422'd — found live during the Phase 5 walkthrough, on the exact case this
  cost source exists for (no accepted quote yet). Fixed (`c8876fd`); the
  existing e2e test only asserted "no *role* error" and so had been passing
  against the silent failure the whole time — strengthened to require the
  field and check for actual success.

**P2 — fixed as part of the Phase 4 redesign:**
`text-success` as plain text measured 3.76:1 under axe (not the 4.5:1 AA the
design doc originally claimed) on 3 sites (`BoqReconciliationPage`'s Accept
link, `VendorsPage`'s duplicate-check message, `DrawingUpload`'s status) —
all switched to `text-emerald-700`, and a new axe check (stubbing the
suggestions response so the previously-never-rendered Accept link is
actually scanned) confirms it. The `NavLink` `end` bug (Overview highlighted
alongside every sub-page) — fixed. `make dev-simulate-settlement`'s
non-idempotency, which made several e2e tests skip on a non-fresh
stack — fixed (`b2e3b29`): it now resolves any leftover unpriced BOQ line
with a manual cost and tolerates the (correct) refusal of the
original-workbook export when the shared project's BOQ spans several import
batches; ran twice in a row, both exit 0.

**Pre-existing bugs found and fixed (not new work, real regressions in
already-shipped code):** `acknowledge_exclusion_flag` never audited;
`taxonomy.update_node`/`move_node` crashed with `MissingGreenlet` (a 500 on
every rename/toggle/move); same bug in `boq.set_tolerance`; `bid_settlement_
scenarios`' RLS had no DELETE policy (migration `0028`); the default
`npm run e2e` config also matched `e2e/real-backend/**` and ran ~80
real-login specs on 6 parallel workers against the shared stack (49 failed
from TOTP replay/brute-force contention) — fixed by excluding
`real-backend/**` from the default config.

## New screens and endpoints

Full list in `docs/v2.md`'s Phase 3 section. Since that summary, this finish
run adds:
- `GET /auth/me` now returns `username` (Keycloak's `preferred_username`,
  via a new realm mapper) — the header shows a name instead of the raw
  subject UUID.
- `DELETE /projects/{id}/members/{user_id}` (bd/md/lead, audited, 404 if not
  a member) and its UI (Remove button + confirm modal on
  `ProjectDetailPage`).
- `platform_admin` demo user `admin1` (dev/test only, same guard as the
  others) — its one exclusive action ("Resolve tenant" on unknown-tenant
  quarantined mail) is now exercisable and was exercised live.
- `DEV_DISABLE_MFA` (`make dev-mfa-off`/`dev-mfa-on`): a dev/test-only
  switch that turns off login OTP and the step-up check, fail-closed outside
  dev/test, every bypass logged and audited as `mfa_bypassed_dev: true`.

## Design system summary

`docs/ui-design-system.md`: tokens (neutral base, one brand accent,
semantic success/warning/danger/info, all WCAG AA), IBM Plex Sans
self-hosted, a sidebar app shell with project context, shared `Badge` /
`Spinner` / `Skeleton` / `Modal` / `ConfirmModal` / `TextPromptModal`
components, an AG Grid theme via the Theming API. Applied to every page in
the app. Layout targets (1440/1280/1024) hold on every page — see below.

**Before/after screenshots:** `docs/ui-qa/screenshots/phase-4/*-before.png`
/ `*-after.png` for the first restyle chunk (Projects, Sheet index, Takeoff
viewer, Project detail — the set built while establishing the pattern);
later chunks' own before/after captures were traded for verification time
under memory pressure (disclosed in `docs/ui-qa/log.md`, not hidden) — the
axe and layout-width checks below independently confirm every later page,
just not as a before/after pair.

**Layout widths:** `docs/ui-qa/screenshots/phase-4/layout-*-{1440,1280,
1024}.png` — 24 pages × 3 widths (72 screenshots), captured by a new
`layout-widths.spec.ts` that fails on any page-level horizontal overflow.
Passed on every page. I additionally eyeballed the dense pages (Settlement,
BOQ reconciliation, Quote review, Takeoff viewer, Procurement packages,
Admin, Vendor detail, Project detail) at 1024: no breakage. The BOQ grid at
1024 shows the pinned Item No plus roughly 4 columns with the rest reached
by in-grid horizontal scroll — normal for a dense data grid, not a bug.

## Accessibility (axe)

`phase4-accessibility.spec.ts`, 18 checks (every restyled page, Admin's six
tabs, Module E's four tabs) — **18/18 passed, zero serious/critical
violations**, including the previously-unchecked `BoqReconciliationPage`
(its Accept-suggestion link is rendered via a stubbed response so the axe
scan actually reaches it) and `SettlementPage` (closing a verification gap
left open at the end of the original Phase 4 run). Root-caused and fixed a
real flakiness source found while re-running this suite clean: the realm
disallows TOTP code reuse within its 30-second step, so two real logins by
the same demo user in the same step failed the first attempt and cascaded
delays through the whole run — `helpers.ts` now waits for a fresh step
before generating a code.

## Known gaps and anything that needs your decision

Carried forward from Phases 2–4 (`docs/ui-qa/log.md`/`issues.md`), still
open:
- **UI-P2-013:** `QuarantineQueuePage` is at a project-scoped URL but its
  data is tenant-wide — needs a decision on moving it to a global route or
  adding project scoping to `InboundEmail`.
- **UI-P2-017 / UI-P2-006:** `BidLevelingPage` has no empty-state message
  for zero rows; `ProjectsListPage` has no true pagination (an empty-state
  was added, real pagination wasn't).
- **UI-P2-020:** settlement export filenames use the project's raw UUID,
  not its code — works, just not very readable in a downloads folder.
- `VendorPrequalificationOut.max_award_value` and a few other pre-existing
  fields are bare `float` (not `JsonDecimal`) — same JSON wire format,
  style-only.
- Dark theme was not built (explicitly optional per the brief).

New from this finish run, needing your decision:
- **Drawing extraction gets permanently stuck at `extracting`** whenever the
  `embed_drawing` Celery task fails (confirmed live: this dev environment
  has no ONNX embedding model provisioned — a local setup gap, not a code
  bug). Root cause: `index_sheets -> chord(group(extract_sheet),
  embed_drawing) -> finalize_drawing` never calls its callback when one
  task in the chord's group raises, so `finalize_drawing` (the only place
  that sets `ready`/`partial`) never runs, and nothing surfaces an error to
  the user either. This is the same shape as the Phase 2 "GEO-TEST stuck in
  `extracting` since 2026-09-24" observation, now confirmed rather than just
  suspected. Two independent fixes, not chosen without your input:
  provision the embedding model wherever real ingestion needs to work
  (operational, no code change), or make `finalize_drawing` resilient to a
  permanently-failing chord member (a real pipeline change, out of this
  run's scope).
- **P2 operational nit:** after a frontend rebuild, a browser tab that
  already visited the app keeps serving the stale `index.html` (and its
  stale JS bundle) from its own HTTP cache until a hard reload — `nginx`
  serves it with only `ETag`/`Last-Modified`, no `Cache-Control`. Worth
  adding `Cache-Control: no-cache` to `index.html` specifically.

## Final test counts (this run's own clean pass)

Backend (`make test-all`, fresh Docker test stack): **360 unit + 193
integration + 34 api = 587 passed, 0 failed.**

Frontend: `npx tsc --noEmit` clean; `npm run build` succeeds; `npm run
test` (vitest) **29/29 passed**; `npm run lint` (oxlint) clean except 3
pre-existing warnings (unrelated `react-refresh`/`set-state-in-effect`
style warnings, not correctness issues, left as-is per the log's earlier
Phase 4 note).

E2E, mocked (`npm run e2e`): **4/4 passed.**

E2E, real backend (`npm run e2e:real-backend -- --workers=1`, MFA **on**,
one clean run against a stack nothing else was using): **78/78 passed, 0
skipped, 0 failed** (36.1 minutes). `step-up-freshness.spec.ts` (run
separately via its own script, as designed): **1/1 passed.**

## Final lifecycle walkthrough

Done in the Playwright MCP browser against the real dev stack, MFA **off**,
on a brand-new project (`WALK-1`) created for this purpose — not a seeded
fixture — carrying it from creation through to a recorded win:
1. **bd1** creates the project, adds `estimator1` and `lead1` as members.
2. **estimator1** uploads a drawing (confirmed the extraction-stuck bug
   above along the way; confirmed BOQ import correctly 403s for this role).
3. **lead1** imports a 3-line BOQ, creates a procurement package, builds the
   settlement draft, and resolves all 3 lines via manual cost override
   (found and fixed the missing-reason-field bug above in the process).
4. **bd1** submits the settlement for approval.
5. **md1** sees Approve/Reject (bd1's own Approve/Reject stayed correctly
   disabled — SoD, "Awaiting a different approver"), approves, downloads the
   generated export, and records a **won** outcome.

Screenshots: `docs/ui-qa/screenshots/phase-5/01`–`04`. Every role transition
used a real Keycloak login (server-side session revoked between users via
`kcadm`, not just a client-side role swap), and every role boundary crossed
during the walkthrough was enforced server-side, not just hidden client-side.

## Exact commands to verify

```bash
# Backend
make test-all

# Frontend
cd frontend
npx tsc --noEmit
npm run build
npm run test
npm run lint

# E2E (mocked, fast)
npm run e2e

# E2E (real backend — needs `make up` running, nothing else using the stack)
# MFA on:
make -C .. dev-mfa-on   # or: bash ../deploy/keycloak/dev-set-mfa.sh false
npm run e2e:real-backend -- --workers=1
bash ../deploy/keycloak/test-stepup-freshness.sh   # separate, ~5 min

# Leave the stack as this run left it:
make -C .. dev-mfa-off
```

## Where things are left

The stack is running with **MFA off**, as requested, so you can test as
any demo user (`estimator1`/`lead1`/`procurement1`/`bd1`/`md1`, all
`<Name>1Pass!`, plus `admin1`/`Admin1Pass!` for `platform_admin`) without an
authenticator app. `git log` on `master` has every commit; nothing has been
pushed.

## Finish-brief follow-up run (after this report)

A second finish-brief pass ("Final fixes after docs/ui-qa-report.md"),
covering five items: drawing-pipeline resilience, production `APP_ENV`
enforcement, five small UI/deploy gaps, a second live lifecycle
walkthrough, and one more clean full regression. Same rules as before
(main session merges; subagents in worktrees with file allow-lists; main
session verifies every diff). Everything below is on `master`; nothing has
been pushed.

### 1. Drawing pipeline resilience

The stuck-at-`extracting` bug flagged above as "needing your decision" is
fixed, not just diagnosed. `backend/app/workers/tasks/takeoff.py`: each
chord member (`extract_sheet`, `embed_drawing`,
`extract_geometry_measurements`) now claims its job row in an independent,
immediately-committed session *before* doing any work, so a later failure
can always durably record its own reason via a second independent session
without racing the first (a naive version of this deadlocked on
`uq_extraction_jobs_dedup` — see `docs/takeoff-pipeline.md`). The outer
Celery task wrappers swallow a terminal failure (log + let the chord
proceed) instead of leaving the task in a state the chord callback waits on
forever. `finalize_drawing` always runs and always recomputes status
(`force=True` bypasses the normal idempotency skip — needed because a
retry must be able to *change* a prior outcome, not just replay it) and
correctly aggregates ready/partial/failed across whatever combination of
jobs actually finished, excluding embedding/indexing from the "did
everything fail" tally so an optional embedding failure alone yields
`partial`, never `failed`. A new celery-beat task, `reap-stuck-drawings`,
fails any drawing still `extracting` past `DRAWING_STUCK_TIMEOUT_S`
(default 2h, configurable) with a clear stall reason, and clears that
reason if a later retry succeeds. A "Retry extraction" button
(`SheetIndexPage.tsx`, estimator+, audited) resets a `partial`/`failed`
drawing back into the pipeline.

Root-caused, not just papered over: `make download-embedding-model` was
silently writing into an empty Docker volume on this Windows/Git-Bash
machine (a `/tmp/...` path that never existed outside the container) — the
actual reason GEO-TEST and WALK-1 got stuck, unrelated to the chord bug
above, which was a second, independently real issue the same investigation
surfaced. Fixed (`Makefile`, `$(CURDIR)`-relative path +
`MSYS_NO_PATHCONV=1`), and a second real bug in `OnnxEmbedder.embed()`
(missing `token_type_ids` input — every real embed call was failing) is
fixed too. Both stuck drawings were rescued via the new Retry action, and
`make download-embedding-model` followed by a fresh upload was confirmed
live to reach `ready` with real embeddings, not just `partial`.

Tests: `backend/tests/integration/test_takeoff_pipeline_resilience.py` —
embed fails → partial; one sheet fails → partial; every content job fails →
failed (not partial); finalize re-runs and changes status on retry; the
sweeper rescues a stalled drawing and clears its stale reason once ready;
a durable cross-session failure write survives the triggering session's
own rollback; a bare-DXF sheet with no text skips the PDF-render fallback
instead of crashing (found live during this same investigation — fixed in
the same pass, see below).

### 2. Production `APP_ENV`

`deploy/docker-compose.prod.yml` now sets `APP_ENV=production` explicitly
for backend, workers, and beat. `PRODUCTION_MODE` (new setting) makes the
backend refuse to start if `APP_ENV` isn't exactly `production` when set,
and `bootstrap.sh` refuses to seed demo users under it. `make
check-prod-app-env` renders the prod compose config and asserts the
setting; `backend/tests/unit/test_config.py` covers the validator
directly. Noted in `docs/deploy-deltas.md` alongside the local validation
actually performed.

### 3. Small items

- `QuarantineQueuePage` moved to a global `/inbox` route
  (`procurement_head`+), old URL redirects, added to the global nav.
- `ProjectsListPage` now uses real pagination (`GET /projects?limit&offset`,
  a proper `Page` envelope) instead of loading every project unbounded;
  `useProjects()` (no args) kept for the two admin pages still using it.
- Settlement export filenames use the project's `code`, not its raw UUID
  (the P2 nit from the previous report, above) — sanitized against header
  injection (`_project_code_for_filename`, `backend/app/services/
  settlement.py`).
- `frontend/nginx.conf`: `Cache-Control: no-cache` on `index.html`
  specifically (the other P2 nit above), so a rebuilt bundle is picked up
  on next load instead of served stale from the browser's own HTTP cache.
- `BidLevelingPage` empty state and a fix to a real, live-discovered bug in
  BOQ reconciliation: accepting a suggested measurement link the backend
  then 422s (e.g. a dimensionally-incompatible unit) failed 100% silently —
  same recurring bug class as the P1s above. Fixed by rendering
  `linkMeasurement.isError`, same pattern as every other mutation on that
  page; the semantic-feedback "accepted" signal now only fires once the
  link itself actually succeeds, not unconditionally.

### 4. Second lifecycle walkthrough

Same shape as the first (Playwright MCP, MFA off), on a second new project
(`WALK-2`), deliberately covering the path the first one skipped: DXF +
vector PDF upload → extraction reaches `ready` → takeoff viewer (two-point
calibration, a measurement override) → BOQ import → reconciliation with
links (this is where the 422-silent-failure bug above was actually found
live) → procurement package → RFQ dispatch, confirmed in Mailpit → vendor
reply → quote acceptance → bid leveling → settlement built entirely from
real accepted-quote costs → approval by a different user → export → a
recorded win.

One deliberate deviation from the brief's literal wording, noted as
instructed: `make dev-simulate-quotes` always operates on its own fixed
C2-SIM project/RFQ (`app/cli.py::_get_or_create_demo_rfq`), not whichever
RFQ WALK-2 actually dispatched, so it can't simulate a reply *to* WALK-2.
Vendor replies were instead injected by hand — the real dispatched pricing
sheet downloaded from Mailpit, priced, and mailed back into GreenMail via
the same `_pricing_sheet_reply_bytes`/reply-token mechanism
`simulate-quotes` itself uses — for both of WALK-2's RFQs (a second
procurement package was created for the one BOQ item the first didn't
cover, specifically so every line in the eventual settlement would resolve
from a real quote rather than a manual entry). The settlement was built,
rebuilt once after the second RFQ's quote came in (`POST
/projects/{id}/bid-settlements` a second time — the UI's own "Build new
draft" button is correctly gated off while a settlement is still `draft`,
by design, so this step used the API directly), submitted by `bd1`,
approved by `md1` (SoD correctly enforced — `bd1`'s own Approve/Reject
stayed disabled), and every settlement line ended up with
`cost_source: "quotation_line"` — no manual overrides anywhere, per the
brief's explicit instruction. The generated `.xlsx` export was confirmed
working; original-workbook export was correctly declined with a clear
message ("this settlement's BOQ import didn't record a rate column"),
which is the expected fallback behavior, not a bug.

Also surfaced, not fixed (out of this run's scope — a missing feature, not
a regression): there is no UI, and no API endpoint at all, for assigning a
vendor to a trade (`VendorTrade` rows only exist via `app/cli.py`'s
simulation seeders or direct test fixtures). Vendor matching for a real
procurement package is consequently unusable through the app itself for
any trade the seeded CLI fixtures didn't happen to cover — worth a
decision on whether that's in scope for a future pass.

A few things that looked like bugs mid-walkthrough and turned out not to
be, confirmed rather than assumed: a transient 500 on RFQ dispatch was a
one-off Keycloak token-refresh timeout, gone on retry; an empty
matched-vendors list was correct (no vendor seeded for that trade, see
above); a Playwright-MCP download-handling error on the Export page was a
browser-automation artifact, not an app bug (confirmed by calling the same
export endpoint directly — 200, valid `.xlsx`).

### 5. Final regression, this run's own clean pass

`make test-all`: **372 unit + 208 integration + 34 api = 614 passed, 0
failed.** (One integration test — `test_projects_pagination.py`'s
boundaries test — failed once on a full concurrent run with a bare
`asyncpg` connection-checkout `TimeoutError` on its very first query,
i.e. environment resource contention, not a logic failure; confirmed by
re-running that file alone immediately after: 4/4 passed. The clean
full-suite run reported here has all 614 green together.)

`npm run e2e:real-backend -- --workers=1` (MFA off): **78/78 passed, 0
failed**, after fixing one real regression this run's own earlier pass
caught: `settlement-winloss-roles.spec.ts`'s export-filename assertion
still expected the pre-item-3 UUID-based pattern
(`settlement-{project.id}-v\d+.xlsx`); updated to the project-code-based
pattern item 3 above actually produces (`settlement-D1-SIM-v\d+.xlsx`),
confirmed live (`settlement-D1-SIM-v238.xlsx`) before updating the
assertion — the spec's own comment had predicted exactly this ("a future
rename here shows up as a spec change here too, not a surprise"). Verified
in isolation (4/4) before the full clean re-run above.

The stack is left running with **MFA off**, same as before.
