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

**Status:** built, unit-green (`make test-unit` 264 passed, `make test-integration` 102 passed, `tests/api` 18 passed; merged to master)

- Corrections from the brief applied to `docs/module-d1-plan.md`: rates
  authoritative (no rounding residual/largest-line absorption), submitter
  cannot approve their own settlement (segregation of duties), explicit
  status lifecycle (draft → submitted → approved|rejected → won|lost,
  export only from approved), quantity-vs-current-BOQ check at submit,
  boundary tests for the AED 2,000,000 / 8% approval thresholds.
- Branch: `feat/d1-settlement` (from `master`).
- Migrations: `0018_approval_margin_routing` (adds
  `approval_policy_tiers.max_margin_pct`, nullable, backward-compatible),
  `0019_bid_settlements` (`bid_settlements`, `bid_settlement_trade_overrides`,
  `bid_settlement_line_items`, `bid_settlement_scenarios`, all RLS-forced).
  Both applied cleanly against the live dev Postgres (`make migrate`).
- New code: `app/models/settlement.py`, `app/schemas/settlement.py`,
  `app/services/settlement.py`, `app/api/v1/routes/settlement.py` (wired
  into the router), a `bid_submission` policy seed + `simulate-settlement`
  CLI command in `app/cli.py`, `make dev-simulate-settlement`.
- Reused `ApprovalEntityType.BID_SUBMISSION` (`"bid_submission"`), an enum
  member that existed but was never actually used anywhere before this.
- Test counts: unit 264 passed (was 251 — +13: 6 approval-routing boundary
  cases + 7 formula/rounding cases); integration 102 passed (was 88 — +14
  bid-settlement tests); API 18 passed (unchanged, confirms the approvals
  SoD fix doesn't break `cost_rate_change`'s existing flow). `make test`
  (full unit+integration via Docker) kicked off as the final phase check.
- Dev simulation (`make dev-simulate-settlement`, real Postgres/Keycloak/
  Redis dev stack, not testcontainers): seeds a dedicated `D1-SIM` project
  (kept separate from C2's `C2-SIM` demo project deliberately — see below)
  with one accepted quotation line, builds a draft, sets defaults
  (plant=2% overhead=5% volatility=3% markup=10%), previews via
  `simulate()`, submits (`tender_total=13790.00`,
  `margin_on_sell_pct=9.091` — matches hand-calculation exactly), confirms
  the submitting `bd_director` is denied deciding their own request, then
  a second `bd_director` approves it. Full output in this phase's commit
  history.
- Assumptions / deviations:
  - Percentages (`plant_pct`, `overhead_pct`, `volatility_pct`,
    `markup_pct`, `max_margin_pct`, `margin_on_sell_pct`) are stored as
    percent-numbers (`10.00` means 10%), not fractions.
  - A BOQ line item only enters a settlement if `boq_quantity IS NOT NULL`
    (leaf items; section/header rows are excluded).
  - `margin_on_sell_pct` is computed from the exact (unrounded) total
    markup divided by the authoritative (rounded) `tender_total` — a
    deliberate, documented precision-basis choice (§4 of the plan).
  - `decide_settlement()` only flips `bid_settlements.status` to
    approved/rejected on that exact call; there's no separate poll/sync
    path — acceptable since `bid_submission`'s policy is always
    single-tier (`highest_tier_only`), so one `decide()` call always
    resolves the whole request.
- Known gaps:
  - `bid_settlement_scenarios` has no cap on how many a caller can save per
    settlement — fine for a dev/demo volume, worth a limit before
    production if this becomes a real UI feature.
  - No frontend yet (Phase 8) — everything above is API/service/CLI only.
  - Cost-library ↔ BOQ-line auto-suggestion doesn't exist (flagged in the
    original plan as deferred) — `cost_source=cost_library_rate` requires
    the caller to already know which `cost_item_id`.
