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

**Status:** built, unit-green (281 unit + 116 integration + 18 API = 415 passed; merged to master)

- Branch: `feat/d3-original-export` (from `master`). No new migration --
  D2's schema already had everything this needed.
- New code: `app/boq/original_export.py` (pure logic: reject macro/
  encrypted, write the rate/amount cells, build the fidelity report by
  diffing the original's and output's raw zip members -- observed, not
  predicted), `preview_original_export`/`export_original_settlement` in
  `app/services/settlement.py`, two new endpoints
  (`/export-original/preview`, `/export-original`).
- Small fix folded in: `commit_import` (D2) never actually populated
  `boq_import_batches.sheet_name` -- fixed before D3 needed it (no
  migration; existing batches keep `sheet_name = NULL` like everything
  else D2 couldn't backfill).
- Test counts: unit 281 (was 269 -- +12: rejection, writing/fidelity,
  four feature-loss categories via a real before/after zip diff, extended
  conditional-formatting detection, a clean-workbook control); integration
  116 (was 112 -- +4: happy path, lossy-blocked-then-accepted-and-audited,
  ineligible-no-batch, denied role). Combined: 415.
- Dev simulation: extended `_get_or_create_d1_demo_rfq` to go through the
  **real** `commit_import` path (a synthetic workbook with a merged title
  cell) instead of creating the BOQ item directly, so a real
  `boq_import_batches` row -- and a real SeaweedFS round trip for the
  retained file -- exists for `make dev-simulate-settlement` to exercise.
  Full chain verified against the real dev stack: build → submit → SoD →
  decide → generated export (clean) → **original-workbook export**
  (`fidelity preview: ok=True lost_features=[]`, then the file itself) →
  outcome. Two bugs hit live during this run (both fixed, both now
  covered by regression coverage -- see below).
- Assumptions / deviations:
  - Feature-loss detection is **observed** (before/after raw zip diff on
    the actual file), not predicted from openpyxl's documented
    limitations -- deliberate per the plan (§6b), and validated by
    injecting real zip members into synthetic fixtures and confirming
    openpyxl actually drops them on its own save (it does, for every
    category tested).
  - Extended (`x14`-namespaced) conditional formatting/data validation is
    detected via a substring match on the worksheet XML, not a full
    parse -- a deliberately blunt, conservative instrument (some false
    positives possible, no false negatives expected for this marker).
  - Eligibility is all-or-nothing per settlement: if even one line traces
    to a different import batch (or none), original-workbook export is
    refused entirely for the *whole* settlement, not attempted line-by-
    line -- "the client's original workbook" is singular by construction.
- Known gaps: none carried forward from this phase specifically (D3 was
  the last piece the D2 groundwork was waiting on).
- Pre-existing bugs found and fixed while building this phase:
  1. (Caught by a test, before merge) `_run_original_export` read
     `line.source_row_number` off `BidSettlementLineItem` -- but that
     column lives on `BoqLineItem`, not the settlement line at all;
     `BidSettlementLineItem` has no such attribute. Fixed to look it up
     via the already-loaded `boq_items` map.
  2. (Hit live during the dev-stack run, before merge) the CLI's D1-SIM
     workbook fixture put a merged title in row 1 but the import mapping
     didn't set `header_row=2`, so the parser tried to read the title row
     as headers and both real rows failed validation. Fixed in the CLI
     fixture only -- not a bug in `commit_import`/`parse_boq_file`
     themselves, which handle `header_row` correctly when told about it.

## Phase 4: Module B, remaining takeoff features

**Status:** §4a, §4b, and §4c built, unit+integration-green (308 unit + 136 integration + 18 API = 462 passed; Phase 4 complete). See `docs/module-b-phase4-plan.md` for all three sub-phases' design.

### §4a: PDF vector geometry extraction, DXF dimension harvesting, multi-signal scale fusion, manual calibration history

- Branch: `feat/4a-pdf-geometry-scale` (from `master`).
- Migrations: `0021_pdf_geometry_scale_fusion.py` (`drawing_sheets.scale_disagreement`, `pdf_layer_mapping_rules`, `sheet_scale_calibrations`), `0022_drawing_measurements_delete_roles.py` (widens `drawing_measurements`' DELETE policy -- see bug #3 below).
- New code:
  - `app/takeoff/pdf.py::index_pdf_geometry()` -- harvests lines/rects/curves from a vector PDF via pdfplumber, synthesizing `GeometricEntity.layer` from stroke colour/line width/dash pattern/(best-effort) OCG name through a project-scoped, ordered `PdfLayerMappingRule` set (PDFs have no native layers). Raster pages (same <20-char heuristic `index_pdf()` already used) get an empty entity list, never guessed at.
  - `app/takeoff/dxf.py` -- DIMENSION entities harvested as a scale-detection signal (`defpoint2`/`defpoint3` + `dxf.text`) when the text is an explicit override, not ezdxf's `"<>"` auto-text default (resolving the dimension-style scale factor to use auto-text was deliberately skipped -- logged as a known gap below).
  - `app/takeoff/scale.py` -- multi-signal fusion (`estimate_scale`): annotation-text, DXF-dimension cross-check, vector-space scale-bar detection (baseline + evenly-spaced ticks + arithmetic-sequence numeric text), and a units-based fallback, combined by picking the highest-confidence signal and flagging `scale_disagreement` (never averaging) when two signals both ≥0.5 confidence disagree by more than 10%.
  - `app/takeoff/geometry/units.py::sheet_scale_factor()` -- folds `scale_ratio` into the native-unit-to-metres factor only for PDF's `"pt"` unit (DXF is already true-to-scale via `$INSUNITS`); `alignment.py`/`pipe_network.py`/`volumes.py` switched to it.
  - `app/services/takeoff.py` -- `recompute_sheet_measurements()` (shared by the extraction pipeline and manual calibration), `record_scale_calibration()`/`list_scale_calibrations()`/`revert_scale_calibration()` (append-only history, current-value columns always mirror the latest row), `set_manual_scale()` rewritten for correct pt/DXF unit handling (bug #1 below), `list_pdf_layer_mapping_rules()`/`replace_pdf_layer_mapping_rules()` (whole-set replace).
  - Four new endpoints: `GET`/`POST .../scale-calibrations[/{id}/revert]`, `PUT`/`GET /projects/{id}/pdf-layer-mapping-rules`.
  - `app/cli.py::simulate_takeoff_pdf` / `make dev-simulate-takeoff-pdf` -- uploads a synthetic vector PDF through the real Celery ingest pipeline (`TAKEOFF_PERSIST_GEOMETRY=true`), seeds a PDF layer-mapping rule, waits on the specific extraction jobs this phase touches (not `drawing.status=ready`, which the missing ONNX model -- known gap below -- prevents on this dev machine), then exercises manual calibration + revert with an explicit "exactly one measurement row" assertion at each step (the regression migration 0022 fixes).
- Role gating: all four new endpoints reuse the existing `_UPLOAD_ROLES` tuple (all five tenant roles) already governing every other drawings endpoint -- there is no service-layer `_require_role` check to give a "denied role" test against (unlike e.g. `settlement_service.build_settlement_draft`), and no pre-existing drawings endpoint has a dedicated API-level permission test either. Exercised instead at the service layer under a real (non-system) `estimator` actor with `project_members` membership -- the lowest role `_UPLOAD_ROLES` allows -- per the brief's "lowest allowed role" half of the testing rule. Logged as a known gap rather than fabricated coverage.
- Known gaps:
  1. DXF DIMENSION auto-text (`dxf.text == "<>"`) is never resolved to a measurement -- would need the entity's dimension-style scale factor, deliberately deferred; only an explicit text override is harvested.
  2. PDF OCG (optional-content-group) layer matching is best-effort: most CAD-to-PDF exports don't declare OCGs, and pdfplumber doesn't surface the owning group name on a per-object basis when they do, so `ocg_name_contains` rules silently never match in that case.
  3. In this dev environment the ONNX embedding model (`ai-service/embeddings/download_model.py`, see `docs/deploy-deltas.md`) isn't provisioned, so `embed_drawing` fails and the ingest chord's `finalize_drawing` never runs -- `drawing.status` sticks at `extracting` rather than reaching `ready`. Pre-existing (every prior phase's ingestion had the same exposure; Phase 4a didn't touch `embed_drawing`), not fixed here -- Phase 5 scope.
  4. The real (non-mock) dev-stack `vllm` service did not reliably extract "SCALE: 1:100" title-block text into a usable `scale_text` field during dev-sim verification, so the auto-detected-scale demo in `simulate_takeoff_pdf` shows `ratio=None` for that signal -- consistent with the "Production hardening checklist" note in `docs/deploy-deltas.md` (PDF/LLM extraction only verified against mock-vllm; needs real synthetic-sample testing before production). The scale-fusion *logic* itself is proven correct independently via unit tests (`test_scale_parser.py`) and the manual-calibration path (which doesn't depend on the VLM at all).
- Pre-existing bugs found and fixed while building this phase:
  1. `set_manual_scale`'s ratio computation was semantically inconsistent with `sheet_scale_factor()`'s convention (real metres per *printed/modelled physical* unit): it used the raw two-point pixel/point distance directly. For a DXF sheet this was a no-op (units already physical), but for a PDF sheet (raw distance in points) it would have applied the points-to-metres conversion twice, silently making any calibrated PDF measurement wrong by ~2,835x. Fixed by converting the raw distance through `meters_per_unit(sheet.units)` before dividing. Caught by reasoning through the test math before writing the test, not by a failing test.
  2. `sheet_scale_factor()` did `base * scale_ratio` where `scale_ratio` (a `Numeric(12,6)` column) arrives as a `Decimal` on anything freshly read from the DB -- `float * Decimal` raises `TypeError`. Didn't show up in `set_manual_scale`'s own happy path (its `ratio` is a freshly-computed Python float, never round-tripped through the DB first), only in `revert_scale_calibration` (which restores a `SheetScaleCalibration.ratio` read straight off a DB row). Caught by the integration test suite (`make test-integration`), not unit tests -- unit tests never touch a real Numeric column. Fixed by coercing to `float()` before multiplying.
  3. `drawing_measurements`' DELETE RLS policy (migration 0010) was scoped to `["lead_estimator", "procurement_head", "managing_director"]` on the explicit, previously-true assumption that `recompute_sheet_measurements` only ever ran as a system actor (the Celery extraction task). Phase 4a broke that assumption: `set_manual_scale`/`revert_scale_calibration` call the same function from real request-path actors (any of the five `_UPLOAD_ROLES`, e.g. `estimator`). Under `FORCE ROW LEVEL SECURITY`, a DELETE with no matching policy silently matches zero rows -- so every recalibration by anyone other than `lead_estimator`/`procurement_head`/`managing_director` just ADDED another measurement row instead of replacing the stale one, and `list_measurements()` would non-deterministically return whichever same-kind row its `ORDER BY sheet_id, capability, kind` happened to place first. Not caught by the integration test suite as originally written -- the test that exercised `set_manual_scale` had no pre-existing measurement row to fail to delete, so the bug was invisible there. Only surfaced by running `make dev-simulate-takeoff-pdf` against the real stack (three `alignment_length_m` rows survived one calibrate + one revert, where there should only ever be one) and inspecting `drawing_measurements`/`sheet_scale_calibrations` directly via `psql`. Fixed by migration 0022 (widens `DELETE_ROLES` to match `WRITE_ROLES`) and the integration test was strengthened to seed a pre-existing system-actor measurement first and assert exactly one row survives two estimator-driven recomputes, so this class of bug can't regress silently again.

### §4b: non-destructive measurement overrides, split-pane traceability, trade classification

- Branch: `feat/4b-overrides-traceability-trade` (from `master`).
- Migration: `0023_measurement_overrides_trade_classification.py` -- `drawing_measurement_overrides` (partial unique index enforcing "at most one active row per measurement", same technique as `bid_settlements`' one-current-version index), `drawing_measurements.trade_node_id`/`bbox_min_x/min_y/max_x/max_y`, `drawing_layer_trade_mappings` (config CRUD, `lead_estimator+` write policy matching `boq_tolerances`' own precedent, not the operational `estimator+` tier overrides use).
- New code:
  - `app/models/takeoff.py::DrawingMeasurement.effective_value` -- the active override's value if one exists, else the raw extractor value; `app/boq/reconciliation.py`'s consumer (`app/services/boq.py::_apply_reconciliation`) now sums this instead of `value`, so an override genuinely changes BOQ reconciliation -- the one behavioural ripple the plan doc called out.
  - `app/services/takeoff.py::override_measurement()`/`revert_measurement_override()` -- setting a new override while one is active auto-supersedes it (old row's `reverted_at` set in the same transaction, never deleted -- it's the audit trail) rather than requiring an explicit revert first; a note is required ("why", not just "what"), enforced at the service layer, not just the schema.
  - `recompute_sheet_measurements()` extended to resolve `trade_node_id` (first `drawing_layer_trade_mappings` pattern matching any source entity's layer wins, case-insensitive substring, same convention as `AlignmentConfig.layer_hints`) and a denormalized bbox (union of source entities' own boxes) per measurement.
  - `list_drawing_entities_in_region()` -- bbox-*intersection* query (not containment) for the split-pane traceability view.
  - `app/services/boq.py::list_unlinked_measurements()` gained the `trade_node_id` filter its own docstring had named as a real gap before this phase (it had nothing to filter on -- it does now).
  - Six new endpoints: `POST /drawing-measurements/{id}/override[/revert]`, `GET /drawing-sheets/{id}/entities` (bbox query params), `PUT`/`GET /projects/{id}/drawing-layer-trade-mappings`; `GET /projects/{id}/measurements:unlinked` gained a `trade_node_id` query param.
  - `app/cli.py::simulate_takeoff_pdf` extended (same command as §4a, not a new one) to seed a trade mapping, confirm classification resolves, set + revert an override, and query the traceability endpoint against the same synthetic drawing.
- Deliberate deviation from the plan doc: no `source_sheet_id` column was added to `drawing_measurements` -- the plan named one for the traceability view, but `drawing_measurements.sheet_id` (pre-existing) already is exactly "which sheet this measurement's source geometry lives on" (every extractor computes one measurement per sheet already), so a second FK would have been purely redundant.
- Deliberate design choice, not a bug: an override does **not** survive a `recompute_sheet_measurements()` call (scale recalibration, re-extraction) -- the measurement row it points at is deleted and recreated (`ON DELETE CASCADE` on `measurement_id`), so the override goes with it. A stale manual number silently surviving an underlying geometry/scale change seemed worse than requiring the estimator to re-review and re-override; covered by `test_recompute_clears_a_stale_override_rather_than_keeping_it`.
- Role gating: `drawing-measurements/.../override[/revert]` reuses `_UPLOAD_ROLES` (all five tenant roles, same reasoning/gap as §4a's endpoints -- no service-layer check, no dedicated API-level permission test for this pre-existing pattern). `drawing-layer-trade-mappings` is narrower (`lead_estimator+`, matching `boq_tolerances`): tested directly, since here RLS *does* genuinely deny a plain `estimator` -- confirmed as a raw `sqlalchemy.exc.ProgrammingError` (asyncpg's `InsufficientPrivilegeError`, translated), not a clean `ForbiddenError`, since there's no service-layer check to raise one (same as `boq_service.set_tolerance`, the existing precedent this mirrors).
- Known gap: no unit tests for `_resolve_trade_node_id`/`_union_bbox` (the two new pure helpers in `app/services/takeoff.py`) -- covered instead at integration level through `recompute_sheet_measurements`, consistent with the rest of that module's own service-layer functions (none of which have unit tests either; they all need a DB/RLS context).
- Pre-existing bug found and fixed while building this phase: none new -- one real bug was found and fixed *within this phase's own new code* before it ever reached a passing state (not "pre-existing"): `revert_measurement_override()` initially tried `session.expire(measurement, ["override"])` followed by a bare synchronous `.override` attribute access in a test, which raised `sqlalchemy.exc.MissingGreenlet` -- async SQLAlchemy can't implicitly re-run a lazy/joined load outside an active awaited call. Fixed by expiring the relationship and then immediately re-fetching the measurement through a fresh awaited `select()` (whose own JOIN repopulates the expired attribute as part of that same awaited call), never touching `.override` synchronously after an expire with no intervening `await`.

### §4c: clustered typology recognition

- Branch: `feat/4c-typology-clustering` (from `master`).
- Migration: `0024_typology_clusters.py` -- `typology_clusters`, `typology_cluster_instances`, `typology_variant_deltas` (config-CRUD write policy, `lead_estimator+`, matching `boq_tolerances`/`drawing_layer_trade_mappings`).
- New code:
  - `app/takeoff/typology.py` (pure) -- two independent detection strategies. **DXF**: instances of the same block reference are trivially the same unit regardless of placement/rotation, so grouping is by `GeometricEntity.block_name` directly; a geometric signature (bbox aspect ratio, entity count, total edge length) is a cross-*drawing* consistency check (block names are only unique within one DXF file, so the same name in two different uploaded drawings could mean genuinely different geometry), not the primary key. **PDF**: no block concept exists, so entities are clustered into spatially separate "regions" by bbox proximity (`cluster_by_proximity`, per sheet -- sheets have independent coordinate spaces), each region's vertices centroid-translated and rounded to a self-scaling tolerance grid, then hashed (`normalized_geometry_hash`); matching hashes across sheets become one cluster. Deliberately translation-only, not rotation-invariant, matching the plan doc's literal scope.
  - `app/takeoff/dxf.py::_block_signature_attributes()` -- computes the signature once per distinct `block_name` from the block *definition*'s own local geometry (`doc.blocks[block_name]`), not from any one INSERT's placed/transformed content -- see bug #1 below for why that distinction mattered.
  - `app/services/typology.py` -- `detect_clusters()` (idempotent: re-running never creates a duplicate proposal for the same `(project, detection_method, detection_key)`; a previously-*rejected* key does NOT block a fresh proposal, a deliberate default), `confirm_cluster()` (the estimator partitions a cluster's detected handles into 1+ labeled groups -- e.g. splitting 2 of 12 detected instances into a "type B" variant -- picks the master, records deltas; replaces the auto-detected single instance row with this partition), `reject_cluster()`, `get_rollup()`.
  - Eight new endpoints under `/typology-clusters` and `/projects/{id}/typology-clusters[/detect]`.
  - `app/cli.py::simulate_typology_pdf` / `make dev-simulate-typology-pdf` -- a real 2-sheet PDF (2 copies of one shape on sheet 1 + a distractor, 1 more copy on sheet 2) through the real Celery pipeline, confirming detection finds exactly the 3 matching instances across both sheets, re-detect is idempotent, confirm succeeds, and the rollup endpoint responds (with an empty `items` list, since no BOQ items are linked in this simulation -- the full rollup arithmetic is integration-tested instead).
- Design decisions the plan doc left for this phase to make (defaults, not literal spec):
  - `typology_cluster_instances` is one row per **group** (e.g. "type A"), not one row per raw detected repeat -- `instance_count` is the group's total repeat count, `source_handles` (JSONB) is the full traceability list of every repeat's own handle, and `sheet_id`/`bbox_*` give ONE representative repeat's location for the split pane. Matches the plan doc's own "instance_count ... a whole group, not per-instance-row" note, read literally.
  - Rollup scoping ("which BOQ items belong to the master") is resolved **spatially on read**, not via a new join table: any `BoqLineItem` linked (`BoqLineItemMeasurement`) to a `DrawingMeasurement` whose bbox (Phase 4b) is fully contained within the master instance's own bbox is in scope. Ties Phase 4b's bbox columns directly into Phase 4c's rollup rather than inventing new storage for "which items are the master's."
  - `master_instance_id` on `typology_clusters` is a nullable FK to `typology_cluster_instances.id`, set only after that row exists (the two tables reference each other) -- create cluster, create instance(s), then `UPDATE` the cluster with the pointer, same two-step pattern as any circular-FK relationship.
- Known gaps (explicitly out of scope per the plan doc, or narrowed further here):
  1. PDF geometry-hash matching is translation-only, never rotation-invariant -- two copies of the same unit drawn at different rotation angles on a PDF sheet will hash differently and will NOT be detected as the same cluster. Real rotation-invariant hashing (PCA alignment or a rotation search) is a materially harder problem, explicitly out of scope for this first bounded implementation.
  2. The DXF geometric-signature outlier check no longer catches a *non-uniformly-scaled* instance of the same block_name (see bug #1 below) -- an accepted simplification once the signature moved to the block definition's own local geometry; every instance sharing a block_name is now trivially treated as matching, which is correct for the overwhelmingly common case and far more robust against rotation than the per-instance alternative would have been.
  3. Raster (scanned) scale-bar/typology detection is out of scope, same as Phase 4a's own scale-bar detection -- vector geometry only.
  4. Role gating for `/typology-clusters/...` reuses the same pattern as `drawing-layer-trade-mappings` (§4b): no service-layer `_require_role` check, RLS alone enforces `lead_estimator+`, confirmed via a raw `ProgrammingError` in the integration suite, not a dedicated API-level permission test.
- Pre-existing bugs found and fixed while building this phase (both found and fixed before this phase's own code ever reached a passing state -- neither is "pre-existing" in the sense of predating this phase, but both are documented per the brief's own "bugs found" category since neither was caught by writing the test first):
  1. **Scale-invariance self-cancellation in `normalized_geometry_hash`.** Rounding vertices to a grid sized as a percentage of the *same region's own* bounding-box diagonal is, by construction, scale-invariant: for any two similar shapes, `corner / grid` reduces to the identical constant regardless of absolute size (verified: a 10x10 and a 6x6 square hashed identically). Caught by a unit test that expected them to differ. Fixed by adding a log-scale "size bucket" (`round(log(diagonal) / log1p(tolerance_pct/100))`) to the hash payload, which reintroduces absolute-scale sensitivity without losing the intended small-noise tolerance (logging, not dividing by a self-derived value, is what avoids the cancellation).
  2. **Rotation broke DXF block-instance matching.** The original design computed each INSERT's signature from its own world-transformed content (`ezdxf.Insert.virtual_entities()`), which is correct for `entity_count`/`total_edge_length` (rotation-invariant) but NOT for `bbox_aspect_ratio` (a 10x5 rectangle rotated 90° has a 5x10 axis-aligned bbox) -- exactly the "differing only by placement (position/rotation) still match" case the plan doc requires. Caught while writing the DXF fixture test (reasoned through before it ever ran, not from a failing assertion): a rotated placement of the identical block would have been wrongly split into its own outlier group. Fixed by computing the signature once per `block_name` from the block *definition*'s own local (untransformed) geometry instead of any instance's placed content -- rotation-invariant by construction, at the cost of no longer catching non-uniform-scale outliers (known gap #2 above).
  3. **`simulate_typology_pdf` broke on a second run against the same dev database.** `detect_clusters()` is (correctly) project-wide, and this simulation re-uploads the identical fixture geometry every invocation against the shared, never-reset demo project -- so a second run's 40x40 "distractor" rectangle legitimately repeats too (one per prior run) and `detect_clusters()` correctly proposes it as its own separate, valid cluster. The script originally assumed "whichever cluster `detect_clusters` just created is the one we want" and picked up this unrelated distractor cluster instead, failing an `instance_count == 3` assertion meant for the real unit shape. Not a bug in `detect_clusters`/`normalized_geometry_hash` at all -- verified by replicating the exact query+grouping logic standalone (`num_regions=6` for the real shape across two runs' worth of drawings, `num_regions=2` for the now-twice-repeated distractor, both legitimately ≥2). Fixed in the CLI script only: disambiguate by `instance_count == 3` (this fixture's own known shape) across every `pdf_geometry_hash` cluster the project has, not by recency.

## Phase 5: semantic matching (B and C)

**Status:** built, unit+integration-green (315 unit + 142 integration + 18 API = 475 passed; merged to master). See `docs/module-b-c-phase5-plan.md` for the design.

- Branch: `feat/5-semantic-matching` (from `master`).
- Migration `0025_semantic_matching.py`: `boq_line_items.description_embedding`, `drawing_measurements.descriptor_embedding`, `quotation_line_items.description_embedding` (all nullable `vector(384)` + HNSW, same technique as migration 0009's `sheet_chunks.embedding`); `semantic_match_feedback` (RLS-forced, project-scoped).
- New code:
  - `app.integrations.embeddings::embed_best_effort()` -- the degradation contract every write path here uses: catches `FileNotFoundError` (ONNX model not provisioned) and returns `None`, never raises; any other exception still propagates.
  - `app/services/semantic_matching.py` -- `combine_scores()` (`0.6*fuzzy + 0.4*semantic`, or fuzzy alone with no embedding), `suggest_measurements_for_boq_line()`, `suggest_boq_for_quotation_line()` (scoped to the quote's own package via the existing `list_package_boq_items`), `record_feedback()`, and the RAG re-ranking (`_rag_adjustment`, ±0.05 max, nearest-neighbor **per candidate**, not global -- see bug #1 below).
  - Write-path wiring: `boq_service.create_line_item()`, `takeoff_service.recompute_sheet_measurements()` (batched per sheet, computing each measurement's synthesized descriptor via `build_measurement_descriptor()`), and both quotation-line creation sites in `app/workers/tasks/quotation_ingestion.py` (batched per ingestion pass via a new `_embed_quotation_line_items_best_effort()` helper).
  - Three new endpoints: `GET /boq-line-items/{id}/measurement-suggestions`, `GET /quotation-line-items/{id}/boq-suggestions`, `POST /semantic-matching/feedback`.
  - `make download-embedding-model` -- the documented make target the brief asked for (exports via `ai-service/embeddings/download_model.py`, copies into the `deploy_onnxmodels` named volume in one step); `docs/deploy-deltas.md` updated to lead with it, keeping the existing manual/air-gapped procedure as the alternative.
  - `app/cli.py::simulate_semantic_matching` / `make dev-simulate-semantic-matching` -- probes whether the real ONNX model is available and prints which path (full or degraded) it's about to exercise, seeds a BOQ line item + two takeoff measurements, shows suggestion ranking, and (only when an embedding exists) records feedback and shows the resulting rank shift.
- Deliberate deviation from the plan doc: BOQ line item embeddings are **not** batched across a whole `commit_import()` (bulk BOQ import) call -- the plan doc's §7 said they would be. `commit_import()`'s existing topological (parent-before-child) creation loop calls `boq_service.create_line_item()` once per row for correctness reasons unrelated to this phase (a row's `parent_id` must already exist as a real DB row), and `create_line_item()` embeds its own row inline -- restructuring that loop to batch embeddings across the whole import felt like a bigger, riskier change to a working, well-tested function than this phase's scope justified. Each row still gets exactly one local ONNX inference call, consistent with that loop's existing per-row DB-round-trip profile; only `recompute_sheet_measurements()` (one sheet's worth of measurements) and the two quotation-line creation sites (one ingestion pass's worth of lines) are genuinely batched, matching the plan doc there.
- Role gating: suggestion endpoints are read-only (`CurrentUser`, RLS-scoped) -- same "no service-layer role check, RLS project-visibility is the real gate" pattern as every other Module B/C Phase 4 read endpoint; a non-member gets `NotFoundError` (the row is invisible under RLS), not `ForbiddenError`, matching every other project-scoped read in this codebase. The feedback endpoint reuses the operational `estimator+` tier (all five tenant roles, migration 0025's `FEEDBACK_WRITE_ROLES`) -- tested at that lowest allowed role plus the same RLS-invisibility denial for a non-member.
- Known gaps (from the plan doc, confirmed unchanged): no cross-tenant learning (RLS-scoped by construction); RAG re-ranking is a single nearest-neighbor lookup per candidate, not a proper k-NN-weighted vote; `EMBEDDING_BACKEND=vllm` isn't specifically exercised by `embed_best_effort`'s own tests (only `OnnxEmbedder`'s `FileNotFoundError` is guarded against). This dev machine has no ONNX model provisioned, so `make dev-simulate-semantic-matching` only ever demonstrated the degraded (fuzzy-only) path live -- the "with embeddings" path (ranking, RAG re-ranking) is proven instead by `tests/integration/test_semantic_matching.py`'s six tests against a deterministic fixture embedder, same posture as Phase 4a's own VLM-reliability note.
- Pre-existing bugs found and fixed while building this phase (both found and fixed before this phase's own code ever reached a passing state, per the same "documented either way" convention Phase 4c established):
  1. **`_rag_adjustment`'s nearest-neighbor lookup was scoped to (project, match_type) only, not per candidate.** When two candidates being ranked in the same suggestion call had received feedback with near-identical query embeddings (e.g. the same BOQ line got one candidate accepted and a different candidate rejected in two rounds), the unscoped "single globally nearest feedback row" lookup returned the SAME row for every candidate in that call -- so only the one candidate whose id happened to match that single nearest row got any adjustment at all; every other candidate silently got `rag_adjustment=0.0`, even when a clear rejection precedent existed for it too. Caught by `test_feedback_shifts_a_subsequent_suggestions_ranking` (an accepted candidate correctly went positive; the deliberately-tied rejected candidate wrongly stayed at exactly `0.0` instead of going negative). Fixed by adding `target_id == :target_id` to the nearest-neighbor query itself, so each candidate looks up its OWN nearest precedent, not the single nearest precedent across all candidates.

## Phase 6: Module C, remaining procurement features

**Status:** built, unit+integration-green (333 unit + 151 integration + 18 API = 502 passed; merged to master). See `docs/module-c-phase6-plan.md` for the design, including its §0 audit of what already existed before this phase (per-line arithmetic verification, currency capture, exclusion detection with a verbatim quote citation -- all pre-existing; only the pieces named below were actually missing).

- Branch: `feat/6-procurement-completion` (from `master`).
- Migration `0026_procurement_completion.py`: `projects.emirate/area/latitude/longitude`; `vendor_service_regions` (RLS-forced); `quotations.stated_total/total_mismatch/fx_rate_to_base/fx_rate_date`; `quotation_line_items.vendor_uom/uom_mismatch`; `quotation_exclusion_flags.source_location/citation_verified`.
- New code:
  - **Geography**: `app/services/procurement.py::_vendor_geography_eligible()` (project emirate vs vendor `vendor_service_regions`, "nothing to filter on" when either side is unset -- never a silent guess) folded into the existing `_vendor_eligibility()` alongside prequalification; `create_rfqs()`'s existing override mechanism (`_DISPATCH_ROLES` = `procurement_head+`, `override_reason` required, audited) reused as-is, extended to also gate on geography -- no new override mechanism invented. `vendors_service.list_service_regions()`/`replace_service_regions()` (whole-set replace), `projects_service.update_location()`.
  - **Arithmetic verification (subtotals)**: `app/procurement/quotation_verification.py::check_total_mismatch()` (pure) -- LLM path only; the deterministic pricing-sheet template has no independent grand-total cell to check against, so `stated_total`/`total_mismatch` stay NULL/false for every deterministic-path quotation.
  - **Unit conversion**: `quotation_verification.py::resolve_quantity_comparison()` (pure) -- converts through `app.boq.units` when the vendor's stated unit and the matched BOQ item's unit are convertible-but-differently-spelled (e.g. "CUM" vs "m3"); sets the new `uom_mismatch` flag (not `quantity_mismatch`) when they're genuinely different dimensions (e.g. "M" vs "M2") -- a category error, not a "numbers don't match" case.
  - **Currency normalisation with recorded FX**: `quotation_service.set_quotation_fx_rate()` (bid-leveling-stage, `procurement_head+`, audited) -- deliberately separate from `BidSettlementLineItem.fx_rate`'s own acceptance-stage rate (Module D1, migration 0019); `get_bid_leveling_matrix()`'s `BidLevelingCell` gains `normalized_unit_price` (shown alongside the raw `unit_price`/`currency`, never replacing them -- no rate recorded means `None`). New `get_quotation_totals()` + its own endpoint (additive, not a breaking change to the existing bid-leveling response shape).
  - **Exclusion citations**: `ExtractedExclusion`/`QuotationExclusionFlag` gain `source_location` (a page marker for PDF/image, or a `Sheet!rowN` marker for a spreadsheet dump -- `pricing_sheet_parser.py::dump_workbook_text()` now prefixes every row with one); `quotation_verification.py::verify_citation()` (pure) deterministically substring-searches the citation against the actual text sent to the model and sets `citation_verified` -- never trusted from the model's own say-so. A citation that fails to verify is kept, not dropped (it might still be real, e.g. from an image with no text layer at all), just flagged for closer review.
  - Six new/changed endpoints: `PUT`/`GET /vendors/{id}/service-regions`, `PATCH /projects/{id}/location`, `PATCH /quotations/{id}/fx-rate`, `GET /procurement-packages/{id}/quotation-totals`, plus additive fields on the existing bid-leveling and `MatchedVendorOut` responses.
- Role gating: service-region write and project-location update reuse existing tiers (`lead_estimator+` matching `vendors`' own WRITE_ROLES; `bd_director+` matching project creation) rather than inventing new ones. Geography-override denial tested at `lead_estimator` (the lowest role that can otherwise create an RFQ at all) vs `procurement_head` (the override tier) -- mirrors the pre-existing prequalification-override test shape exactly. FX-rate recording tested at `lead_estimator` (denied) vs `procurement_head` (the review-authority tier, same as `resolve_currency_and_vat`).
- Known gaps:
  1. Live dev-stack verification (`make dev-simulate-quotes`, extended with a new scenario (g) exercising a unit conversion + subtotal mismatch + exclusion citation together) could not confirm real-model extraction QUALITY for the three new LLM-schema fields: this dev machine's real local `vllm` returned zero line items (`status=extraction_empty`) for **every** PDF-based scenario in the simulation, including the two pre-existing ones (b, e) that predate this phase -- a longstanding, already-documented limitation (the "Production hardening checklist" note in `docs/deploy-deltas.md` from the very start of this build), not something Phase 6 introduced or could fix here. The actual downstream wiring (subtotal check, unit conversion, citation verification) IS proven correct against the real `_extract_quotation_body` code path via `test_extract_quotation_body_wires_subtotal_unit_and_citation_verification` (monkeypatched `extract_quotation`, deterministic controlled output) -- what's unverified is specifically the real model's ability to populate `vendor_uom`/`stated_total`/`source_location` accurately from an actual document, which needs the same real-vision-model testing the checklist already calls for before production.
  2. No geocoding integration (project/vendor addresses to lat/lng) -- the coordinate columns exist for manual entry (or a later phase), no external geocoding API call was added, per the standing no-external-calls constraint.
  3. No live FX-rate feed -- `fx_rate_to_base` is always manually recorded, per the standing "no auto-conversion" rule.
- Pre-existing bug found and fixed while building this phase: none -- the deterministic pricing-sheet template genuinely has no grand-total cell (confirmed by reading `app/procurement/pricing_sheet.py` before assuming one existed, which corrected this phase's own plan doc's initial wrong assumption that `stated_total` would apply to the deterministic path too -- caught before any code was written, not a runtime bug).

## Phase 7: Module E schema readiness

**Status:** not started

## Phase 8: frontend

**Status:** not started

## Phase 9: end-to-end and wrap-up

**Status:** not started
