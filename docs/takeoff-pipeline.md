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

**Implemented (Phase 2)**: DXF geometric-entity harvesting
(`app/takeoff/dxf.py::index_dxf_geometry()` -- LINE/LWPOLYLINE/ARC/INSERT,
persisted to `drawing_entities.geometry` by `index_sheets` when
`TAKEOFF_PERSIST_GEOMETRY=true`) and four real extractors registered in
`app/takeoff/geometry/`: `AlignmentExtractor`, `CorridorAreaExtractor`
(`geometry/alignment.py`), `TrenchPrismoidalVolumeExtractor`
(`geometry/volumes.py`), `PipeNetworkTopologyExtractor`
(`geometry/pipe_network.py`). See each module's docstring for its algorithm,
and `tests/unit/test_alignment_extractor.py` /
`test_volumes_extractor.py` / `test_pipe_network_extractor.py` /
`test_geometry_math.py` for hand-computed fixtures.

**Implemented (Phase 2b)**: wired into the Celery pipeline.
`extract_geometry_measurements` (queue: `ingest`) runs after `index_sheets`
in the same chord as `extract_sheet`/`embed_drawing`, gated on
`TAKEOFF_PERSIST_GEOMETRY`; it runs every extractor in the registry
(`from app.takeoff.geometry import stubs; stubs.get_registry()`) against
each sheet's persisted `drawing_entities` rows and writes the results to
`drawing_measurements` (migration `0010`, RLS same pattern as every other
takeoff table). Read-only via `GET /drawings/{id}/measurements` (optional
`sheet_id` filter).

**Key assumptions/scope limits of the Phase 2 algorithms** (see individual
module docstrings for the full reasoning):
- Planar only: no Z/3D geometry anywhere; trench depth comes from explicit
  attribute text, not 3D coordinates. Curved LWPOLYLINE segments (DXF
  "bulge" arcs) *are* handled in-plane -- see below.
- Units: native drawing units (`$INSUNITS`) throughout, converted to metres
  only when building a `Measurement` (`geometry/units.py`); `$INSUNITS=0`
  ("unitless") or an unrecognized unit yields a raw, unconverted magnitude
  with `unit="unitless"` and low confidence rather than a guessed value.
- Every layer-name hint, DXF attribute tag, and tolerance lives in
  `geometry/config.py` as a `GeometryExtractionConfig` (no hard-coded
  layer names inside the extractor classes) -- a heuristic, not a real
  convention survey. The module-level registry (`geometry/stubs.py`) only
  ever holds one, default-configured instance per capability (used as-is
  by `extract_geometry_measurements`); a real per-project override means
  constructing extractors directly with a project's config instead of
  pulling from the registry -- there's still no per-project settings store
  to read one from.
- `AlignmentExtractor`/`CorridorAreaExtractor` chain-stitch via a snap
  tolerance (default 1cm, `config.alignment.snap_tolerance_m` /
  `config.corridor.snap_tolerance_m`) and assume non-branching geometry; a
  junction (3+ entities meeting at a point) stitches unpredictably.
  LWPOLYLINE bulges (arc segments) are preserved through stitching --
  reversing a chain negates and reverses the bulge list so a curved
  alignment's true arc length (not the straight chord) is reported.
- `CorridorAreaExtractor` computes area via the shoelace formula (with the
  same bulge-aware arc correction) on the polygon traced by the left chain,
  a straight closing edge, the reversed right chain, and another straight
  closing edge -- not a vertex-by-vertex triangulation. The two sides no
  longer need matching vertex counts, only that the joined boundary traces
  a simple (non-self-intersecting) polygon; the two end-caps are always
  assumed straight.
