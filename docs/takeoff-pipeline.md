# Module B: takeoff ingestion pipeline

## Scope of this slice

**Implemented**: upload → SeaweedFS; PDF page indexing (text + title-block
candidate region) and DXF layout/entity/text indexing via `ezdxf`;
multi-sheet indexing; VLM title-block extraction (text or image path)
against vLLM's OpenAI-compatible API with guided JSON decoding; scale-text
parsing (regex) with a VLM disambiguation fallback; manual two-point scale
calibration; chunking + ONNX (CPU) embeddings + pgvector storage with an
HNSW index; a thin similarity-probe endpoint
(`POST /projects/{id}/sheets:search`); per-job status tracking with
idempotent replay.

**Deferred** (see `app/takeoff/geometry/stubs.py` for the registered-but-
disabled extension points and their intended algorithms): DXF geometric
intelligence (alignment/corridor/trench-volume/pipe-network extraction),
clustered typology recognition, BOQ parsing and semantic reconciliation,
raster OCR of drawing bodies, and the visual-traceability UI. None of these
need a pipeline redesign to add later — they're new Celery tasks plus one
migration flipping `TAKEOFF_PERSIST_GEOMETRY` on.

## The task graph (`app/workers/tasks/takeoff.py`)

```
POST /projects/{id}/drawings          streams to S3, sha256-dedupes
POST /drawings/{id}/ingest            enqueues index_sheets

index_sheets (queue: ingest)
  PDF: pypdf/pdfplumber page count, per-page text, title-block region text,
       is_raster flag (< 20 extracted chars => scanned)
  DXF: ezdxf modelspace/paperspace layouts, $INSUNITS, TEXT/MTEXT/ATTRIB
       harvest into drawing_entities (geometric entities gated behind
       TAKEOFF_PERSIST_GEOMETRY, default off)
  -> chord(
       group(extract_sheet(sheet) for each sheet)   (queue: vlm, concurrency 2)
       embed_drawing(drawing)                        (queue: embed)
     , finalize_drawing(drawing))                     (queue: ingest)

extract_sheet: builds candidate_text (raw_text tail or DXF title-block
  ATTRIBs); if raster or no usable text, renders the page to PNG
  (pypdfium2) and crops the title-block region for the VLM image path;
  calls titleblock.extract_title_block() (guided JSON against
  ai-service/schemas/title_block.schema.json); parses scale_text via
  scale.parse_scale_text(), falling back to scale.disambiguate_via_vlm()
  when confidence is 0.

embed_drawing: chunks each sheet (title block + windowed body text +
  per-layer entity-text groups), embeds via the ONNX backend (CPU, default —
  see A8), bulk-inserts sheet_chunks.

finalize_drawing: status = 'ready' or 'partial' depending on whether any
  extraction_jobs row failed.
```

Every task upserts its own `extraction_jobs(drawing_id, sheet_id, job_type)`
row to `running` first and returns early if a prior attempt already
succeeded — a chain replay after a worker crash is safe.
`task_acks_late=True`, `worker_prefetch_multiplier=1`,
`task_reject_on_worker_lost=True`, exponential backoff with jitter on
`ConnectionError`/`TimeoutError`.

## Design simplification vs. the original sketch

Tasks take `tenant_id` (and `actor_user_id`/`actor_roles` where an audit
trail needs an attributable actor) as **explicit arguments**, rather than a
custom `ContextTask` pulling context from Celery task headers. This is more
verbose per call site but avoids a real footgun: Celery header propagation
across retries and chains is an easy place to silently lose context, and an
explicit argument is visible in Flower/logs without decoding anything.
`app/workers/base.py::build_worker_context()` /
`with_worker_session()` turn those arguments into the same
`RequestContext` + RLS-scoped session that request code uses.

## vLLM: mock today, real GPU later

`VLLM_API_BASE` defaults to the `vllm` compose service, which is currently
`ai-service/mock-vllm` (a ~100-line FastAPI stand-in returning
schema-shaped placeholder JSON for any `guided_json`/`response_format`
request) rather than the real `vllm/vllm-openai:latest` image — no GPU host
was available at build time. The real image + GPU reservation is defined as
a separate `vllm-gpu` service gated behind the `gpu` Compose profile; switch
by running `docker compose --profile gpu up -d vllm-gpu` and pointing
`VLLM_API_BASE` at it. The request/response contract
(`app/integrations/vllm.py`) is identical either way — nothing in
`app/takeoff/` needs to change.

## Packaging gotcha: `ai-service/` must ship in the backend image

`app/takeoff/prompts.py` resolves `ai-service/prompts/*.j2` and
`ai-service/schemas/*.json` relative to the **container root**
(`Path(__file__).resolve().parents[3]`, which lands on `/` inside the
image). The SRS's literal `backend: build: ../backend` scopes the Docker
build context to `backend/` alone, which **never includes `ai-service/` at
all** — the real production/dev container would have booted fine (nothing
imports these files at module-load time) but crashed the first time
`extract_title_block()` or `disambiguate_via_vlm()` actually ran. Fixed by
widening the build context to the repo root
(`deploy/docker-compose.yml`'s backend/celery services now use
`context: .. / dockerfile: backend/Dockerfile`) and having
`backend/Dockerfile` explicitly `COPY ai-service/prompts /ai-service/prompts`
and `COPY ai-service/schemas /ai-service/schemas`. Verified by actually
importing `app.takeoff.prompts` and rendering a template inside the real
built image, not just inside a dev-mode bind mount that happened to have
the whole repo checked out.

## Embeddings: ONNX by default (decision A8)

`EMBEDDING_BACKEND=onnx` (default) keeps the GPU free for the
vision-language model — `app/integrations/embeddings.py::OnnxEmbedder` runs
`BAAI/bge-small-en-v1.5` (384-dim) on CPU via ONNX Runtime, mean-pooled and
L2-normalized. Model files are provisioned offline via
`ai-service/embeddings/download_model.py` into `ONNX_MODEL_DIR`. An
alternative `VllmEmbedder` exists for `EMBEDDING_BACKEND=vllm` deployments
that would rather not run a second CPU inference path, but it bridges
sync→async via `asyncio.run()` internally and is only safe to call from a
plain sync context with no event loop already running in that thread —
document this constraint before switching backends. `app/db/types.py`'s
`EmbeddingVector()` column type uses a literal default dimension (384),
*not* a live `get_settings()` call, specifically so importing `app.models`
never requires a configured environment (an earlier version broke every
pure unit test this way — see `db/types.py`'s docstring).
