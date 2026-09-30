# Est Build: External AI Provider + AI-Assisted Verification and Pricing Brief

## 0. Scope change (the owner's decision, recorded)
Until a GPU server runs the in-house model, the platform uses an **external AI API** for classification, document reading, drawing ↔ BOQ verification and pricing assistance.
- This **knowingly reverses** SRS §1.1 ("no calls to external AI APIs") as a **temporary** measure. Record it in `docs/deploy-deltas.md`, `docs/build-log.md` and a new `docs/ai-provider.md`.
- Switching back to the local vLLM later must be **configuration only**, with no code changes.
- The owner will supply the API key and model details **after** the build. Everything must be built and tested without a key, using a mock/recorded provider. Real-key testing comes later with mock cost-library and vendor data.

Same working rules as `docs/finish-brief.md` section A: the main session merges, subagents work in worktrees with file allow-lists, the main session verifies everything, stack-dependent tests run one at a time with `--workers=1`, nobody pushes, and `docs/ai/log.md` is kept current for resuming.

**Order:** if `feat/dwg-conversion` is still in progress, finish and merge it first. Then do Phase 1 onwards.

**Plan first:** write `docs/ai-plan.md` covering the provider design, every AI task (inputs, output schema, what's deterministic and what's AI), data flows, cost controls and defaults. Commit it, then build **without waiting**, except for finish-brief section A's stop conditions.

---

## Phase 1: provider layer (main session: security-sensitive)
1. **One `AIProvider` interface** with these operations:
   - `classify` and `extract_structured`, both JSON-schema-constrained;
   - `vision_extract` (page images and PDF pages);
   - `match_rank` (rank candidates with reasons);
   - `embed` (optional).

   **Implementations:**
   - `local_vllm` (existing, the default when `AI_PROVIDER` is unset);
   - `anthropic` (native Messages API, tool/JSON-schema output, PDF and image input);
   - `openai_compatible` (any OpenAI-style endpoint, `response_format` JSON schema, image input);
   - `mock` (deterministic, fixture-driven, the default for tests).

   Port the existing vLLM callers (C2 quote extraction, intake classification, title block) to this interface, so every AI call goes through one place.
2. **Configuration**, all in `.env.example`; keys are never committed, logged or returned by any API:
   - `AI_PROVIDER` and `AI_MODEL`, plus optional per-task overrides (`AI_MODEL_CLASSIFY`, `AI_MODEL_VISION`, `AI_MODEL_REASONING`);
   - `AI_API_KEY` and `AI_BASE_URL`;
   - `AI_TIMEOUT_S` and `AI_MAX_RETRIES`;
   - `AI_MONTHLY_BUDGET_USD` and `AI_PROJECT_BUDGET_USD`.

   If the provider is external and the key is missing, AI features show "AI not configured" and fall back to rules. Nothing crashes.
3. **Governance (tenant data leaves the boundary, so this is mandatory):**
   - **Admin switch:** a tenant-level "External AI allowed" setting, off by default, that only managing_director can change (audited). An optional per-project override lets a confidential tender be kept off external AI.
   - **Audit every call** in an `ai_calls` table (RLS): task, provider, model, project, the entity it concerns, prompt and response (stored internally for traceability), tokens, cost estimate, latency, status and error. Admins get a usage and cost view.
   - **Budgets:** hard stops at the monthly and per-project caps, with a clear UI message. Rate limiting and retries with backoff.
   - **Cache by (task, input sha256, model, prompt version)**, so re-running the same document costs nothing.
   - **Egress:** only the configured AI host is reachable from the workers that need it. Document it in the deploy docs.
4. **Safety, carried over from C2:**
   - Every document is untrusted input, with a strict boundary between system instructions and document content.
   - Output schemas have **no action fields**, and **AI output is always a proposal**.
   - Prompt-injection tests run for every task.
   - The AI never produces money totals. Every Decimal calculation stays in the existing engines.

