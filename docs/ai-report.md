# External AI provider, drawing-to-BOQ verification and AI pricing: report

Brief: `docs/ai-provider-brief.md`. Plan: `docs/ai-plan.md`. Provider reference and per-task data disclosure: `docs/ai-provider.md`. Resume log: `docs/ai/log.md`. Branch `feat/ai-provider` (merged to `master`, not pushed).

> **This work knowingly and temporarily reverses SRS §1.1 ("no calls to external AI APIs")**, at the owner's decision, until a GPU server runs the in-house model. It is **off by default** (`AI_PROVIDER=local_vllm`, tenant switch off) and reversible by configuration alone. Recorded in `docs/deploy-deltas.md` and `docs/build-log.md`.

## 1. What was built

**Provider layer (Phase 1).** One `AIProvider` interface (`classify`, `extract_structured`, `vision_extract`, `match_rank`, `embed`) with four implementations: `local_vllm` (default), `anthropic` (native Messages API, forced tool call for schema output, image and PDF blocks), `openai_compatible`, and `mock` (deterministic, the default for tests). Every AI call goes through `AIGateway`: provider-configured check, tenant switch and project opt-out, cache, per-tenant rate limit, monthly and per-project budget hard stops, retry with backoff, and an append-only `ai_calls` row for every call (including blocked, cached and failed), written in its own transaction so it survives a caller's rollback. The four existing vLLM callers were ported without changing their call shape. Callers with no fallback (title block, scale hint, quotation extraction) now degrade on any AI error instead of failing.

**Intake and reading (Phase 2).** Folder upload (relative paths kept and used as a weak classification signal, in the rules and in the model prompt), the "Drop the tender package here" landing after creating a project, a deterministic pdfplumber BOQ reader (repeated headers, wrapped descriptions, brought/carried-forward lines, collection pages) with the vision task only for pages it cannot read and for scans, an editable review grid and commit through the same tree builder as an Excel import, AI-read rows flagged with page and region, drawing annotation reading (title block, legend, schedule, `L=245.0m` / `D300` / `12 nos` with page and bounding box) with per-sheet progress and links into the takeoff viewer.

**Drawing to BOQ verification (Phase 3).** Per BOQ line: Match, Variance (delta and %), Missing in drawings, Not verifiable; plus Missing in BOQ for drawing quantities nothing accounts for. Quantities come from measured geometry first, then annotations the AI read, never from a visual estimate; comparison and tolerance reuse the existing reconciliation and unit engine. The AI interprets lines and ranks candidate evidence; it can only choose among candidates it is given. Accept / reject / include / clear decisions are audited, non-destructive, recalculate deterministically, persist across runs, link accepted measurements into the existing reconciliation and feed the existing semantic-match feedback table. Report screen with filters, summary, top risks and xlsx/PDF export. Pipe runs are grouped per (sheet, kind, layer) into one evidence item and the extractor's network total is skipped, so a size that is 20 runs is one item and nothing double counts.

**Pricing assistant (Phase 4).** For each settlement line: real candidates (accepted vendor quote line, cost-library rate as at the tender date, historical median from past settlements and outturn), flags computed in code (unit differs, stale rate, quote exclusions, vendor prequalification and location eligibility, FX needed, deviation from history, single source), an AI choice among them with a rationale, and a confidence. Accept, choose another, enter manually (reason required) or reject; bulk-accept only takes high-confidence, unflagged proposals. Everything applies through the existing `set_line_cost`, so rates stay authoritative and approval routing, thresholds and segregation of duties are untouched. Markup, overhead and volatility advice is advisory: the platform computes every margin with the existing engine, a person presses "Use these values", and nothing is applied automatically.

**Governance.** `External AI allowed` tenant switch (off by default, managing_director only, audited), per-project opt-out, `ai_calls` audit with an admin usage and cost view, budgets, cache by (task, input hash, model, prompt version), rate limit, and a plain-language status ("AI not configured", "not allowed", "budget reached") in the UI.

## 2. Bugs found in existing code and fixed (each with a test)

