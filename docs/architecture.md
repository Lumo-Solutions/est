# Architecture Overview

INSTALLTEC is a single-tenant-capable, multi-tenant-from-day-one,
self-hosted platform: every component runs inside the deployment boundary
(Contabo GPU cloud trial, migrating later to on-premise Docker) with zero
external AI/cloud dependencies, per SRS §1.

## Components

- **FastAPI backend** — the only component that talks to Postgres directly
  from request paths. Validates Keycloak-issued JWTs, sets per-request
  PostgreSQL session variables that PostgreSQL Row-Level Security (RLS)
  policies key off, and exposes the REST API.
- **PostgreSQL 16 + pgvector** — single datastore for all transactional
  data (Module A governance core), bi-temporal cost rates, the hash-chained
  audit trail, and vector embeddings for RAG (Module B).
- **Redis** — Celery broker/result backend and BFF session store.
- **SeaweedFS (S3-compatible)** — object storage for uploaded drawings and,
  later, vendor quotations.
- **Keycloak** — OIDC identity provider, enforces MFA (TOTP) and issues the
  JWTs the backend validates.
- **vLLM** (real: `Qwen/Qwen2.5-VL-7B-Instruct`; dev/CI: `ai-service/mock-vllm`)
  — vision-language inference for title-block/scale extraction from drawing
  sheets, via an OpenAI-compatible API with guided JSON decoding.
- **onnxruntime (in-process, backend/Celery)** — local CPU embedding
  inference (`BAAI/bge-small-en-v1.5`) for pgvector-backed retrieval, keeping
  the single GPU dedicated to the vision-language model.
- **Celery + Redis** — asynchronous pipeline for drawing ingestion,
  extraction, and embedding, so uploads don't block request/response cycles.
- **React/Vite frontend** — served by nginx, talks to the backend over
  `/api`.

## Request flow

```
                     ┌─────────────┐
                     │   Browser   │
                     └──────┬──────┘
                            │ HTTPS
                     ┌──────▼──────┐        ┌──────────────┐
                     │   Caddy /   │◄──────►│   Keycloak    │
                     │  frontend   │  OIDC  │  (realm auth) │
                     └──────┬──────┘        └──────────────┘
                            │ /api
                     ┌──────▼──────┐
                     │   FastAPI    │
                     │   backend    │
                     └──┬───┬───┬──┘
             ┌──────────┘   │   └───────────┐
             ▼              ▼                ▼
      ┌────────────┐ ┌────────────┐  ┌──────────────┐
      │ PostgreSQL │ │   Redis    │  │  SeaweedFS    │
      │ + pgvector │ │ (sessions, │  │  (drawings)   │
      │  (+ RLS)   │ │  celery)   │  └──────────────┘
      └────────────┘ └─────┬──────┘
                            │ task queue
                     ┌──────▼──────┐
                     │   Celery     │
                     │  workers /   │──────► vLLM (title-block, scale)
                     │    beat      │──────► onnxruntime (embeddings)
                     └──────────────┘
                            │
                            ▼
                (writes back to PostgreSQL + SeaweedFS)
```

Both the FastAPI request path and Celery tasks open PostgreSQL sessions the
same way (`app/db/session.py`), setting the same RLS context GUCs
(`app.tenant_id`, `app.user_id`, `app.roles`), so authorization is enforced
identically whether a query runs synchronously in a request handler or
asynchronously in a worker.

## What's in Slice 1 vs. deferred

**Implemented this slice:**
- Module A in full: vendor master + duplicate detection, trade taxonomy,
  prequalification & statutory register, bi-temporal master cost library,
  multi-tier approval workflows, immutable hash-chained audit trail — all
  behind PostgreSQL RLS.
- Keycloak authentication: OIDC login, MFA (TOTP) enforcement, BFF session
  cookies, RLS context propagation from JWT claims.
- Module B ingestion slice: vector PDF + DXF upload and multi-sheet
  indexing, vLLM-based title-block/scale extraction, ONNX embeddings +
  pgvector storage with a similarity-search probe endpoint.

**Implemented (Phase 2/2b/3):** DXF geometric intelligence -- alignment
measurement, corridor areas, trench prismoidal volumes, pipe network
topology (`backend/app/takeoff/geometry/`) as real, unit-tested extractors,
wired end-to-end: `index_sheets` persists geometric entities behind
`TAKEOFF_PERSIST_GEOMETRY`, `extract_geometry_measurements` (ingest queue)
runs the extractor registry against them and writes `drawing_measurements`,
and a read-only `GET /drawings/{id}/measurements` exposes the result. BOQ
reconciliation (`backend/app/boq/`, `drawing_measurements` ->
`boq_line_items`): hierarchical BOQ line items (ltree, same pattern as
trade taxonomy), each linkable to *several* measurements (summed --
`boq_line_item_measurements`), unit-dimension-checked and converted (not
just exact-string-matched), with a per-project/per-trade configurable
tolerance (`boq_tolerances`) and a persisted three-class discrepancy flag
(`match`/`variance`/`unmatched`) that self-heals on read if a linked
measurement changes or disappears. Bulk import from an Excel/CSV tender
BOQ (`app/boq/import_parser.py`) with a dry-run preview + all-or-nothing
commit. See `docs/takeoff-pipeline.md` for the full takeoff pipeline and
`docs/boq-reconciliation.md` for BOQ reconciliation's full design and what
remains deferred.

**Explicitly deferred, with extension points already in place:**
- *Semantic* cross-referencing (pgvector RAG) to find which measurement(s)
  a BOQ description refers to -- linking is always a manual, explicit
  action. A trade filter on the unlinked-measurements endpoint (no trade
  classification exists on `drawing_measurements`). PDF tender BOQs (only
  `.xlsx`/`.csv` import today). See `docs/boq-reconciliation.md`.
- Clustered typology recognition (`TypologyClusterExtractor` in
  `backend/app/takeoff/geometry/stubs.py`) -- the largest of the deferred
  items, needs its own design pass.
- Visual traceability UI and non-destructive estimator overrides.
- Modules C (Procurement & Bid Leveling), D (Executive Cockpit & Pricing),
  and E (Post-Award Contract Management) — Module A's schema already leaves
  the hooks Module E needs (see `docs/module-a-data-model.md`).