- `TrenchPrismoidalVolumeExtractor` invents an unvalidated DXF marker
  convention (INSERT + ATTRIB tags, names configurable via
  `config.trench`; defaults `STATION`/`WIDTH_TOP`/`WIDTH_BOTTOM`/`DEPTH`/
  `TRENCH_ID`) since no cross-section convention existed anywhere in the
  codebase or SRS -- flag for review against real trench cross-section
  sheets before relying on it. Volume is computed **per segment** between
  every consecutive pair of real cross-sections
  (`geometry_math.trench_segment_volume`/`composite_trench_volume`), with
  the prismoidal formula's midpoint section synthesized by averaging each
  *dimension* (top width, bottom width, depth) of the segment's two real
  endpoints -- not by averaging their areas, and not a composite
  Simpson's-rule scheme over triads of sections (an earlier version did
  that; it's only exact for equally-spaced stations, so real, uneven
  station spacing needed a different approach).
- `PipeNetworkTopologyExtractor` uses a much larger snap tolerance (default
  1m, `config.pipe_network.snap_tolerance_m`) than the alignment
  extractors, since pipe polylines are commonly drawn to a manhole's
  rim/schematic offset rather than its exact insertion point -- also
  unvalidated against real drawings. If more than one node falls within
  tolerance of a pipe endpoint, the nearest is still reported as a best
  guess, but the measurement's `metadata` gets
  `from_node_ambiguous`/`to_node_ambiguous` + a `_candidates` list and its
  confidence is halved -- never picked silently.

DXF geometric intelligence beyond these four (most notably clustered
typology recognition -- see `TypologyClusterExtractor` in
`geometry/stubs.py`, explicitly flagged as needing its own design pass),
BOQ parsing and semantic reconciliation, raster OCR of drawing bodies, and
the visual-traceability UI remain **deferred**.

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

## Two real bugs found by end-to-end Docker verification (Phase 2)

Both predate Phase 2's geometry work; neither was caught by the existing
unit-test suite. Found while manually verifying `TAKEOFF_PERSIST_GEOMETRY`
against the real Docker stack (a real `docker compose up` + a real DXF
upload through the API, not a venv or mocked components) -- exactly the
kind of bug that class of testing exists to catch.

**`index_sheets`'s Celery-forwarded actor had no roles, so real (non-system)
ingestion could never write anything.** `trigger_ingest()`
(`app/services/takeoff.py`) forwarded `ctx.tenant_id` and `ctx.user_id` to
the `index_sheets` task, but never `ctx.roles`. `build_worker_context()`
only sets `is_system=True` (which bypasses every RLS write policy) when
`actor_user_id` is `None`; with a real actor but an empty role set, the
`extraction_jobs` table's `WITH CHECK (... AND app_has_role(...))` INSERT
policy can never pass. Every request-triggered ingestion failed at its
very first database write with `InsufficientPrivilegeError`, silently
swallowed by Celery's own error logging -- a purely synthetic/venv-based
test would never trigger this path, since it doesn't go through the real
JWT → `RequestContext` → Celery `.delay()` → RLS chain at all. Fixed by
forwarding `list(ctx.roles)` to `index_sheets.delay(...)` and threading an
`actor_roles` parameter through to `build_worker_context()`.