## Phase 2: intake and reading (absorbs the pending intake follow-ups)
1. **Folder upload** (drag a folder in, or `webkitdirectory`), with relative paths kept as a classification signal and the same safety limits as zips. After creating a project, land on the Tender documents tab with a clear "Drop the tender package here" empty state.
2. **Classification:** rules first. The AI provider handles only low-confidence or conflicting files, and receives the first pages' text, the title-block region and the folder path. The confirm step stays as it is.
3. **Reading, with the AI assisting deterministic parsing:**
   - **PDF BOQ:** pdfplumber extracts the table first (columns, repeated headers, wrapped descriptions, brought/carried forward lines, collection pages skipped). Pages it can't parse cleanly, and scanned pages, go to `vision_extract` with a strict row schema. Every AI-read row is flagged "AI-read" with its page and region, and goes through the same wizard: mapping, dry-run preview where the user fixes rows, then commit. The original-workbook export isn't available for PDF sources; say so.
   - **Drawings (PDF, DXF or converted DWG):** the AI reads title blocks, legends, the drawing schedule, scale notes and **dimension or quantity annotations** (for example "L=245.0m", "Ø300 uPVC", "12 nos"), each returned with its page and bounding box. Geometry measurement stays deterministic, as it is today.
   - **Vendor quotes** (the C2 AI path) now go through the provider.
4. Per-sheet extraction progress shown in the UI, with links into the takeoff viewer.

## Phase 3: drawing ↔ BOQ quantity verification (the core AI task)
**Goal:** after intake, produce a **verification report** comparing every BOQ line with what the drawings show.
1. **Interpreting the BOQ (AI):** for each BOQ line, the AI interprets the description, extracting the work type, material, size or diameter, unit and trade. It then proposes **which drawing evidence corresponds**: layers or styles, block types, legend symbols, annotated quantities, sheets. It returns a ranked list with reasons.
2. **Quantities (deterministic first):**
   - (a) **measured geometry** from the takeoff (lengths, areas, volumes, counts of blocks or symbols), using the layer mapping the AI proposed;
   - (b) **annotated values** the AI read from the drawings, with page and bbox;
   - (c) if neither exists, the line is marked "not verifiable from drawings". **An AI visual estimate is never used as a quantity.** At most it's shown as a low-confidence hint, never counted as a match.

   Unit conversion uses the existing unit engine.
