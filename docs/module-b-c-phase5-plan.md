# Phase 5 plan: semantic matching (Module B + Module C)

Per `docs/preconstruction-build-brief.md`'s Phase 5. Every default below is
this plan's own choice where the brief leaves it open.

## 0. What already exists (not rebuilt here)

- `app/integrations/embeddings.py::get_embedder()` -- ONNX (default) or vLLM
  backend, `EmbeddingBackend.embed(texts) -> list[list[float]]`. `OnnxEmbedder`
  raises `FileNotFoundError` when the model isn't provisioned at
  `$ONNX_MODEL_DIR` -- the exact gap Phase 4a's dev-sim hit.
- `app/db/types.py::EmbeddingVector(dim)` -- `pgvector.sqlalchemy.Vector`,
  384-dim default, and migration 0009's `sheet_chunks` table is the only
  existing pgvector consumer (HNSW, `vector_cosine_ops`, `m=16,
  ef_construction=64`) -- the index precedent this phase reuses verbatim.
- `app/procurement/quotation_matching.py::match_line_item()` -- rapidfuzz
  `WRatio`-only, auto-assigns `boq_line_item_id` when score >= 0.72 (C2,
  unchanged by this phase). Called from
  `app/workers/tasks/quotation_ingestion.py:490` during LLM-path extraction.
- `app/services/boq.py::link_measurement()`/`remove_measurement_link()` --
  the existing link table (`BoqLineItemMeasurement`) + audit trail Phase 5's
  "accepting a suggestion goes through the existing link table" refers to;
  unchanged.
- `app/services/boq.py::list_unlinked_measurements()` (Phase 4b: now takes
  `trade_node_id`) -- the query this phase's BOQ-to-takeoff suggestions
  layer on top of.

## 1. ONNX embedding model as a documented make target

`ai-service/embeddings/download_model.py` already does the actual export;
it just isn't wired into `make`. New target:

```
download-embedding-model:
	pip install --quiet "optimum[onnxruntime]" huggingface_hub
	python ai-service/embeddings/download_model.py --target-dir /tmp/onnx-model-export
	docker run --rm -v installtec_onnxmodels:/models -v /tmp/onnx-model-export:/src alpine cp -r /src/. /models/BAAI_bge-small-en-v1.5/
```