**DXF byte-stream reads silently corrupted every real (CRLF-terminated)
file.** `index_dxf()`/`index_dxf_geometry()` both parsed via
`ezdxf.read(io.StringIO(data.decode(...)))`. A real DXF file's lines are
CRLF-terminated (confirmed against ezdxf's own `saveas()` output); `ezdxf`'s
reader expects `readline()` to hand back lines with the terminator already
stripped, the way a real text-mode file does. `io.StringIO` wrapping an
already-decoded string does *not* do that (it only special-cases `"\n"`),
so every line kept a trailing `"\r"`, and `ezdxf` silently returned a
near-empty document (its internal entity database an order of magnitude
smaller than the real file, every layout's entity count exactly 0) instead
of raising. This means the *original* Phase 1B `index_dxf()` likely never
successfully parsed a single real (non-synthetic) DXF file, in any
deployment -- every existing DXF unit-test fixture built its bytes via
`doc.write(io.StringIO())` (an in-memory buffer, LF-only), which never
produces CRLF and so never exercised this path at all. Fixed by centralizing
DXF parsing in `_read_dxf_document()`, which uses
`io.TextIOWrapper(io.BytesIO(data), newline=None)` (universal newlines,
matching how `ezdxf.readfile()` itself reads a real file) instead. Every
DXF test fixture now builds its bytes via a real `doc.saveas()` to a temp
file rather than `doc.write(io.StringIO())`, specifically so this class of
bug can't silently reappear -- see `test_index_dxf_geometry_survives_crlf_
line_endings` / `test_fixture_is_crlf_terminated_like_a_real_dxf_file` in
`tests/unit/test_dxf_geometry.py`. `saveas()` alone wasn't quite enough,
though: it opens the file in default text mode, so it only actually
produces CRLF bytes on Windows -- on Linux (the real backend container,
and presumably CI) it writes LF only, silently de-fanging the regression
test on exactly the platform that matters most. Caught by running the full
suite in a real `python:3.12-slim` container as part of verifying this
work, not just locally on Windows. The fixture now forces CRLF explicitly
after `saveas()` if the platform didn't already produce it.

Also found while wiring this up: `TAKEOFF_PERSIST_GEOMETRY` was a
`Settings()` field with no Compose wiring at all -- setting it in `.env`
had zero effect on any container. Fixed in `deploy/docker-compose.yml`:
added to both the (misleadingly-named -- see below) `x-backend-env` anchor
used by the `celery-*` services, and separately to `backend`'s own
independent environment list.

**Compose footgun, fixed in two passes:** invoking `docker-compose.test.yml`
and the main `docker-compose.yml`/`docker-compose.override.dev.yml` from
the repo root both defaulted to the Compose project name `deploy` (the
directory holding the compose files) when no `-p`/`--project-name` was
given -- running `docker compose -f deploy/docker-compose.test.yml up`
while the main dev stack was already up silently **recreated**
`postgres`/`redis`/`seaweedfs` under the test file's ephemeral (tmpfs)
definitions, destroying those containers (though not their named volumes,
which survived and reattached correctly to a subsequent `make up`) --
happened once during Phase 2 verification and was recovered from. First
pass fixed the *project name* collision: `COMPOSE_TEST` in the Makefile
pins `-p installtec-test`. That wasn't the whole story -- the test
Postgres was **also** published at the same host port (`5433:5432`) as
the dev stack's own Postgres, so starting the test stack while dev was up
failed outright trying to bind a port already in use, independent of the
project-name fix (a second, real incident: `make test-integration` failed
this way in practice). Second pass, in `deploy/docker-compose.test.yml`:
Postgres/Redis host port mappings are **removed entirely** (see below for
why they were never actually needed), and SeaweedFS/mock-vllm moved to a
dedicated `58xxx`/`59xxx` block, away from both the dev stack's ports and
common local defaults.

The main `COMPOSE` variable deliberately was **not** given a `-p` in
either pass -- its volumes (`pgdata`/`swdata`/`onnxmodels`) have no
explicit `name:` override, so they're project-name-prefixed; changing that
project name would silently start every `make up` against brand-new,
empty volumes instead of the real dev data. `backend`'s `environment:`
block still does not use the `x-backend-env` YAML anchor at all -- it's a
second, fully-duplicated env-var list (kept in sync with the anchor by
hand); adding a var to one and not the other is exactly the trap the
`TAKEOFF_PERSIST_GEOMETRY` wiring above fell into. Not fixed here (would
mean restructuring `backend`'s whole service block) -- worth doing
separately.

**What `tests/integration`/`tests/api` actually connect to (audited when
fixing the port collision above): nothing in `docker-compose.test.yml` at
all.** `tests/conftest.py`'s `postgres_container`/`redis_container`
fixtures use the `testcontainers` Python library to spin up their own
separate, ephemeral, dynamically-ported containers directly via the
Docker API -- never `docker-compose.test.yml`'s `postgres`/`redis`
services. And every test that touches `S3_ENDPOINT`/`VLLM_API_BASE` sets
it to an intentionally-unreachable placeholder (`http://s3.invalid`,
`http://vllm.invalid/v1`) rather than a real endpoint, so `seaweedfs`/
`mock-vllm` are never called either. `docker compose ... up -d` in
`make test-integration` was, and remains, dead weight for every test that
exists today -- kept (with corrected, non-colliding ports) for a future
test that talks to SeaweedFS/mock-vllm directly over HTTP, since that's a
plausible thing to want and the services cost nothing sitting idle.
Because nothing reads a fixed DSN for Postgres/Redis, there was already no
way for a test to *silently* hit the dev database by construction -- but
as a hard, load-bearing safety net against a future refactor changing that
(e.g. reading a DSN from an environment that happens to have `deploy/.env`
sourced into it), `tests/conftest.py` now asserts the testcontainers-
provisioned host/port/dbname it's about to use doesn't match the dev
stack's known identity (port `5433`, db `installtec_core`, or the
compose-internal hostnames `postgres`/`redis`) before doing anything else,
raising immediately if it ever does.