1. `POST /projects/{id}/boq-items` raised `MissingGreenlet` while serialising its response (no test called it).
2. `bid_settlement_line_items.cost_source` was `varchar(16)` but `cost_library_rate` is 17 characters, so **applying a cost-library rate to a settlement line always failed**; no test covered that path (migration `0036`).
3. The sheet index counted `extraction_status = 'ready'`; the backend writes `succeeded`.
4. `docker-compose.yml`: the `backend` service keeps its own environment list, so `AI_*` reached the workers but not the API (`deploy/check-ai-env.sh`, `make check-ai-env`, now guards it).
5. The cost library is append-only by design (no DELETE policy), so `clean-demo-data` **deactivates** demo cost items rather than deleting them (same situation as `inbound_emails`); re-seeding reactivates them.

## 3. Data that leaves the boundary, per task

See the table in `docs/ai-provider.md`. In short: classification sends file name, folder and the first pages' text; BOQ and annotation reading send only the pages the deterministic readers could not handle (and annotations only when someone asks); interpretation and ranking send BOQ text and candidate labels but **no prices**; **`cost_choose` sends vendor names and rates, and `markup_advise` sends trade-level direct-cost totals**. Keep the tenant switch off, or the project opt-out on, for anything commercially sensitive.

## 4. Governance controls

Tenant switch and project opt-out (blocked calls are audited and never leave), key handled as a secret (never logged, returned or stored), budgets as hard stops, `ai_calls` visible to lead_estimator and above, admin usage view, egress rule documented (`docs/deploy-deltas.md`: allow HTTPS to the one AI host from the four AI-capable workers and the backend, deny the rest), AI output always a proposal, schemas with no action, rate or quantity fields, numbers clamped to the schema range, unknown keys dropped, unknown references ignored.

## 5. Evaluation baseline (mock)

`make ai-eval` runs the production code paths on golden sets built from the synthetic pack and writes `docs/ai-eval/`. Baseline on the deterministic mock fixtures (`docs/ai-eval/latest-mock.md`): classification 100% (15 cases), BOQ PDF page reading 100%, annotation reading 100%, BOQ line interpretation 100%, evidence ranking 100% (16 lines), cost choice 100% (9 lines), markup advice 100%. **This is the fixtures' regression baseline, not a model's quality**: the mock was tuned against the same pack, and the first version of it scored 88% (it missed a correspondence keyword, heading rows, bare `100.0m` lengths and treated "connection to existing manhole" as the new manholes), which is exactly what the harness is for. Run it against the real provider once the key is in.

## 6. Known limits

- A visual estimate is never a quantity. Lines with no measurable or annotated evidence are "Missing in drawings" or "Not verifiable", never guessed.
- Rate proposals come only from real sources; a line with none says "No cost source: manual entry required".
- Annotated quantities are summed when several match and flagged (`multiple_annotations`, lower confidence) because a length printed on both plan and profile could double count; the report lets the estimator exclude the duplicate.
- History and vendor eligibility are read under the caller's row-level security: a lead sees past projects they belong to; bd_director, procurement_head and managing_director see all.
- The demo `clean-demo-data` cannot delete cost-library items (append-only); it deactivates them.
- PDF BOQs cannot be written back into an original workbook (no workbook exists); the export says so and the generated export still works.
- The vendors list shows the first 50 vendors by name and has no paging or search yet (existing behaviour). On a database with more than 50 vendors a new vendor can be off the first page; the `vendors-prequal` spec now opens the vendor by the id the create call returns. Worth adding paging.
- Real-model behaviour (prompts, thresholds, cost) is unmeasured until a key is supplied: expect to tune `RULES_ATTACH_MIN_SCORE`, the bulk-accept threshold (0.85) and batch sizes against `make ai-eval`.

## 7. What the owner must do

Fill in `deploy/.env` (recreate the containers with `make up` afterwards):

```
AI_PROVIDER=anthropic            # or openai_compatible; local_vllm to switch back
AI_API_KEY=<the key>
AI_MODEL=<model id>              # optional per task: AI_MODEL_CLASSIFY / AI_MODEL_VISION / AI_MODEL_REASONING
AI_BASE_URL=                     # openai_compatible: required (https); anthropic: leave blank
AI_MONTHLY_BUDGET_USD=           # recommended
AI_PROJECT_BUDGET_USD=           # recommended
```

