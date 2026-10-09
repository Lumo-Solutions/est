# BOQ-led estimation agent: plan

Brief: `docs/boq-agent-brief.md`. Branch `feat/boq-agent`. Working rules: `docs/finish-brief.md` §A. This plan records the
design choices the brief left open; defaults in the brief's last section are adopted as written.

## 0. Scope change (recorded in deploy-deltas, build-log, ai-provider)
- Upload becomes fast and AI-free: `tenant_ai_settings.intake_ai_classify` (default **false**). The per-file AI call in
  `tender_intake_processing._ai_read` stays, behind that flag; when off, the rules classification is the result (as when
  the AI is unavailable today), flagged `classified_by='rules'`.
- "The AI never sets money" is relaxed **for drafts only**: the agent writes proposals; a deterministic applier puts them
  in a *draft* settlement; a lead_estimator+ must confirm each agent line before submit. Approval is unchanged.

## 1. Data model (migrations from 0040, all RLS, tenant_id + project_id like neighbours)
| Migration | Content |
|---|---|
| 0040 manifest | `project_file_index` (1:1 with `project_documents` via unique `document_id`): `path`, `folder`, `filename`, `ext`, `size_bytes`, `sha256`, `page_count`, `page_sizes` JSONB, `page1_text` (≤4000), `title_block_text`, `sheets` JSONB (name, header row, rows), `hints` JSONB (doc type, discipline, number, revision, scale, addendum no + confidences), `partial_index` bool + `partial_reason`, `indexed_at`, `search_tsv` (generated tsvector, GIN), `embedding` vector (DEFAULT_EMBEDDING_DIM, HNSW/ivfflat cosine). Plus `tenant_ai_settings.intake_ai_classify`. A separate table (not columns) because the tsvector/embedding must not bloat `project_documents` scans and the backfill needs "has manifest" as a simple anti-join. |
| 0041 agent | `agent_runs`, `agent_steps`, `agent_line_proposals`, `agent_conversations`, `agent_messages` (brief §2.5). |
| 0042 settlement | `bid_settlement_line_items.agent_proposal_id`, `agent_confirmed_by`, `agent_confirmed_at`; `cost_source` accepts `agent_candidate`, `agent_estimate` (column is already varchar(24), widened in 0036; the enum gains the values). |

## 2. Phase 1: fast index
- New `app/intake/manifest.py`: `build_manifest(filename, ext, data, folder, limits) -> ManifestEntry` — pure, no AI, no
  rasterisation. PDF via pypdfium2 only (page count/sizes, page-1 text, bottom-right title-block text); XLSX/CSV sheet names +
  first non-empty row + row counts (openpyxl read-only); DOCX first 4000 chars; DWG/DXF name+size; images dimensions.
  Rules hints from `intake/rules.py` + `intake/metadata.py`. Limits (time, pages, chars) from settings; over a limit →
  `partial_index`, never parked. PDFium calls go through the existing process-wide lock (see memory: PDFium not thread-safe).
- `process_one` becomes: claim → download → safety → `build_manifest` → persist manifest + rules classification → route by
  rules only (BOQ workbook → wizard offer, addendum → register) → embed (local ONNX, batched in `intake_embed` step) . The AI
  call is skipped unless `intake_ai_classify`.
- Search: `app/services/manifest_search.py`: `search(project_id, query, filters, k)` = tsvector rank fused (RRF) with cosine
  rank. RLS scopes both.
- Backfill: `python -m app.cli backfill-manifest [--project ID] [--limit N] [--dry-run]`; touches **only** `project_file_index`;
  never edits `project_documents`. Tested on demo data. Not run on 102/103 without the user.
- Numbers: `docs/boq-agent/report.md` before/after on `make dev-ai-demo-pack` and the opt-in 2,000-file test.

