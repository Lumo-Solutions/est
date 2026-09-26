# Build log — Est Build pre-construction programme

Tracks progress against `docs/preconstruction-build-brief.md`. Read this
first when resuming after a context compaction; continue from the first
phase that isn't `unit-green`.

## Housekeeping

- `backend;C` and `ai-service;C` at the repo root are empty directories
  (confirmed via `ls -la`), almost certainly created by Git Bash/MSYS
  rewriting a `C:` absolute path into a literal directory name at some
  earlier command. Harmless, left in place per the brief (0.5) — not
  deleted. User to decide whether to remove them.

## Phase 1: D1, bid settlement and margin simulation

**Status:** in progress

- Corrections from the brief applied to `docs/module-d1-plan.md`: rates
  authoritative (no rounding residual/largest-line absorption), submitter
  cannot approve their own settlement (segregation of duties), explicit
  status lifecycle (draft → submitted → approved|rejected → won|lost,
  export only from approved), quantity-vs-current-BOQ check at submit,
  boundary tests for the AED 2,000,000 / 8% approval thresholds.
- Branch: `feat/d1-settlement` (from `master`).
- Migrations: TBD (0018 approvals `max_margin_pct` extension, 0019
  `bid_settlements`/trade overrides/line items).
- Commits: TBD.
- Test counts: TBD.
- Assumptions / deviations: TBD.
- Known gaps: TBD.
- Pre-existing bugs found (separate from new work): TBD.

## Phase 2: D2, client BOQ export (generated) and win/loss

**Status:** not started

## Phase 3: D3, export into the client's original workbook

**Status:** not started

## Phase 4: Module B, remaining takeoff features

**Status:** not started

## Phase 5: semantic matching (B and C)

**Status:** not started

## Phase 6: Module C, remaining procurement features

**Status:** not started

## Phase 7: Module E schema readiness

**Status:** not started

## Phase 8: frontend

**Status:** not started

## Phase 9: end-to-end and wrap-up

**Status:** not started