Then: sign in as the managing director, Admin > AI, switch **External AI allowed** on (confirm the dialog); allow HTTPS egress to the provider host; run `make ai-smoke` (one tiny real call per task) and `make ai-eval PROVIDER=anthropic` (spends real money on the synthetic golden sets only, writes `docs/ai-eval/`). To switch back to the in-house model: `AI_PROVIDER=local_vllm` and `make up`. No code change, no data migration.

## 8. How to run the demo

`make up && make migrate && make seed`, set `AI_PROVIDER=mock` and `TAKEOFF_PERSIST_GEOMETRY=true` in `deploy/.env`, then `make dev-seed-ai-demo` (cost library, vendors, 15 past tenders) and `make dev-ai-demo-pack` (writes `./.ai-demo-pack/`). Create a project (the UI lands on Tender documents), drop the `Al Reem Package 3` folder, confirm, import the Excel BOQ, read annotations, **Verify BOQ against drawings**, then `make dev-seed-ai-demo-quotes` before building the settlement. `make dev-clean-demo-data` removes it all. The designed outcome is in `backend/app/demo/ai_demo.py` (`EXPECTED_CLASSES`).

## 9. Verification record

Run on 2026-09-30 on the final commit of this branch (before the merge), each suite separately:

| Check | Result |
|---|---|
| `make test-unit` | 631 passed |
| `make test-integration` | 264 passed |
| `make test-api` | 90 passed |
| Frontend `npm run build` | OK |
| Frontend `vitest run` | 27 files, 148 tests passed |
| Frontend `npm run lint` / `oxlint e2e` | 0 errors (3 pre-existing warnings in files this work did not touch) |
| `make check-ai-env` | OK: the backend service passes all 13 `AI_*` keys the workers get |
| Real-backend specs (25 files; `step-up-freshness` is ignored by the config), each file alone with `--workers=1` | all pass, including the new `ai-walkthrough.spec.ts` (2 tests) |

**Real-backend runs were not clean first time; what was found.**

- The walkthrough found three genuine defects, all fixed with tests: a confirmed PDF BOQ was refused by the router; measured evidence could be cut by the verification attach cap when several annotations ranked first; and the verification report crashed (white screen) on a top risk with no BOQ line ("Missing in BOQ"). The mock classifier also needed to call an image-only scan a low-confidence drawing, as the older classification mock did (the `tender-intake` spec caught this).
- Three older specs were stale against deliberate changes and were updated: `project-pages` (creating a project now lands on its Tender documents tab, per the brief) and `vendors-prequal` (see the known limit below). `tender-intake` was fixed in the mock, not the spec.
- **Connection flakes in this dev environment.** Across the full pass, several specs failed once with `ECONNRESET` on an API call or a timeout on `/api/v1/auth/login`, at a different step each time, and passed when rerun alone (`login`, `home-dashboard`, `dwg-conversion`, `phase4-accessibility`, `quotation-settlement-overrides`, `ai-walkthrough`, `tender-intake`). `project-members-scenarios` failed three times the same way before passing (the last run used `--retries=2` and reported no flaky test). The backend showed no errors or restarts, 300 fresh connections through the proxy all succeeded, and the failures only appear on Playwright's reused keep-alive sockets, so I attribute them to the local Docker/Windows networking and test client rather than the application. A clean CI host should confirm this; if they recur there, look at keep-alive settings on the backend and proxy first.
- A first attempt at `make test-all` was killed by the harness for low memory (not a test failure); the suites were then run separately as above.

## 10. Subagents (finish-brief rule A)

Every UI task ran in its own worktree with a file allow-list, created by the main session from the current branch head. For each: the commit was confirmed to exist on its branch, the full diff was read, changed files were checked against the allow-list, and `tsc`, `oxlint` and `vitest` were re-run by the main session after merging. Agents: AI admin UI (`6951c4e`, merged as `241316a`; its worktree base had drifted, so two conflicts were resolved by hand), folder upload (`764ec01`), PDF BOQ wizard (`e46af75`), sheet annotations (`2eea92c`, one wrong assumption about `extraction_status` found and fixed by the main session), verification report (`9f60931`), pricing assistant (`58f7f73`). No agent ran git beyond add/commit/status/diff/log, touched the shared stack, or edited a security-sensitive file. Migrations, RLS, config, auth and compose were main-session only.
