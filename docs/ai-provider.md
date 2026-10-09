# External AI provider

> **Knowing, temporary deviation from SRS §1.1** ("No calls to commercial external AI APIs"). Decided by the owner: until a GPU server runs the in-house model, the platform can use an external AI API for classification, document reading, drawing-to-BOQ verification and pricing assistance. It is **off by default** and reversible by configuration only. Recorded in `docs/deploy-deltas.md` and `docs/build-log.md`.

Design and task list: `docs/ai-plan.md`. Brief: `docs/ai-provider-brief.md`.

## What runs where

| `AI_PROVIDER` | Where the data goes | Governed / cached / billed |
|---|---|---|
| `local_vllm` (default when unset) | the self-hosted vLLM (`VLLM_*`), inside the deployment | no |
| `mock` | nowhere (deterministic fixtures; tests and keyless dev) | no |
| `anthropic` | the Anthropic Messages API (`AI_BASE_URL` blank = `https://api.anthropic.com`) | **yes** |
| `openai_compatible` | any OpenAI-style `/chat/completions` endpoint at `AI_BASE_URL` | **yes** |

Every AI call in the code base goes through `app.ai.gateway.AIGateway`. Nothing else may talk to a model.

## Switching (configuration only)

Edit `deploy/.env`, then recreate `backend` and the celery workers (`make up`).

```
# external
AI_PROVIDER=anthropic            # or openai_compatible
AI_API_KEY=<key>
AI_MODEL=<model id>              # optional per task: AI_MODEL_CLASSIFY / AI_MODEL_VISION / AI_MODEL_REASONING
AI_BASE_URL=                     # openai_compatible: required (https). anthropic: leave blank
AI_MONTHLY_BUDGET_USD=200        # optional hard stops
AI_PROJECT_BUDGET_USD=25

# back to the in-house model: no code change
AI_PROVIDER=local_vllm
```

If an external provider is selected and the key/model is missing, AI features show **"AI not configured"** and fall back to rules or manual entry. Nothing crashes.

## Governance (tenant data leaves the boundary)

1. **Tenant switch** `External AI allowed`: off by default. Only `managing_director` changes it (`PUT /api/v1/admin/ai-settings`), and every change is written to the audit chain (before/after).
2. **Per-project override** (`PUT /api/v1/projects/{id}/ai-override`, `bd_director`/`managing_director`, audited): `false` keeps a confidential tender off external AI regardless of the tenant switch. It can only restrict, never grant.
3. **`ai_calls`**: every call, including blocked, cached and failed ones, with task, provider, model, project, entity, prompt and response (internal), tokens, cost estimate, latency, status and error. Append-only, RLS: every role can write, only `lead_estimator` and above can read. List endpoints never return the prompt or response.
4. **Budgets**: `AI_MONTHLY_BUDGET_USD` and `AI_PROJECT_BUDGET_USD` are hard stops (`ai_budget_exceeded`, audited as `blocked`); `GET /api/v1/admin/ai-usage` (`managing_director`, `bd_director`) shows month-to-date spend and per task/model usage. Costs are estimates from a token table (`app/ai/pricing.py`); the provider's invoice is authoritative.
5. **Cache** by (tenant, task, input sha256, model, prompt version): re-running the same document costs nothing (logged as `cached`). External providers only.
6. **Rate limit** per tenant per minute (`AI_RATE_LIMIT_PER_MIN`, Redis; fails open) and retry with backoff on timeouts, 429 and 5xx (`AI_MAX_RETRIES`).
7. **The key** is a `SecretStr`: never in `repr`, logs, API responses or the `ai_calls` table.

## Safety (carried over from C2)

Documents are untrusted input. System instructions are separate from document text; schemas have **no action fields** and unknown keys are dropped by the gateway; **AI output is always a proposal** that a person confirms; the AI never produces a money total (Decimal engines do), and never a quantity from a visual guess. Prompt-injection tests exist for every task.

## Egress

Only the configured AI host may be reachable from the workers that call it (`backend`, `celery_worker`, `celery_worker_vlm`, `celery_worker_quotation`). With an external provider enabled, allow outbound HTTPS to that one host (for Anthropic: `api.anthropic.com:443`) and deny the rest. Add the rule at the host firewall or the container network; `docs/deploy-deltas.md` has the checklist.

