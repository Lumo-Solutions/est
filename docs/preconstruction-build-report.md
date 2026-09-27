# Preconstruction Build Report

`INSTALLTEC/RFP/2026/PCP-01`. Covers the programme executed under
`docs/preconstruction-build-brief.md`'s own Phases 1-9 (Module D in
full, the remainder of Modules B and C, Module E schema readiness, the
full frontend, and this end-to-end wrap-up). Module A and the initial
parts of Modules B and C predate this brief entirely -- it says so in
its own opening line ("this brief covers all remaining pre-construction
building work... Module D, the rest of Modules B and C, Module E schema
readiness, and the frontend") -- so this report cites their code
directly rather than inventing a phase history for work this programme
didn't do. `docs/build-log.md` is the authoritative, phase-by-phase
record this report summarizes; read that first for anything not
covered in enough depth here.

## 1. SRS traceability

One row per `MASTER_SRS.MD` §4 bullet. "Pre-existing" means the code
already existed when this brief's Phase 1 started -- verified by
reading the actual files this session, not assumed.

### Module A: Enterprise Data & Governance Core

| SRS item | Code | Tests | Status |
|---|---|---|---|
| Vendor Master & Duplicate Detection | `app/models/vendors.py`, `app/services/vendors.py`, `app/api/v1/routes/vendors.py` (create, duplicate-check/scan/resolve, service regions) | `tests/unit`/`tests/integration` (vendor CRUD, duplicate scoring) | Pre-existing |
| Configurable Trade Taxonomy | `app/models/taxonomy.py` (ltree), `app/services/taxonomy.py`, `app/api/v1/routes/taxonomy.py` (create/list/get/subtree/update/move); admin UI: `frontend/src/features/admin/TaxonomyAdmin.tsx` (Phase 8f) | integration RLS tests; Playwright `admin-audit.spec.ts` | Pre-existing + admin UI in Phase 8f |
| Prequalification & Statutory Register | `app/models/prequal.py`, `app/services/prequal.py`, `app/api/v1/routes/prequal.py` (authorities, certificate types, vendor certificates, decisions) | `tests/integration/test_prequal*.py` | Pre-existing |
| Master Cost Library (bi-temporal, A-10) | `app/models/costlib.py::CostItemRate` (`valid_period`/`sys_period`, `source`/`source_ref`) | `tests/unit`/`tests/integration` for costlib | Pre-existing; confirmed in Phase 7 to already support outturn write-back (`RateSource.OUTTURN`) with zero schema change |
| Approval Workflows & Security (multi-tier routing, MFA, RLS) | `app/models/approvals.py`, `app/services/approvals.py` (`route_tiers`, `decide`, SoD, MFA step-up), `app/api/v1/routes/approvals.py`; admin CRUD for policies added Phase 8f | `tests/unit/test_approval_routing.py`, `tests/integration/test_approval_policies_admin.py` | Pre-existing routing engine; **SoD bug fixed in Phase 1** (see §5); admin CRUD added Phase 8f |
| Immutable Audit Trail (hash-chained) | `app/models/audit.py`, `app/services/audit.py` (`record`, `verify_chain`), `app/api/v1/routes/audit.py` (`/events`, `/verify`) | `tests/integration/test_audit_chain_db.py` | Pre-existing; read-only viewer added Phase 8f (`frontend/src/pages/AuditPage.tsx`) |

### Module B: AI Takeoff & Estimation Engine

| SRS item | Code | Tests | Status |
|---|---|---|---|
| Drawing Ingestion (vector PDF + DXF, multi-sheet indexing) | `app/takeoff/pdf.py`, `app/takeoff/dxf.py`, `app/workers/tasks/takeoff.py` (`index_sheets` etc.) | integration (real Celery pipeline) | Pre-existing; PDF vector-geometry harvesting added Phase 4a |
| Scale & Title Block Extraction, manual two-point fallback | `app/takeoff/scale.py` (multi-signal fusion), `takeoff_service.set_manual_scale`/`record_scale_calibration`/`revert_scale_calibration` | `tests/unit/test_scale_parser.py`, integration | Pre-existing title-block/scale-bar basics; multi-signal fusion, calibration history, revert all added Phase 4a. Frontend: `TakeoffViewerPage`'s `CalibrationPanel` (Phase 8b) |
| Infrastructure Geometry (alignment, corridor, trench, pipe network) | `app/takeoff/geometry/{alignment,corridor,volumes,pipe_network}.py` | `tests/unit/test_dxf_geometry.py`, integration | Pre-existing |
| Clustered Typology Recognition | `app/takeoff/typology.py`, `app/services/typology.py`, `/typology-clusters` routes | `tests/integration/test_typology_clustering.py` | **Built Phase 4c** (DXF block-name + PDF spatial-proximity-hash clustering, confirm/reject/rollup). Frontend: `TypologyPage` (Phase 8c) |
| BOQ Reconciliation & Discrepancy Auditing (semantic RAG) | `app/boq/reconciliation.py`, `app/services/boq.py`, `app/services/semantic_matching.py` | `tests/integration/test_boq_rls.py`, `tests/integration/test_semantic_matching.py` | Pre-existing arithmetic reconciliation; **semantic/RAG suggestion ranking built Phase 5**. Frontend: `BoqReconciliationPage` + suggestion accept/reject (Phase 8c) |
| Visual Traceability & Adjudication (split-pane, confidence, overrides) | `takeoff_service.override_measurement`/`revert_measurement_override`/`list_drawing_entities_in_region`; frontend `TakeoffViewerPage`, `DxfSheetView`, `PdfSheetView`, `MeasurementPanel` | `tests/integration` (overrides, traceability); `dxfGeometry.test.ts`, `confidence.test.ts` | Backend override/traceability built Phase 4b; **entire frontend split-pane viewer built Phase 8b** (client-side DXF-to-SVG conversion, pdf.js for PDF, confidence-band overlay) |

### Module C: AI Procurement & Bid Leveling

| SRS item | Code | Tests | Status |
|---|---|---|---|
| Automated RFQ Generation & Dispatch | `app/services/procurement.py` (`create_package`, `match_vendors`, `create_rfqs`, `dispatch_rfq`/`resend_rfq`) | `tests/integration/test_procurement_dispatch.py` | Pre-existing; geography-based vendor eligibility added Phase 6. Frontend: `ProcurementPackagesPage` (Phase 8d) |
| Email Quotation Ingestion (IMAP, VLM) | `app/workers/tasks/quotation_ingestion.py`, `app/procurement/quotation_extraction.py` | `tests/integration/test_quotation_ingestion*.py` | Pre-existing. Frontend: `QuarantineQueuePage` (Phase 8d) |
| Normalisation & Semantic Mapping (arithmetic, unit, currency, semantic) | `app/procurement/quotation_verification.py` (subtotal/unit-conversion checks, Phase 6), `semantic_matching.py::suggest_boq_for_quotation_line` (Phase 5) | `tests/unit/test_quotation_verification.py`, integration | Pre-existing per-line arithmetic/currency capture; **unit conversion, currency normalisation with recorded FX, exclusion citations built Phase 6**; semantic mapping built Phase 5 |
| Bid Leveling & NLP Exclusion Detection (citations) | `quotation_ingestion_service.get_bid_leveling_matrix`, `list_exclusion_flags` (Phase 8d), `verify_citation` (Phase 6) | `tests/integration/test_procurement_geography_and_verification.py` | Pre-existing exclusion detection with verbatim quote; **citation location + verification, and the list-exclusion-flags read, built Phase 6/8d**. Frontend: `BidLevelingPage` (Phase 8d) |

### Module D: Executive Cockpit & Pricing Engine

| SRS item | Code | Tests | Status |
|---|---|---|---|
| Bid Settlement & Margin Simulation | `app/models/settlement.py`, `app/services/settlement.py` (`build_settlement_draft`, `simulate`, `submit_settlement`, `decide_settlement`) | `tests/integration/test_bid_settlement.py` | **Built Phase 1 (D1)**. Frontend: `SettlementPage` live sliders (Phase 8e) |
| Client BOQ Export (generated + original workbook) | `settlement_service.export_settlement` (D2), `app/boq/original_export.py` + `export_original_settlement`/`preview_original_export` (D3) | `tests/integration/test_bid_settlement_export_outcome.py`, `test_bid_settlement_original_export.py` | **Built Phases 2-3 (D2/D3)**. Frontend: `ExportPage` (Phase 8e) |
| Win/Loss Data Capture | `settlement_service.record_outcome`, `SettlementReasonCode` | `tests/integration/test_bid_settlement_export_outcome.py` | **Built Phase 2 (D2)**; admin CRUD for reason codes added Phase 8f. Frontend: `WinLossPage` (Phase 8e) |

### Module E: Post-Award Contract Management (schema readiness)

| SRS item | Code | Tests | Status |
|---|---|---|---|
| Phase 1 schema readiness (contracts, revisions, exclusion register, outturn write-back-ready) | `app/models/module_e.py`, `app/services/module_e.py` (read-only) | `tests/integration/test_module_e_schema.py` | **Built Phase 7**. Deliberately schema/RLS only, no workflow, per the brief. No frontend screen (not listed in the brief's Phase 8 screen list) |

### Frontend (all screens, Phase 8a-8f)

Every screen in the brief's Phase 8 bullet list is built and routed --
see `docs/build-log.md`'s Phase 8a-8f sections for full detail per
screen. Summary: auth (login/callback/session, 8a), projects +
drawings + takeoff split-pane (8b), typology + BOQ import/reconciliation
(8c), procurement + bid-leveling (8d), settlement + export + win/loss
(8e), admin + audit (8f).

### Phase 9: end-to-end

`make dev-simulate-e2e` (`app/cli.py::simulate_e2e`) exercises the
entire chain for real: upload DXF+PDF -> takeoff -> BOQ import ->
reconcile -> package -> RFQ (real dispatch) -> a real simulated
vendor quote -> accept -> bid-level -> settle (submit, a different
user approves) -> export both ways -> win/loss, against a dedicated,
cleanable project. See `docs/build-log.md`'s Phase 9 section.

## 2. Assumptions and invented conventions needing business validation

Every default the brief itself asked to be recorded, in one place:

- **Percentages are stored as whole percent-numbers** (`10.00` means
  10%), not fractions, across settlement (`plant_pct`, `markup_pct`,
  `margin_on_sell_pct`) and approval-policy tiers (`max_margin_pct`).
- **A BOQ line only enters a settlement if `boq_quantity IS NOT NULL`**
  (leaf items only; section/header rows excluded).
- **`margin_on_sell_pct`** is the exact (unrounded) total markup divided
  by the authoritative (rounded) `tender_total` -- a deliberate
  precision-basis choice (`docs/module-d1-plan.md` §4).
- **Export role is `estimator+`** (the settlement's own `approved`
  status gate is the real protection) -- the brief didn't specify a
  role for the export action itself.
- **VAT is entirely opt-in per export call**, never a persisted
  settlement field.
- **`rate_column`/`amount_column`** on a BOQ import are spreadsheet
  column *letters*, unlike every other `*_column` mapping field (header
  *text*) -- deliberate, since these two only exist so a later
  settlement export can compute an exact cell reference, never to parse
  a value at import time.
- **Feature-loss detection for the original-workbook export is
  observed** (a real before/after zip diff), not predicted from
  openpyxl's documented limitations.
- **Original-workbook export eligibility is all-or-nothing per
  settlement**: if even one line traces to a different import batch (or
  none), the whole settlement is refused, never attempted line-by-line.
- **Typology instance rows are one per labelled group, not one per raw
  detected repeat** -- `instance_count` is the group total,
  `source_handles` is the full per-repeat traceability list.
- **Typology rollup scoping is resolved spatially on read** (a linked
  measurement's bbox contained within the master instance's own bbox),
  not via a new join table.
- **PDF DXF-typology geometry-hash matching is translation-only, never
  rotation-invariant** -- an explicit, bounded first implementation.
- **Module E's `contract_ref`/`variation_ref` are plain nullable
  columns**, not a trigger-assigned sequence -- no workflow exists yet
  to decide the real numbering convention, and inventing one for a
  schema-only phase would be exactly the kind of speculative feature the
  phase's own "no workflows" scope excludes.
- **Frontend tech defaults** (every one the SRS left open): React 18
  (pinned; npm defaults to 19), Tailwind v4 CSS-first config, TanStack
  Query (no Redux), pdf.js bundled, nginx same-origin reverse proxy for
  `/api/*` (no CORS anywhere), vitest + Playwright (`channel: 'chrome'`,
  never `playwright install`).
- **Approval-policy admin writes are restricted to `managing_director`
  only** (Phase 8f) -- narrower than the usual three-role "structure"
  tier used elsewhere, because this table governs who has authority to
  approve what money; it deliberately matches that table's own
  pre-existing DB-level RLS write-role restriction rather than inventing
  a new tier.

## 3. Deviations from plan docs (caught before or during building, not bugs)

- D1: rates are authoritative (no rounding residual/largest-line
  absorption) -- a correction applied to the plan doc itself before
  building, not a deviation discovered afterward.
- D3: eligibility check is all-or-nothing per settlement (see §2 above).
- Module E: `contract_ref`/`variation_ref` as plain columns, not a
  trigger sequence (see §2 above) -- the plan doc's own phrasing said
  "trigger-assigned"; corrected before writing the migration.
- Phase 4b: no `source_sheet_id` column added -- the pre-existing
  `drawing_measurements.sheet_id` already served that exact purpose; a
  second FK would have been redundant.
- Phase 8b: the parent Phase 8 plan doc assumed a new DXF-to-SVG backend
  endpoint would be needed; corrected in the 8b plan doc's own §0 audit
  -- the existing `GET /drawing-sheets/{id}/entities` endpoint already
  returns everything needed to render client-side.
- Phase 8c: AG Grid's 5,000-row performance test was moved from vitest
  to Playwright -- jsdom has no `ResizeObserver` and no real layout
  engine, so row-virtualisation math can't be exercised there at all.

## 4. Known gaps

Grouped by area; each is also recorded in its own phase's
`docs/build-log.md` section with more detail.

**AI / model quality (environmental, not code):**
- This dev machine has no real GPU / provisioned vLLM model and no
  ONNX embedding model -- every "real model" path (vision-language
  quotation extraction, semantic embeddings) has only ever been proven
  against a mock or a deterministic fixture. The actual extraction
  *wiring* (subtotal check, unit conversion, citation verification,
  suggestion ranking) is proven correct against controlled inputs; real
  model output *quality* is explicitly flagged in `docs/deploy-deltas.md`
  as needing a real-GPU accuracy run before production (out of scope
  for this brief).
- DXF DIMENSION entities using auto-text (`"<>"`) are never resolved to
  a scale signal (only an explicit text override is harvested).
- PDF OCG (optional-content-group) layer matching is best-effort; most
  CAD-to-PDF exports don't declare OCGs at all.
- No geocoding integration (project/vendor lat/lng are manual-entry
  only) and no live FX-rate feed -- both per the standing no-external-
  calls constraint.
- No rotation-invariant typology matching for PDF sheets (translation-
  only).
- No cross-tenant learning for semantic-matching feedback (RLS-scoped
  by construction).

**Frontend:**
- The interactive Keycloak login form cannot be completed live in this
  dev environment -- `start-dev` on plain HTTP marks its own login-flow
  cookies `Secure; SameSite=None`, which browsers correctly refuse to
  send back over HTTP (`docs/keycloak-setup.md`'s "Cookie not found"
  section, found before this brief, unrelated to and not fixed by it).
  Production is unaffected (real TLS via `deploy/docker-compose.prod.yml`'s
  Caddy). Every frontend phase's live verification used a bearer token
  against the real stack plus Playwright with mocked API responses
  instead of a full unauthenticated browser click-through.
- Per-trade and per-line settlement-simulation overrides
  (`SimulateRequest.trade_overrides`/`line_overrides`) are not exposed
  in the cockpit UI, only the four project-default sliders.
- No delete endpoint for saved settlement scenarios (none exists on the
  backend; not invented).
- No visual drag-and-drop taxonomy tree editor (a plain move-by-picking-
  a-new-parent-id form).
- Several admin-adjacent actions (resolve-tenant, dismiss, attach,
  reject, resend) use `window.prompt` for a required note/reason rather
  than a proper modal.
- No frontend for Module E (not in the brief's Phase 8 screen list).

**Phase 9 e2e simulation:**
- `make dev-clean-demo-data` cannot delete the simulated vendor reply's
  `inbound_emails`/`quotation_attachments` rows -- that table has no
  DELETE RLS policy at all (a deliberate append-only quarantine/
  compliance trail). They become orphaned (`rfq_id=NULL`, the same
  `ON DELETE SET NULL` a real deleted RFQ's history gets in production)
  but stay harmless and identifiable.

## 5. Pre-existing bugs found (kept separate from new work, per the brief)

Every one of these predates the commit that fixed it and was found
while building unrelated new work, never assumed from a code read
alone -- each confirmed by a failing test, a live dev-stack run, or (a
few times) careful reasoning through the actual math before writing a
test. Full detail in each phase's `docs/build-log.md` section; summary:

1. **Approval SoD bypass** (Phase 1) -- the generic approval engine let
   the same user who created a request also decide it, for any entity
   type, including the already-shipped `cost_rate_change` policy. Fixed
   generically in `decide()`.
2. **`boq_import_batches` column widths** (Phase 2) -- five `*_column`
   fields declared `String(8)` (sized for a letter) but actually store
   header *text*; any header over 8 characters would fail the INSERT.
   Widened to `String(255)`.
3. **`commit_import`'s `source_row_number` off-by-header-row** (Phase 2)
   -- stamped from the data-relative row number, never adding
   `header_row`, so a D3 cell reference built from it would point one
   row too high.
4. **`_run_original_export` read the wrong table** (Phase 3) --
   `source_row_number` lives on `BoqLineItem`, not
   `BidSettlementLineItem`; caught by a test before merge.
5. **`set_manual_scale`'s unit conversion applied twice for PDF sheets**
   (Phase 4a) -- would have made any calibrated PDF measurement wrong by
   ~2,835x. Caught by reasoning through the math before writing the
   test.
6. **`sheet_scale_factor()` Decimal/float `TypeError`** (Phase 4a) --
   only surfaced via a real DB-round-tripped `Decimal`, not a unit
   test's freshly-computed float.
7. **`drawing_measurements`' DELETE RLS gap** (Phase 4a) -- a real,
   silent-data-corruption-class bug: under `FORCE RLS`, a DELETE with no
   matching policy matches zero rows instead of erroring, so
   recalibration by most roles just accumulated duplicate measurement
   rows instead of replacing the stale one. Found by running the real
   dev-stack simulation and inspecting rows directly via `psql`, not by
   the integration suite as originally written.
8. **`_rag_adjustment` cross-candidate score bleed** (Phase 5) -- a
   nearest-neighbor feedback lookup unscoped by `target_id` let one
   candidate's feedback silently zero out a different candidate's
   adjustment in the same suggestion call.
9. **nginx `Host` header dropped the port** (Phase 8a) -- broke the
   OIDC `redirect_uri`, the first thing to ever actually exercise the
   frontend's same-origin proxy topology.
10. **Backend requested an OIDC scope the realm never defined** (Phase
    8a) -- `scope=openid profile email` against a realm with no
    `profile`/`email` client scopes. **No interactive browser login had
    ever completed successfully before this fix, in any prior phase.**
11. **Presigned drawing-download URLs were never browser-reachable**
    (Phase 8b) -- signed against the internal compose-network hostname;
    the PDF viewer was the first thing to ever try fetching one from
    outside that network.
12. **No endpoint listed a quotation's exclusion flags** (Phase 8d) --
    `acknowledge_exclusion_flag` needed a caller-supplied id, but
    nothing let a reviewer discover which flags existed in the first
    place.
13. **No endpoint listed a project's settlements** (Phase 8e) -- only
    build (create) and get-by-id existed; no way to land on a project
    and discover its settlement history.
14. **Settlement percentage-unit mismatch in the new slider UI** (Phase
    8e) -- the frontend's own new code, not existing backend code, but
    caught the same way: simulating against real seeded data and
    noticing the result was two orders of magnitude off before merging.
15. **Approval policies and settlement reason codes had no admin API at
    all** (Phase 8f) -- real, live-read DB tables with zero create/
    update routes; only `app/cli.py`'s dev-seed had ever written a row.
16. **BOQ import's dot-delimited item-number parent inference** (Phase
    9) -- not a bug in the parser (it's correct for real hierarchical
    BOQs), but a real collision the e2e simulation's own flat item
    numbers hit; documented in §4 above as the reason the simulation
    uses `"1"`/`"2"`, not `"1.0"`/`"2.0"`.

## 6. Migrations (27 total, `backend/app/migrations/versions/`)

| # | File | Introduced |
|---|---|---|
| 0001 | `extensions_and_helpers` | Pre-existing |
| 0002 | `tenancy` | Pre-existing |
| 0003 | `audit` | Pre-existing |
| 0004 | `taxonomy` | Pre-existing |
| 0005 | `vendors` | Pre-existing |
| 0006 | `prequal` | Pre-existing |
| 0007 | `cost_library` | Pre-existing |
| 0008 | `approvals` | Pre-existing |
| 0009 | `takeoff` | Pre-existing |
| 0010 | `drawing_measurements` | Pre-existing |
| 0011 | `boq_reconciliation` | Pre-existing |
| 0012 | `boq_tolerances` | Pre-existing |
| 0013 | `boq_measurement_links` | Pre-existing |
| 0014 | `boq_reconciliation_table` | Pre-existing |
| 0015 | `procurement_packages` | Pre-existing |
| 0016 | `quotation_ingestion` | Pre-existing |
| 0017 | `quotation_submission_grouping` | Pre-existing |
| 0018 | `approval_margin_routing` | Phase 1 (D1) |
| 0019 | `bid_settlements` | Phase 1 (D1) |
| 0020 | `boq_import_retention_winloss` | Phase 2 (D2) |
| 0021 | `pdf_geometry_scale_fusion` | Phase 4a |
| 0022 | `drawing_measurements_delete_roles` | Phase 4a (bugfix, see §5.7) |
| 0023 | `measurement_overrides_trade_classification` | Phase 4b |
| 0024 | `typology_clusters` | Phase 4c |
| 0025 | `semantic_matching` | Phase 5 |
| 0026 | `procurement_completion` | Phase 6 |
| 0027 | `module_e_schema` | Phase 7 |

No migration in Phase 3, 8, or 9 -- D3 needed no schema change, and the
frontend/wrap-up phases only added two Python-level admin endpoints
(Phase 8f) against pre-existing tables.

## 7. New `.env.example` keys

Everything in `deploy/.env.example` beyond `MASTER_SRS.MD` §6's own
four-variable verbatim template (`DATABASE_URL`, `REDIS_URL`,
`VLLM_API_BASE`, `S3_ENDPOINT`) is an addition; `docs/deploy-deltas.md`
is the authoritative, always-current log of every one of them with its
reason. The one key this specific brief's programme added:

- **`S3_PUBLIC_ENDPOINT`** (default `http://localhost:8333`) -- Phase
  8b. `S3_ENDPOINT` only resolves inside the compose network; a
  presigned drawing-download URL handed to a real browser needs a host
  the browser can actually reach. Same internal/public split already
  used for `KEYCLOAK_BASE_URL`/`KEYCLOAK_PUBLIC_URL`.

To sync a `deploy/.env` that predates this key:

```bash
grep -q '^S3_PUBLIC_ENDPOINT=' deploy/.env || \
  echo 'S3_PUBLIC_ENDPOINT=http://localhost:8333' >> deploy/.env
```

## 8. Final test counts

- Backend: **335 unit + 165 integration + 18 API = 518 tests**, all
  passing as of this report.
- Frontend: **21 vitest + 4 Playwright = 25 tests**, all passing.

## 9. Exact commands to verify

```bash
# Backend
make test-unit
make test-integration          # testcontainers; needs Docker
# tests/api (18 tests, not wired into a Makefile target):
export MSYS_NO_PATHCONV=1
docker run --rm \
  -e TESTCONTAINERS_HOST_OVERRIDE=host.docker.internal \
  -v "$(pwd)/backend:/workspace" -v "$(pwd)/ai-service:/ai-service" \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v installtec-test-pip-cache:/root/.cache/pip -w /workspace \
  python:3.12-slim bash -c \
  "apt-get update -qq && apt-get install -y -qq --no-install-recommends build-essential >/dev/null && pip install --quiet -e '.[dev]' && python -m pytest tests/api -q"

# Frontend
cd frontend
npm run build     # tsc -b && vite build
npm run test       # vitest
npm run e2e        # Playwright, real installed Chrome, no download
npm run lint       # oxlint

# Full stack + end-to-end simulation
cd deploy && docker compose up -d --build
make dev-simulate-e2e       # the full lifecycle, real services, ~1-2 min
make dev-clean-demo-data    # removes only what the above created
```

Reviewing this report and the commands above is the final step per the
brief's own Phase 9 close: "Stop there. The user runs `make
test-integration` and the e2e simulation, and reviews the report."
