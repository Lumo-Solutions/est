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
