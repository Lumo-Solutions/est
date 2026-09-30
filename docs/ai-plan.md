# External AI provider + AI-assisted verification and pricing: plan

Implements `docs/ai-provider-brief.md`. Branch `feat/ai-provider` (phase branches `feat/ai-p<N>` merge `--no-ff` into it, then into `master`). This is a **temporary, knowing reversal of SRS §1.1** ("no external AI APIs"), recorded in `docs/deploy-deltas.md`, `docs/build-log.md` and `docs/ai-provider.md`.

## 1. Provider design

One module, `backend/app/ai/`, is the only place that talks to a model.

```
app/ai/
  provider.py     AIProvider protocol + request/response dataclasses
  registry.py     get_provider(settings, task) -> AIProvider   (AI_PROVIDER selects)
  gateway.py      AIGateway: the ONLY entry point for callers (governance + cache + audit + budget)
  providers/local_vllm.py        existing guided_json call, moved here
  providers/openai_compatible.py response_format json_schema, image_url input
  providers/anthropic.py         Messages API, forced tool_use for schema output, image/PDF document blocks
  providers/mock.py              deterministic, fixture-driven
  pricing.py      per-model $/token table (config-overridable) -> cost estimate
  cache.py        (task, input sha256, model, prompt_version) -> response
  budget.py       monthly / per-project hard stops
  errors.py       AINotConfigured, AIDisabledForTenant, AIBudgetExceeded, AIProviderError
```

Operations on `AIProvider`: `classify`, `extract_structured` (both: system + user + JSON schema -> dict), `vision_extract` (schema + images / PDF pages -> dict), `match_rank` (query + candidates + schema -> ranked list with reasons), `embed` (optional; the local ONNX embedder stays the default and is untouched).

`classify` and `extract_structured` share one wire path; they differ in task labelling, default model tier and cache namespace. `match_rank` is `extract_structured` with a fixed ranked-list schema.

**Callers never import a provider.** They call `AIGateway.run(task=..., ...)`, which in order: (1) resolves tenant/project governance, (2) checks provider configured, (3) checks cache, (4) checks budget, (5) calls the provider with retry/backoff, (6) writes an `ai_calls` row, (7) returns `AIResult(data, call_id, cached)`. Failure modes raise typed errors that every caller already handles by falling back to rules ("AI not configured" / "AI not allowed" / "budget exceeded").

Default provider is `local_vllm` when `AI_PROVIDER` is unset, so existing behaviour and the existing mock-vllm dev/test stack are unchanged. Switching back to local later is config only (`AI_PROVIDER=local_vllm`).

### Config (`.env.example`, `core/config.py`)
`AI_PROVIDER` (local_vllm|anthropic|openai_compatible|mock), `AI_MODEL`, `AI_MODEL_CLASSIFY`, `AI_MODEL_VISION`, `AI_MODEL_REASONING`, `AI_API_KEY`, `AI_BASE_URL`, `AI_TIMEOUT_S`, `AI_MAX_RETRIES`, `AI_MONTHLY_BUDGET_USD`, `AI_PROJECT_BUDGET_USD`, `AI_STALE_RATE_MONTHS`. `SecretStr` for the key; never logged, never in any response schema, redacted in `repr`. The existing `VLLM_*` vars remain and feed `local_vllm`. The `_assert_vllm_is_private` guard stays for `VLLM_API_BASE`; a new validator requires `AI_BASE_URL` to be https for external providers.

## 2. Governance

- **Tenant switch** `tenants.external_ai_allowed` (default false), changeable only by `managing_director` via `PUT /admin/ai-settings`, audited. **Per-project override** `projects.external_ai_override` (null = inherit, false = never external). A confidential tender is kept local/off. `local_vllm` and `mock` are never "external" so are not gated.
- **`ai_calls`** table (tenant RLS, project column nullable; read: managing_director, bd_director, platform admin, lead_estimator for own project; write: all app roles via the gateway): id, task, provider, model, project_id, entity_type, entity_id, prompt (internal), response (internal), input_sha256, prompt_version, tokens_in/out, cost_usd (Numeric), latency_ms, status (ok|cached|error|blocked), error, created_by, created_at. Prompt/response are excluded from list endpoints (detail only, MD).
- **Budgets:** month-to-date and project-to-date cost summed from `ai_calls`; a call is refused (`AIBudgetExceeded`, HTTP 402-style `ai_budget_exceeded` code) once the cap is reached. Unset cap = unlimited for local/mock.
- **Cache** table `ai_cache` keyed by (tenant, task, input_sha256, model, prompt_version): a hit costs nothing and is still logged as `cached`.
- **Rate limiting / retries:** tenacity backoff on timeouts/5xx/429; per-tenant token bucket in Redis.
- **Egress:** documented in `docs/ai-provider.md` + `docs/deploy-deltas.md`: only the AI host allowed from the AI-capable workers.