**`make test-integration` on Windows**: `cd backend && python -m pytest`
(what it did until now) needs a host Python matching the `>=3.12,<3.13`
pin plus the `dev` extras installed into it -- neither is guaranteed to
exist. Confirmed on the machine this was developed on: only Python 3.14 is
on `PATH` (no 3.12 at all), and `testcontainers` isn't installed. Fixed by
running pytest inside a throwaway `python:3.12-slim` container instead
(matching the pinned interpreter exactly regardless of host setup),
attached to `$(TEST_PROJECT_NAME)_default` with the host's Docker socket
mounted in (Docker-outside-of-Docker -- needed because `testcontainers`
talks to the same Docker daemon the host uses, not to anything nested
inside the pytest container) and a persistent pip-cache volume so repeat
runs mostly skip re-downloading dependencies. Verified as far as
possible without actually invoking it end-to-end: the container starts,
attaches to the right network, installs the `dev` extras, and collects all
43 integration tests cleanly; the Docker-socket mount itself couldn't be
exercised in the environment this was developed in (a sandboxed agent
session, which refuses to mount the Docker socket into a container as a
containment-escape risk) -- run `make test-integration` to confirm the
last mile.

**Two more real bugs found verifying Phase 3 (BOQ reconciliation) against
the live stack, both pre-existing, unrelated to BOQ reconciliation
specifically:**

- `app.services.takeoff.trigger_ingest()` forwarded `ctx.user_id` but not
  `ctx.roles` to the `index_sheets` Celery task. `build_worker_context()`
  only sets `is_system=True` (bypassing every RLS write policy) when
  `actor_user_id` is `None`; with a real actor but an empty role set, the
  `extraction_jobs` INSERT's `app_has_role(...)` WITH CHECK could never
  pass -- every real (non-system) ingestion failed at its very first
  write. Fixed by forwarding `list(ctx.roles)` and threading an
  `actor_roles` parameter through `build_worker_context()`. See
  `tests/integration/test_trigger_ingest_roles.py`, which also confirms
  the fix forwards *exactly* the actor's roles (no elevation) and that a
  non-member's `get_drawing()` read is still silently RLS-filtered to
  nothing (a clean 404, never reaching Celery at all) -- verified directly
  against the live stack (estimator1, member vs non-member) before
  writing the test, both directions.
- `upload_drawing()` had no project-membership pre-check, unlike
  `trigger_ingest()` (whose `get_drawing()` SELECT is naturally
  RLS-filtered before any write happens). An INSERT has no such prior read
  to be filtered by -- its `WITH CHECK` fails hard, and there was no
  handler for that Postgres exception class (`ProgrammingError`, unlike
  the constraint violations `IntegrityError` already gets translated to a
  clean response for), so an estimator/lead_estimator without project
  membership got an unhandled 500 on upload, after already streaming the
  file to S3. Fixed with `assert_can_see_project()`
  (`app/services/projects.py`, mirrors `app_can_see_project()` exactly) --
  a clean 403 before any S3 write. Verified against the live stack in both
  directions (403 without membership, 201 after `POST /projects/{id}/
  members`).

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
