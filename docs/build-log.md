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