## Files

`backend/app/ai/`: `provider.py` (interface), `providers/` (four implementations), `gateway.py`, `store.py`, `registry.py`, `pricing.py`, `schema_util.py`, `compat.py` (`extract_json` shim for the original callers). Migration `0032`. Admin API in `app/api/v1/routes/ai.py`.

## What leaves the boundary, per task

Only when `AI_PROVIDER` is external **and** the tenant switch is on **and** the project has not opted out. With `local_vllm` or `mock` nothing leaves. Embeddings always stay local (ONNX). Every call is recorded in `ai_calls` (prompt and response kept internally; the admin usage view shows task, model, tokens, cost, latency and status only).

| Task | Sent to the provider | Never sent |
|---|---|---|
| `intake_classify` | **every** uploaded file (AI-first intake, prompt v2; a byte-identical copy in the same project reuses its original's answer): file name, folder path, file type, page count, the text of the first two pages (up to ~6,000 characters) or a workbook's sheet names with their first rows, title-block text (~2,000), what the automatic rules suspect (as an unverified hint), and, **only when the text is not enough** (scans, sheets that are all linework, images), a page-1 image plus a higher-resolution crop of the title block, sent to the vision model | the file itself, pages after the second, the rest of a workbook |
| `title_block` | title-block text and the cropped title-block image of a sheet | the rest of the sheet |
| `scale_hint` | the printed scale text | anything else |
| `quotation_extract` | the vendor quotation's text, or its page image | tenant BOQ, other quotes |
| `boq_pdf_rows` | one page image and up to ~6,000 characters of that page, only for pages the table reader could not read and for scans | pages the reader handled itself, rates and amounts |
| `drawing_annotations` | the sheet image (PDF) or up to ~8,000 characters of sheet text (DXF), only when someone asks for annotations to be read | measurements |
| `boq_interpret` | BOQ item numbers, descriptions, units and section headings | quantities, rates |
| `evidence_rank` | a BOQ description and unit, and up to 8 candidate drawing items (label, value, unit, layer, sheet number) per line | prices |
| `cost_choose` | a BOQ description, unit and quantity, and up to ~10 candidate cost sources: label, **rate, currency, vendor name**, age and flags | anything not a candidate |
| `markup_advise` | project name, size band, current percentages, trade names with line counts and **direct-cost totals**, win/loss history by margin bucket | individual rates, competitor names |

`cost_choose` and `markup_advise` therefore expose commercial figures. Keep the tenant switch off, or the project's AI opt-out on, for anything commercially sensitive. AI never supplies a rate, a quantity or a total: each task's schema has no field for one, and the platform's own engines compute every number.

## Files added by the AI work

`backend/app/ai/` (gateway, providers, mock fixtures, eval, smoke), `backend/app/verification/`, `backend/app/pricing/`, `backend/app/boq/pdf_reader.py`, `backend/app/boq/pdf_ai.py`, `backend/app/takeoff/annotations.py`, `backend/app/demo/` (synthetic dataset), `ai-service/prompts|schemas/` (boq_pdf_rows, drawing_annotations, boq_interpret, evidence_rank, cost_choose, markup_advise). Migrations `0032` to `0036`.

## BOQ agent and the AI at upload (10 Oct 2026)

- **No model call at upload by default.** `intake_ai_classify` (tenant setting, default off) gates the per-file classification described above; `AI_MODEL_CLASSIFY` is then used only by the agent's bulk reads. Turning it on restores the previous behaviour exactly.
- **The agent runs on `AIGateway`** (task names `agent.step`, `agent.vision`, `agent.chat`): caching, the `ai_calls` audit, rate limiting, the external-AI switch, the per-project opt-out and the monthly/project budgets apply to every step. Step output is a JSON-schema object (`note`, `tool`, `args`), so it works with `openai_compatible`, `anthropic`, `local_vllm` and `mock` without provider-native tool calling. Reasoning tier plans and steps; the vision tier looks at a page only when the agent asks for one (counted separately and capped per run).
- **What the model may claim** is limited in code: a rate/currency/unit/as-of date comes from the chosen cost candidate's database row, never from the model; an estimate without a candidate needs evidence and a method text and is flagged `agent_estimate`.