## 3. Phase 2: agent core (`app/agent/`)
Package layout: `tools.py` (registry, arg models, executors), `loop.py` (step loop), `context.py` (notes + window),
`applier.py` (proposals → draft settlement), `runner.py` (run/section orchestration), `chat.py`, `mock_sessions.py`.

### 3.1 Step contract
Each step calls `AIGateway.run(task="agent.step", kind=EXTRACT, tier=reasoning, schema=STEP_SCHEMA)`, schema
`{note: string≤300, tool: enum[TOOLS], args: object}`. `args` is validated by the tool's pydantic model after the gateway
(the gateway's `strip_unknown` cannot validate polymorphic args). Invalid → an error result fed back, counts as a step.
`prompt_version` = `agent-1`. `meta=AIMeta(project_id, entity_type="agent_run", entity_id=run_id)` so budgets/audit apply.
An `ai_calls` row per step is linked from `agent_steps.ai_call_id`. Gateway errors map: `AIBudgetExceeded`/`AIDisabledForTenant`
/`AINotConfigured` → section `stopped_limit` (or run `blocked` with reason); `AIRateLimited` → wait next window, retry.

### 3.2 Context
Prompt = fixed system rules + section brief + `notes` (≤2000 chars, model-maintained: each step may emit nothing extra; the
loop appends the step `note` to a bounded per-section notes list, oldest compacted to one line each) + last 6 tool results
(each truncated to 3000 chars) + one-line summaries of earlier results. Documents' text is always wrapped
`<<<DOC file=… page=…>>> … <<<END DOC>>>` and the system prompt states it is data. `looks_like_injection` runs on every text
tool result; a hit sets `agent_steps.injection=true`, wraps with a warning marker, and shows in the trace.

### 3.3 Tools
As the brief table. Notes where the brief left room:
- `read_text/read_sheet/view_page/read_title_block` reuse manifest + `intake.extract` + `boq.pdf_reader`; `view_page` renders one page
  (PDFium under lock) → `AIGateway.run(kind=VISION, tier=vision)` returning a short factual description schema; counted in
  `agent_runs.page_views`.
- `get_measurements` enqueues the existing measure-on-demand with priority 0, polls up to `agent_measure_wait_s` (120), returns
  summary quantities or `pending`.
- `verify_lines`, `cost_candidates` call the existing `services/verification` / `services/pricing_ai._gather` (refactored
  into a public `gather_candidates(session, ctx, settlement, project, lines)` without behaviour change).
- All file ids resolved through `project_file_index` joined to project → out-of-project id gives `unknown_file`.
- Bounds: pages ≤ 5 per read, rows ≤ 100, search k ≤ 20, results truncated.

### 3.4 Proposals and the applier
`propose_line` stores an `agent_line_proposals` row (status `proposed`). Validated in code: a `candidate_ref` must be one the
same run got back from `cost_candidates` for that line (stored in run state); rate/currency/uom/as_of come from that
candidate's `apply` dict — model values are dropped. Unit compatibility via `pricing.engine.units_compatible`; incompatible →
error back to model. `estimate` needs ≥1 evidence item and method text, forced flag `agent_estimate`. Quantity never changed;
measured variance stored in `qty_check`.
Applier (`applier.apply_run(session, ctx, run_id)`): runs as the **run starter's context** (so `set_line_cost` role checks and
audit attribution are a real person), only when current settlement `status == draft` (creates one via `build_settlement_draft`
if none). Skips lines with `source_set_by` not null and a non-agent cost source (person-set). Supersedes its own earlier
agent proposals. Writes line fields directly (not via `set_line_cost`, which stamps `source_set_by`): cost, currency, `cost_source`
= `agent_candidate|agent_estimate`, FK of the chosen quote/rate, `agent_proposal_id`; `source_set_by` stays NULL so "person-set"
remains distinguishable; `needs_fx` leaves fx_rate NULL. Audit entry per applied line. It never touches percentages, FX, quantities.
Confirm: `POST /settlements/{id}/lines/{lid}/agent-confirm` (lead_estimator+, takes `proposal_id` viewed; for estimates it must
equal the line's current proposal) sets `agent_confirmed_by/at`; bulk-confirm only `agent_candidate` lines passing
`can_bulk_accept`. A person editing the line via `set_line_cost` clears `agent_proposal_id` (becomes person-set).
**Submit gate** in `submit_settlement`: any line with agent cost source and null `agent_confirmed_by` → `ConflictError` listing ids.
(`settlement.py` is money/approval-adjacent: main session only.)

### 3.5 Runs
`POST /projects/{id}/agent/runs` {scope, limits override ≤ defaults×? (not above tenant max)} → returns run in `awaiting_confirm`
with a cost estimate (steps×avg tokens from price table; `$0` on local/mock) if provider is external; `POST …/confirm`
(lead_estimator+, audited) → `queued`. Planning step (one task) stores `plan` JSON; then one Celery task per section on queue
`agent` (new worker `celery-worker-agent`, concurrency 1). Section status: `pending|reading|done|stopped_limit|failed|cancelled`.
Pause/resume/cancel check `agent_runs.status` between steps. Task runs under `system_context(tenant)` for reading; the applier
runs under the starter's context built from `agent_runs.started_by` + roles snapshot. Limits: 40 steps/section, 60 views/run,
$5/run; hit → `stopped_limit`. Section result stores a coverage report: files read, found-not-read (+reason), lines without
evidence. Stuck-run sweeper added to the maintenance tick (a `reading` section with no step for 10 min → failed, retryable).

### 3.6 Chat
`agent_conversations/messages`; `POST /projects/{id}/agent/chat` {message} enqueues a turn on queue `agent`; the client polls
`GET …/chat/{conv}/messages?after=` (no SSE pattern exists on the frontend — verify; polling chosen). Turn limit 15 steps /
$0.50. Extra tools `run_status`, `explain_line`, `rerun_section(section, note)`. Writes only through `propose_line` + applier
(the applier call from chat is the same function, under the chatting user's context).

### 3.7 Mock
`mock_sessions.py`: a handler registered for task `agent.step` that replays a scripted sequence keyed by a session id carried in
the user prompt's header; fixture for the demo pack BOQ. Scripts can include an injection scenario and an over-limit scenario.

## 4. Phase 3 UI (subagent, after API contract is merged)
API contract doc `docs/boq-agent/api-contract.md` written before UI work. Project page: Run action + Agent tab (progress, trace,
coverage, chat). Settlement page: source badge, confidence, flags, evidence drawer, Confirm/Bulk/Replace, banner. Doc tree groups by
folder + hints and marks "read by agent". Design system, IBM Plex, lucide, axe clean.

## 5. Phase 4 eval, 5 real pack, 6 folded fixes
As the brief. Phase 5 only with the user present.

## 6. Order of work and ownership
1. plan (this) → 2. migration 0040 + manifest + process_one switch + search + backfill + tests (main) → 3. measure Phase 1 →
4. migrations 0041/0042 + `app/agent` core + mock + tests (main) → 5. applier + submit gate + boundary tests (main) →
6. routes + api-contract → 7. UI via ≤2 worktree subagents → 8. Phase 4 eval, Phase 6 fixes, e2e spec, report, merge `--no-ff`.

## 7. Defaults (as brief)
40 steps/section, 60 views/run, $5/run; chat 15 steps/$0.50; agent never sets percentages/FX/quantities/submit;
`intake_ai_classify` false; lead_estimator+ runs/chats/confirms, estimator views.

## 8. Risks
- Qwen structured output: add `AI_EXTRA_BODY` support to `openai_compatible` if needed (brief §2.1).
- Embedding 1,600 files at upload: batch, local ONNX; failure leaves `embedding` NULL and search falls back to FTS only.
- Existing tests that assert AI-classified intake results need the flag on in their fixtures.
