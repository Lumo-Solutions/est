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