- Pre-existing bug found and fixed (not new-module scope): the generic
  approval engine (`app/services/approvals.py::decide`) let the same user
  who created an `ApprovalRequest` also decide it — no segregation of
  duties at all, for any entity type, including the already-shipped
  `cost_rate_change` policy (currently unused in production code, but a
  real gap in shipped code regardless). Fixed generically in `decide()`;
  confirmed both directions with a dedicated test
  (`tests/unit`/`tests/integration` cover `bid_submission`; would need a
  `cost_rate_change`-specific test added if that policy is ever wired up
  for real — noted here rather than added speculatively).

## Phase 2: D2, client BOQ export (generated) and win/loss

**Status:** built, unit-green (269 unit + 112 integration + 18 API = 399 passed; merged to master)

- Branch: `feat/d2-export` (from `master`).
- Migration: `0020_boq_import_retention_winloss` -- `boq_import_batches`
  (retains the original `.xlsx` in S3, plus its column mapping incl. the
  two new `rate_column`/`amount_column` letters for D3), two nullable
  columns on `boq_line_items` (`import_batch_id`, `source_row_number`),
  `bid_settlements.outcome_competitor_vendor_ids`, and
  `settlement_reason_codes` (tenant-configurable, seeded).
- New code: `app/models/boq.py::BoqImportBatch`,
  `app/models/settlement.py::SettlementReasonCode`, export/outcome
  additions to `app/services/settlement.py` and
  `app/api/v1/routes/settlement.py`, retention logic in
  `app/services/boq_import.py::commit_import`, reason-code seed in
  `app/cli.py`.
- Test counts: unit 269 passed (was 264 -- +5 leak-scanner tests);
  integration 112 passed (was 102 -- +10: 2 import-retention, 8 export/
  outcome); API unchanged (18). Combined single run: 399 passed.
- Dev simulation (`make dev-simulate-settlement`, extended): build →
  submit → SoD → decide → **export** → **outcome**, against the real dev
  stack. Output: `exported settlement-<project>-v2.xlsx (5063 bytes),
  sha256=060f3756..., leak_scan=CLEAN` then
  `recorded outcome: status=won our_price=13790.00`.
- Assumptions / deviations:
  - `BoqImportColumnMapping.rate_column`/`amount_column` are spreadsheet
    column **letters** (e.g. `"F"`), unlike every other `*_column` field
    on that dataclass, which is header **text** matched against the
    parsed row -- deliberate, since these two exist only so D3 can later
    compute an exact cell reference, never to parse a value.
  - The original workbook is reused from the **existing**
    `installtec-drawings` S3 bucket (`boq-imports/{project_id}/
    {batch_id}.xlsx`), not a new bucket -- avoids a new env var/S3-identity
    grant for what's conceptually the same category of project document.
  - Export role is `estimator+` (the `approved` state gate is the real
    protection; preparing the file once approved is ordinary estimating
    work) -- the brief doesn't specify a role, flagged as a default pick.
  - `record_outcome` accepts a settlement in `submitted` **or** `approved`
    (per the brief's exact wording, not "approved only" like export).
  - VAT is entirely opt-in per export call (`include_vat`/`vat_pct` on the
    request, default `false`/`5.0`) -- not a persisted settlement field.
- Known gaps (carried from the D2 plan, §8):
  - No admin CRUD for `settlement_reason_codes` yet -- seed data only.
  - D3 (writing into the retained original workbook) is a separate,
    not-yet-built phase; nothing before this point can actually *use*
    `source_object_key`/`source_row_number` yet, only record them.
- Pre-existing bugs found and fixed while building this phase (caught by
  the new tests, not by any code review): (1) `boq_import_batches`'
  `item_no_column`/`description_column`/`uom_column`/`quantity_column`/
  `parent_column` were first declared `String(8)`, sized for a column
  *letter* like the two new rate/amount fields -- but those five actually
  store header *text* ("Description" alone is 11 characters), so any real
  header longer than 8 characters would have failed the INSERT outright.
  Widened to `String(255)` in both the migration and the model before
  this branch ever reached master. (2) `commit_import` initially stamped
  `source_row_number` directly from `ParsedBoqRow.row_number`, which is
  1-indexed relative to the *data* rows (row 1 = the first row after the
  header), not the real spreadsheet row -- so a cell reference D3 builds
  from it would have pointed one row too high. Fixed to add
  `mapping.header_row` before storing.

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