Run on a machine with internet access (the script's own docstring already
says this); the named volume (`installtec_onnxmodels`, already mounted at
`/models` in `backend`/`celery-worker` per `docs/deploy-deltas.md`) is what
the running stack actually reads from, so this target writes into it
directly rather than requiring a manual volume copy. Documented in
`docs/deploy-deltas.md`, not run automatically by `make up` (network
access, several-hundred-MB download -- opt-in only, matching
`bootstrap-keycloak`'s own "separate, explicit step" precedent).

If blocked (no network in this environment): unit tests use a **deterministic
fixture embedder** (below), never a real download attempt.

## 2. Degradation contract (the standing constraint made concrete)

New `app/integrations/embeddings.py::embed_best_effort(texts) -> list[list[float]] | None`:
returns `None` (never raises) when `get_embedder().embed(...)` raises
`FileNotFoundError` (model not provisioned) -- every write-path caller
(below) uses this, never the raw `embed()`, so a missing model degrades a
write to "no embedding stored," not a failed request. A genuinely
unexpected error (not `FileNotFoundError`) still propagates -- this
wrapper narrows one specific, anticipated failure mode, it doesn't swallow
bugs.

Every suggestion function (§4/§5) computes a **fuzzy score always** and a
**semantic score only when both sides have a stored embedding**; the
combined score (§4) degrades to the fuzzy score alone when semantic is
unavailable -- "everything degrades to fuzzy matching" implemented as
"semantic is an optional additive term," not a separate code path to keep
in sync.

## 3. Schema

One migration, `0025_semantic_matching.py`:

- `boq_line_items.description_embedding vector(384)` NULL + HNSW index.
  Embeds `f"{item_no} {description}"` (same text shape
  `quotation_matching._candidate_text()` already fuzzy-matches against, so
  the two scoring paths compare like with like).
- `drawing_measurements.descriptor_embedding vector(384)` NULL + HNSW
  index. Embeds a synthesized descriptor: `f"{capability} {kind} layer={layer or 'unknown'} trade={trade_name or 'unclassified'}"`,
  built from the measurement's own `capability`/`kind` plus (Phase 4b)
  `trade_node_id` resolved to a name and the *first* source entity's layer
  (from `source_entity_ids`) -- a `DrawingMeasurement` has no free-text
  description of its own, so this is genuinely synthesized, not pulled
  from a column, and documented as such (a design decision, not a bug, if
  someone goes looking for a `description` field that doesn't exist).
- `quotation_line_items.description_embedding vector(384)` NULL + HNSW
  index. Embeds `f"{vendor_item_text or ''} {vendor_description_text}"`
  (same shape `match_line_item()` already queries with).
- No separate "package items" embedding table -- a `ProcurementPackageItem`
  is a join row with no text of its own; package-scoped vendor-quote-line
  matching (§5) queries `boq_line_items.description_embedding` filtered to
  one package's linked BOQ items (`list_package_items()`, already exists),
  not a fourth embedding domain. Named explicitly here since the brief's
  own phrasing ("package items") could be read as a separate table.
- `semantic_match_feedback` (new, tenant+project-scoped, RLS-forced): the
  continuous-learning store (§6).

Write roles: embeddings are written by the same code paths that already
write `boq_line_items`/`drawing_measurements`/`quotation_line_items`
(system actor via Celery, or the existing request-path service
functions) -- no new write-role tier, these are just new nullable columns
on existing RLS-protected tables.

## 4. Suggestion scoring

```
combined_score = fuzzy_score                                   if no semantic score
combined_score = 0.6 * fuzzy_score + 0.4 * semantic_score       if both available
```

0.6/0.4 weighting (fuzzy favoured): fuzzy already has a proven, tuned
threshold (0.72, C2) on real vendor-quote text; semantic is new and
unvalidated against this domain's actual documents, so it nudges rather
than dominates ranking. `semantic_score` = cosine similarity via
pgvector's `<=>` operator, mapped from `[distance 0..2]` to `[similarity
1..-1]` as `1 - distance` (cosine distance, standard pgvector convention),
then clamped to `[0, 1]` (a negative similarity contributes nothing extra,
never a penalty on top of fuzzy). Top-k default `k=5`, configurable per
call, never persisted as "the" match -- these are **read-only suggestions**;
nothing in this phase auto-assigns a link the way C2's 0.72 auto-accept
does.

## 5. New endpoints (suggest-only; accepting reuses existing link/accept flows)

- `GET /boq-line-items/{id}/measurement-suggestions?top_k=5` -- ranks
  `list_unlinked_measurements` (same project) by `combined_score` against
  this BOQ line's `description_embedding` + fuzzy(description text,
  synthesized descriptor text). Role: same as `GET .../measurements`
  (`CurrentUser`, read-only, project-visibility via RLS) -- a suggestion
  list is not itself a mutation.
- `GET /quotation-line-items/{id}/boq-suggestions?top_k=5` -- ranks the
  quote line's own package's BOQ items (`list_package_items`) by
  `combined_score`, reusing `match_line_item`'s fuzzy scoring plus the new
  semantic term. Same read-only role tier.
- Both return `[{target_id, fuzzy_score, semantic_score: float | None,
  combined_score, rag_adjustment: float}]` (§6) sorted descending, so a
  reviewer sees exactly how a score was built, not just a final number.
- Accepting: `POST /boq-line-items/{id}/link-measurement` (exists,
  unchanged) / whatever finalizes a quotation line's `boq_line_item_id`
  (exists, unchanged) -- **this phase adds no new "accept" endpoint**, it
  only adds `POST .../feedback` (§6) alongside the existing accept/reject
  action, recording the outcome for future re-ranking.

## 6. Continuous learning (RAG re-ranking, no model training)

```
semantic_match_feedback
  id, tenant_id, project_id
  match_type          varchar   -- "boq_measurement" | "quote_boq"
  query_embedding      vector(384)   -- the query side's embedding at feedback time
  target_id            uuid          -- the suggested/accepted-or-rejected target's id
  outcome              varchar   -- "accepted" | "rejected"
  created_by, created_at
```

Written by a new `POST /semantic-matching/feedback` call, made by the
frontend (Phase 8) right alongside whichever existing accept/reject action
the reviewer already takes -- a thin, additive call, not a new workflow.
`match_type` keeps the two domains from cross-contaminating each other's
re-ranking.

**Re-ranking at suggestion time** (deliberately bounded, not a learned
model): for each candidate, find the single most-similar past feedback row
of the same `match_type` and project via `query_embedding <=> :this_query`
(pgvector nearest-neighbor, `LIMIT 1`, no threshold floor -- a distant
"nearest" match contributes ~0 anyway once scaled). If that nearest
feedback row's `target_id` equals the candidate's own id:
`rag_adjustment = +0.05 * similarity` (accepted) or `-0.05 * similarity`
(rejected); otherwise `rag_adjustment = 0`. `final_score = combined_score +
rag_adjustment`, clamped to `[0, 1]`. A small, bounded nudge (max ±0.05):
this is genuinely "re-rank based on precedent," not "let history override
the actual text/geometry similarity" -- with only a handful of tenant
examples early on, a larger weight would make suggestions swing wildly
from one or two data points.

No training, no separate model artifact -- "the model" here is just this
nearest-feedback-row lookup, re-evaluated fresh on every suggestion call.

## 7. Where embeddings get computed (write-path wiring)

- `boq_line_items`: `boq_import_service.commit_import()` (bulk) and
  `boq_service.create_line_item()`/`update_line_item()` (single) call
  `embed_best_effort()` best-effort after the row exists, same transaction.
- `drawing_measurements`: `recompute_sheet_measurements()` (already the
  single choke point every extractor/recompute path goes through, Phase
  4a/4b) computes the descriptor text and embeds it right after building
  each `Measurement` row -- no new call site needed elsewhere.
- `quotation_line_items`: wherever a line item is created (deterministic
  pricing-sheet path and LLM path both funnel through
  `app/workers/tasks/quotation_ingestion.py`) -- one shared helper, not
  duplicated per path.
- Batched, not per-row: `embed_best_effort` takes a list, so a
  multi-hundred-line BOQ import does one embedding call for all its rows,
  not N round-trips into ONNX Runtime.

## 8. Testing plan

- Unit: `embed_best_effort` degrades to `None` on `FileNotFoundError`
  (monkeypatched embedder), propagates any other exception; the
  score-combination formula (fuzzy-only, fuzzy+semantic, RAG adjustment
  clamped) against constructed inputs, no real embedder involved.
  Deterministic fixture embedder (hash-based, fixed-dimension, no model
  file) used wherever a unit test needs a real `[float]` vector shape --
  documented inline as fixture-only, never used outside tests/unit.
- Integration: suggestion endpoints rank correctly against real pgvector
  columns (seeded with the fixture embedder via a monkeypatched
  `get_embedder`, since the real ONNX model isn't available in CI either);
  feedback recorded then genuinely shifts a subsequent suggestion's rank;
  missing-embedding rows still get fuzzy-only suggestions (degradation,
  exercised for real, not just asserted in isolation); role tests at the
  lowest allowed (read access via project membership) + a denied role
  (no project membership) per the brief's rule.
- Dev simulation: extends the existing `simulate-takeoff-pdf`/BOQ-sim
  flow (or a small new `simulate-semantic-matching` CLI command) against
  the real dev stack; explicitly logs whether the real ONNX model was
  available (checked via `embed_best_effort` returning non-`None` for a
  probe string) so the build log can state plainly which path was actually
  exercised on this machine, same as Phase 4a's own VLM-reliability note.

## 9. Known gaps going in (documented up front, not discovered later)

- No cross-tenant learning -- `semantic_match_feedback` is project-scoped
  by construction (RLS), matching every other tenant-isolated table; a
  pattern learned on one client's BOQ never leaks into another's
  suggestions.
- The RAG re-ranking is a single nearest-neighbor lookup, not a proper
  k-NN-weighted vote -- chosen for simplicity and explainability (one
  precedent, one reason, shown in the response) over marginal ranking
  quality; revisit if real usage shows it's too noisy.
- `EMBEDDING_BACKEND=vllm` (the alternative backend) is not specifically
  tested by this phase's new code -- `embed_best_effort` only guards
  against `OnnxEmbedder`'s `FileNotFoundError`; a mis-configured
  `VllmEmbedder` failing for a different reason (connection refused) would
  still propagate. Acceptable: `onnx` is the default and this repo's only
  actually-deployed backend so far.