## 3. Safety (carried from C2)
Documents are untrusted input; prompts put the system instruction outside and wrap document text in a delimited, "data not instructions" block. Every schema has no action field; results are proposals persisted with `source='ai'` and reviewed by a person. Money totals and quantities are never AI outputs: AI reads/maps, engines compute in Decimal. Prompt-injection tests per task (a document containing "ignore previous instructions ..." cannot change output shape, and unknown keys are dropped).

## 4. AI tasks (inputs / output schema / deterministic vs AI)

| Task | Input | Output (schema-constrained) | Deterministic part |
|---|---|---|---|
| `intake_classify` | filename, folder path, first pages' text, title-block text/region | doc_class, sub_type, confidence, evidence, metadata | rules run first; AI only for low-confidence/conflicting |
| `title_block` | title-block text + image | drawing_number, title, revision, date, discipline, scale text | regex fallback |
| `scale_hint` | raw scale text | ratio, confidence | regex parser first |
| `quotation_extract` (C2) | quote text/image | line items, exclusions | matching to BOQ stays deterministic |
| `boq_pdf_rows` | pages unparsable by pdfplumber (image + text) | rows {item_no, description, unit, qty, rate?, page, bbox} | pdfplumber table parse first |
| `drawing_annotations` | drawing page image/text | annotations {text, kind, value, unit, page, bbox}, legend, schedule | geometry measurement untouched |
| `boq_interpret` | batch of BOQ lines | per line {work_type, material, size, unit, trade, evidence candidates ranked with reasons} | candidates pre-filtered by layers/blocks/annotations |
| `cost_choose` | BOQ line + deterministic candidates | ranked candidate ids + rationale + flags | candidates gathered, rate taken from chosen source, flags computed (stale, unit mismatch, exclusions, single-source, deviation) in code |
| `markup_advise` | per-trade context numbers | ranges + reasoning | margin-on-sell math and thresholds in existing engine |

## 5. Data flows
1. **Upload** (files/folder/zip) -> intake safety -> rules classify -> (gateway, only if needed) -> proposal -> user confirm.
2. **Read**: BOQ xlsx via existing import; PDF BOQ via pdfplumber, low-confidence pages via `boq_pdf_rows`; feeds the existing wizard (mapping -> dry-run -> commit). AI rows flagged `ai_read` with page + bbox. Drawings: existing deterministic pipeline + `drawing_annotations` stored as `drawing_annotations` rows.
3. **Verify**: `boq_interpret` proposes evidence; `verification` service computes quantities (measured geometry via layer mapping -> annotated values -> not-verifiable) using the unit engine; classes match / variance / missing_in_drawings / not_verifiable, plus missing_in_boq; results in `verification_runs` + `verification_lines`; overrides are audited; accepted mappings write `semantic_match_feedback`; reconciliation reads the same accepted links (no parallel system).
4. **Price**: candidates (accepted quotes, cost-library rate as at tender date with components, historical/outturn, vendor prequal + location) -> `cost_choose` -> `settlement_ai_proposals` rows -> person accepts/overrides -> writes the line's cost through the existing settlement service. Markup advice is display-only; people set sliders; thresholds unchanged.

## 6. Cost controls and defaults
Rules-first everywhere; cache by input hash; batch BOQ lines (default 25 per call); per-task model tier (cheap classify, vision for pages, reasoning for mapping/pricing); per-project and monthly caps; stale rate default 12 months (`AI_STALE_RATE_MONTHS`); bulk-accept confidence threshold 0.85; verification tolerance = existing `boq_tolerances`.

## 7. Build order and delivery
Phase 1 provider layer (main session, security sensitive: config, migrations, RLS, gateway, admin API) -> Phase 2 intake/reading -> Phase 3 verification -> Phase 4 pricing -> Phase 5 demo data/eval/tests -> Phase 6 wrap-up. Backend services/UI/tests in phases 2-5 may be delegated to <=2 worktree subagents under finish-brief section A; migrations, RLS, auth and config stay main-session. Stack-dependent tests run one at a time, `--workers=1`. Progress and resume point: `docs/ai/log.md`.