3. **Classes per BOQ line** (matching the existing three-class scheme, extended):
   - **Match** (within tolerance);
   - **Variance** (with the delta and %);
   - **Missing in drawings** (a BOQ item with no drawing evidence);
   - **Not verifiable** (for example provisional sums, preliminaries, or items that can't be drawn).

   Plus **Missing in BOQ**: drawing elements with no BOQ line, which is possible missed scope.

   Each line carries its confidence, the method (measured, annotated or AI-mapped), and evidence links that open the takeoff viewer on the exact sheet and region.
4. **Report:**
   - a screen with filters by class, trade and confidence, where the estimator can accept or override a mapping (non-destructive, audited), so the report recalculates;
   - a summary (counts, total variance by trade, top risks);
   - **export to xlsx and PDF**;
   - accepted mappings are stored as feedback for future suggestions (the existing RAG feedback table);
   - the result feeds the existing reconciliation, so the two stay one system and don't become parallel ones.
5. **Performance:** batch BOQ lines per call, cache results, show progress, and keep the whole report within the project budget. It must handle a 1,000+ line BOQ.

## Phase 4: AI pricing assistant (settlement)
**Goal:** for every BOQ line in a settlement draft, propose a cost, where it came from, and a suggested markup, with reasons. **Every proposal can be accepted or overridden by a person. Approval routing and SoD don't change.**
1. **Candidates:** gather these deterministically for each line:
   - accepted vendor quote lines (C2);
   - cost-library rates as of the tender date, including components;
   - historical rates from past settlements and outturn data (Module E);
   - vendor prequalification and location eligibility.
2. **Choosing (AI):** the AI matches the BOQ description to candidates (the semantic part, for example "Supply & lay 150mm uPVC SN8" against the cost item "uPVC pipe DN150 SN8, laid"). It ranks them and proposes one, with a rationale and flags:
   - a unit mismatch;
   - a stale rate (older than N months, configurable);
   - a vendor quote with exclusions (C2 flags);
   - a single-source risk;
   - a big deviation from the historical median.

   **The rate itself always comes from the chosen source.** The AI never invents a rate. A line with no candidate is marked "No cost source: manual entry required".
3. **Markup suggestion (AI, advisory):** suggest markup, overhead and volatility ranges per trade, using win/loss history (Phase 2 D2 data), how risky the flagged lines are, market volatility settings and project size. Show the reasoning and the expected margin-on-sell for each option. **Only a person sets the values**, and approval thresholds (AED 2m / 8%) are enforced exactly as today.
4. **UI:** a "Propose costs with AI" action on the settlement draft (lead_estimator+), a per-line proposal panel (source, rate, rationale, flags, accept or override), bulk-accept for high confidence, and a "Suggest markup" panel next to the sliders. All accept and override actions are audited and show who, when and which AI call.
5. The accepted costs flow into the existing settlement engine, where rates are authoritative and Decimal. Nothing downstream changes.

## Phase 5: mock data and testing without a key
1. **`make dev-seed-ai-demo`:** a realistic UAE infrastructure dataset. It's synthetic and tagged, so `dev-clean-demo-data` removes it. It includes:
   - a **cost library**: about 150 items across earthworks, asphalt, kerbs, drainage and pipes (uPVC, DI, GRP by diameter), manholes, road marking, street lighting and landscaping, with component rates and some history;
   - **vendors**: about 20, with trades, locations, prequalification (some expiring) and accepted quotes with realistic exclusions;
   - **win/loss history**: about 15 past tenders with margins and outcomes;
   - a **tender pack**: DXF and vector-PDF drawings, a PDF BOQ and an Excel BOQ, with deliberate matches, variances, a missing-in-BOQ item and a missing-in-drawings item.
2. **Mock provider:** returns deterministic, schema-valid outputs recorded for the fixtures, so every phase runs end to end in tests and in the dev stack without a key.
3. **Evaluation harness** (`make ai-eval`): a golden set for each task (classification, BOQ row reading, annotation reading, BOQ ↔ drawing mapping, cost-candidate choice). It reports accuracy, cost and latency per provider and model. It runs against `mock` now, and against the real provider once the key is added. Save the results in `docs/ai-eval/`.
4. **`make ai-smoke`:** one tiny real call per task, skipped with a clear message when no key is set.
5. **Tests:**
   - unit tests for every schema, rule, calculation and budget or cache path;
   - integration and API tests for RLS on the new tables, the admin switch, budget hard stops, "AI not configured" fallbacks, and roles (lowest allowed and denied);
   - prompt-injection tests for each task;
   - a real-backend Playwright walkthrough with the mock provider: create a project, drop the folder, classify and confirm, extract, run verification, review the report and export it, build the settlement, propose costs with AI, accept, suggest a markup and set it, submit, approve as a different user, and export.

## Phase 6: wrap-up
- Run `make test-all`, the frontend checks, and the real-backend specs for everything touched, **each file separately** with `--workers=1` (the machine's memory can't take the full suite reliably).
- Write `docs/ai-report.md` covering:
  - what was built;
  - the data that leaves the boundary, per task;
  - the governance controls;
  - eval baselines on mock;
  - known limits (vision estimates are never quantities, rate proposals only come from real sources);
  - **exactly which `.env` keys the owner must fill in**;
  - how to run `ai-smoke` and `ai-eval` once the key is added;
  - how to switch back to local vLLM.
- Merge, leave MFA off, don't push, and stop.
