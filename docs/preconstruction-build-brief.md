# Est Build: Pre-Construction Build Brief (all remaining building)

You are continuing the Est Build platform (`INSTALLTEC/RFP/2026/PCP-01`). Read `MASTER_SRS.MD`, `README.md` and every file in `docs/` before starting. This brief covers **all remaining pre-construction building work** in one programme: Module D, the rest of Modules B and C, Module E schema readiness, and the frontend. Security hardening, the real-GPU accuracy run and Contabo deployment are **out of scope**. They come after this.

---

## 0. How to run this programme

### 0.1 Autonomy (this replaces the "wait for OK" rule for this programme only)
- For each phase, write a short plan to `docs/<phase>-plan.md`: what you'll build, every default the SRS doesn't specify and the value you picked, and the risks. Commit it, then **build straight away without waiting for approval**.
- **Stop and ask only** when:
  (a) an action is destructive or irreversible (dropping or rewriting existing data or migrations, force-push, deleting tracked files you didn't create);
  (b) a change would need an edit to `deploy/.env` other than appending missing keys from `.env.example`;
  (c) a change would weaken RLS, auth, MFA step-up, audit, or the rule that AI output is only ever a proposal;
  (d) a dependency has a copyleft or commercial licence (AGPL, GPL, SSPL, BUSL, AG Grid Enterprise, PyMuPDF). Use MIT, BSD or Apache alternatives;
  (e) an SRS requirement genuinely conflicts with a decision recorded below.
  In every other case, pick the conservative default, record it in the phase plan, and keep going.

### 0.2 Resumability (your context will be compacted, so keep this current)
- Keep `docs/build-log.md` up to date: one section per phase with status (not started, in progress, built, unit-green), commits, migrations added, assumptions, deviations, known gaps, and **pre-existing bugs found (kept separate from new work)**.
- **If you are resuming, read `docs/build-log.md` first** and continue from the first phase that isn't unit-green.

### 0.3 Git
- One branch per phase from `master` (`feat/d1-settlement`, `feat/d2-export`, …). One commit per logical change, conventional commits.
- When a phase is unit-green, merge it into `master` with `--no-ff`. **Never push.** Renaming to `main` happens later, at push time.
- Always use `git --no-optional-locks` for read-only commands (status, log, diff).
- Never commit `deploy/.env`, the rendered `deploy/seaweedfs/s3-identities.json`, `.dev-token` or any secret. Never print secrets.

### 0.4 Testing while building
- Write tests alongside the code: unit tests for all pure logic, and integration tests for every endpoint and RLS policy.
- **Permission rule:** every permission gets an integration test for the **lowest allowed role** and at least one **denied role**.
- Run `make test-unit` at the end of each phase and fix failures before merging. Run `make test-integration` yourself if it works in your environment; if it doesn't, say so in the log and move on. **The user's full run at the end is the real sign-off.**
- Never weaken RLS, skip, or `xfail` a test to get green. Fix the code, or log the failure as a known gap.

### 0.5 Standing constraints (from the SRS and past decisions)
- No external AI or cloud calls, telemetry, CDNs or web fonts. The whole stack must work air-gapped. AI goes only through the in-stack vLLM (currently mock) and ONNX.
- AI output is a **proposal**. It never triggers an action, a status change or a link without a human accepting it. Guided or strict JSON schemas carry no action fields. Keep the prompt-injection boundary tests.
- Every new tenant-scoped table gets RLS `FORCE`d, with policies that follow the existing pattern, plus an isolation test.
- All state changes, approvals **and exports** write audit events through the existing hash-chained audit trail.
- Money is `Decimal`, never float. Currency defaults to AED; different currencies are never merged without a recorded FX rate.
- Configurable values live in the DB or in config classes with audited changes. Don't hard-code them.
- Non-production environments fail closed for email and IMAP (the existing redirect guard stays).
- Git Bash: any script that calls `docker exec` with absolute container paths needs `MSYS_NO_PATHCONV=1`.
- There are stray directories named `backend;C` and `ai-service;C` in the repo root, probably from Git Bash path conversion. Check what's in them, record it in the log, and don't delete them. The user will decide.

---

## Phase 1: D1, bid settlement and margin simulation
Build from `docs/module-d1-plan.md`, **with these corrections applied to the plan first**:
1. **Rates are authoritative.** Remove the "residual on the largest line" design (`extended_sell_amount` / per-line `rounding_adjustment`). Round `unit_sell_rate` to 2 dp. Each `line_amount` is exactly `unit_sell_rate × qty`, at 2 dp. `tender_total = Σ line_amount`. Approval routing uses `tender_total`. Store a settlement-level `rounding_difference = tender_total − exact unrounded model total`. Recompute and document the 3-line worked example under this rule.
2. **Segregation of duties:** the submitter can never approve their own settlement. If the approval engine doesn't enforce this generally, enforce it in the engine, so `cost_rate_change` is covered too, and log it as a pre-existing gap.
3. **Statuses:** draft → submitted → approved | rejected → won | lost. Export only from approved. Document each transition and the role it needs.
4. **At submit**, compare quantities with the current BOQ (addenda). If anything differs, block and return the differing lines. Add an audited "refresh quantities" action, and define what happens to line overrides.
5. **Approval policy `bid_settlement`:** managing_director if sell_total > AED 2,000,000 **or** margin-on-sell < 8%; otherwise bd_director. MFA step-up is inherited. "Margin" input means markup on cost (`markup_pct`); margin on sell is always shown too.
6. **Boundary tests:** exactly 2,000,000.00 and 2,000,000.01; margin-on-sell exactly 8.00% and just below; a zero total; negative markup (routes to MD).
- Percentages resolve in this order: line override, then trade override, then project default (plant, overhead, volatility per trade, markup). Cost sources: an accepted quote line, a cost-library rate as of a date (`costlib.get_rate_as_of`), or manual entry (who and why). A reviewer must record FX. Simulation is stateless with optional saved scenarios. Settlements are versioned and snapshotted on submit.
- Deliver a dev simulation command, `make dev-simulate-settlement`.

## Phase 2: D2, client BOQ export (generated) and win/loss
- **At BOQ import (Module B):** keep the original workbook in S3 and record the sheet and cell coordinates of each row (description, unit, qty, rate and amount cells). Backfill is not possible for existing imports; mark them `source_workbook = null`.
- **Generated export:** a fresh .xlsx with the client's hierarchy and item numbers, pre-VAT line rates and amounts, and an optional 5% VAT summary line. Export only from an approved settlement. The export is audited (who, when, settlement version, file sha256).
- **Leak test:** no cost, markup, margin, overhead, source, vendor or FX data anywhere in the file. That includes hidden sheets, hidden rows and columns, comments, defined names, document properties and custom XML.
- **Win/loss:** outcome, our price, winning price (optional), competitors (free text plus an optional vendor link), reason codes (a configurable list), date and notes. bd_director+. Audited. Only from approved or submitted settlements; moving to won or lost sets the settlement status.

## Phase 3: D3, export into the client's original workbook (SRS requirement)
- Open the retained original with openpyxl. Reject `.xlsm` and encrypted files. Write **only** the rate cells, and the amount cells when those cells are **not** formulas. Never touch formulas, merged ranges, styles, sheet order, print areas or defined names.
- **Fidelity check:** re-open the output and compare it with the original. Formulas, merged ranges, sheet names and order, and every cell outside the written set must be unchanged. Detect features openpyxl drops (images, charts, some data validation or conditional formatting, pivots, external links) and **report them before download**. If any would be lost, the default is to refuse and offer the generated export, unless the user explicitly accepts the loss (audited).
- The same leak test and audit as D2 apply.
- Tests use synthetic client workbooks with formulas, merged cells, multiple sheets, subtotals and a hidden sheet.

## Phase 4: Module B, remaining takeoff features
1. **Vector PDF geometry extraction** (pdfplumber and pypdfium2, both already dependencies; **no PyMuPDF**). Extract lines, polylines, curves, rects and text with coordinates, plus multi-sheet indexing (sheet number and title per page). Feed them into the existing `GeometryExtractionConfig` pipeline. PDFs have no layers, so map using stroke colour, line width, dash pattern and optional content groups (OCG), all configurable per project. Scanned or raster pages are flagged, never guessed.
2. **Multi-signal scale detection:** scale-bar detection, dimension text against measured length, and scale annotations ("1:500 @ A1"). Combine the signals into a confidence score and flag disagreements. **Manual two-point calibration** API: the estimator picks two points and enters the real distance. It's stored per sheet, audited, and overrides the auto scale, and dependent measurements are recomputed.
3. **Non-destructive estimator overrides:** the original measurement is never changed. Overrides are stored with who, why, the value and a timestamp. The effective value is the override if present. Reconciliation uses the effective value. Overrides can be reverted.
4. **Traceability data for the split pane:** each measurement stores its source sheet, a bounding box or polyline in sheet coordinates, and its confidence. Add an endpoint for the frontend to fetch the geometry of a region.
5. **Trade classification of measurements:** a per-project mapping from layer or style to trade. `measurements:unlinked` gains a trade filter.
6. **Clustered typology recognition:** detect repeating units. For DXF, group by block reference and geometric signature. For PDF, use a normalised geometry hash with tolerance. Clusters are **proposals** until an estimator confirms them. For a confirmed cluster: quantify one master unit in detail, record the instance count, and record **explicit variant deltas** per instance group (for example "type B = type A + 1 maid room"). Totals are master × count + Σ deltas, fully traceable. A change to the master recomputes the cluster.

## Phase 5: semantic matching (B and C)
- Download the ONNX embedding model with `ai-service/embeddings/download_model.py` into the volume, as a documented make target. If the download is blocked, use deterministic fixture embeddings in tests and log it.
- Add pgvector columns and indexes for BOQ line descriptions, measurement descriptors, vendor quote line descriptions and package items.
- **BOQ to takeoff:** suggest candidate links (top-k with scores) combined with the existing fuzzy score. **Suggest-only.** Accepting a suggestion goes through the existing link table and audit.
- **Vendor quote lines to package BOQ:** the same, on top of the C2 rapidfuzz matching.
- **Continuous learning (RAG):** accepted and rejected links are stored as tenant-scoped examples and used to re-rank future suggestions. No model training.
- Everything degrades to fuzzy matching if the model or embeddings are missing.

## Phase 6: Module C, remaining procurement features
1. **Location:** add a project location (emirate and area, optional coordinates) and vendor service regions. Vendor matching adds a geography filter; an override needs procurement_head+, a reason and an audit event, like the existing prequalification override.
2. **Check against the SRS and complete:** arithmetic verification (qty × rate against the stated amount, and subtotals), unit conversion, currency normalisation with recorded FX, and **LLM exclusion detection with explicit source-text citations** (page or cell plus the quoted span), shown as flags in bid leveling. Only build what's missing, and list in the log what already existed.

## Phase 7: Module E schema readiness (schema and design only, no workflows)
- Write `docs/module-e-schema-design.md` first, then the migrations. Cover:
  - carrying a won settlement into a contract (a contract record linked to the settlement snapshot, its BOQ lines and accepted vendor quotes);
  - a live exclusion register seeded from quote exclusion flags;
  - revision and variation comparisons (BOQ and contract revisions with lineage);
  - outturn (actual) cost write-back into the bi-temporal cost library, with provenance.
- RLS on every table. Minimal read endpoints only where needed to prove the model. Check that nothing in D1 or D2 has to be refactored to fit.

## Phase 8: frontend
- `frontend/`: React 18, TypeScript, Vite, Tailwind, **AG Grid Community only**. All assets bundled, with no CDN, no web fonts from the internet and no telemetry. Served by nginx in the compose `frontend` service; **remove the `profiles: ["frontend"]` gate**.
- **Auth, per the SRS (HTTP-only cookies):** a backend-for-frontend flow. The backend handles the Keycloak authorization-code flow with PKCE and sets an encrypted, HTTP-only, SameSite session cookie, with CSRF protection on state-changing requests. Bearer tokens keep working for the API and CLI. **MFA step-up** in the UI: when the API needs a higher `acr`, the UI sends the user through Keycloak step-up and then retries the action.
- **Screens:**
  - projects list and detail;
  - drawing upload and sheet index;
  - takeoff **split pane** (pdf.js for PDFs, server-rendered SVG for DXF, measurements highlighted on the drawing, confidence indicators, overrides, two-point calibration);
  - typology cluster review;
  - BOQ import wizard (mapping, dry run, commit) and reconciliation grid (AG Grid, virtualised, **smooth at 4,200+ rows**, with a performance test on a generated 5,000-line BOQ), link suggestions to accept or reject, unlinked measurements;
  - procurement packages and RFQs (draft, dispatch, resend);
  - quarantine and review queues, quote review and acceptance, version promotion;
  - bid-leveling matrix with exclusion flags and citations;
  - settlement cockpit (live simulation sliders, saved scenarios, submit, approve or reject, SoD shown in the UI);
  - export (generated or original, with the fidelity report);
  - win/loss;
  - admin (taxonomy, approval policies, tolerances, layer and style to trade mapping, reason codes, vendor regions);
  - audit viewer (read-only).
- The UI hides actions the role can't perform, **but the server remains the only enforcement**.
- Tests: vitest for components and logic, plus Playwright smoke tests for login and one happy path per module, using the pre-installed browser. **Don't download browsers.**

## Phase 9: end-to-end and wrap-up
- `make dev-simulate-e2e`: upload a DXF and a vector PDF → takeoff → BOQ import → reconcile → package → RFQ → simulated quotes → accept → level → settle → approve (a different user) → export, both generated and original → win/loss. Use only synthetic data, tagged so it can be cleaned up with a `make dev-clean-demo-data` target that deletes **tagged data only**.
- Write `docs/preconstruction-build-report.md`. Include: what was built per SRS bullet (a traceability table: SRS item → code, tests, doc); all assumptions and invented conventions needing business validation; deviations; known gaps; pre-existing bugs found; migrations list; new `.env.example` keys (and the append command); final unit and integration counts; and the exact commands the user should run to verify.
- Stop there. The user runs `make test-integration` and the e2e simulation, and reviews the report.

---

## Output at the end of each phase
Update `docs/build-log.md`, then print a status block of no more than 10 lines: phase, branch merged, commits, migrations, test counts, assumptions, anything needing the user's decision. Then continue to the next phase.
