# Module B Phase 4 plan: remaining takeoff features

Phase 4 of `docs/preconstruction-build-brief.md`. This phase is large
enough that the brief's own §0.1 explicitly allows splitting it — three
branches, merged in sequence:

- **4a** — vector PDF geometry extraction + multi-signal scale detection +
  recompute-on-calibration (brief items 1, 2).
- **4b** — non-destructive overrides + split-pane traceability + trade
  classification of measurements (brief items 3, 4, 5).
- **4c** — clustered typology recognition (brief item 6) — the codebase's
  own `geometry/stubs.py` already flags this as *"the largest of the
  deferred items, likely needs its own design pass"*, which this plan
  treats as confirmation, not a surprise.

Status: **proposal, committed then built straight away per 0.1.**

Researched first (not guessed): `geometry/config.py`, `dxf.py`,
`geometry/{entities,base,geometry_math,alignment,pipe_network,volumes,
stubs}.py`, `scale.py`, `titleblock.py`, `pdf.py`, `models/takeoff.py`,
`services/takeoff.py`, `workers/tasks/takeoff.py`, current migration head
(0020, so this phase starts at 0021). Findings that shape every decision
below are cited inline as `(found: ...)`.

## 4a. Vector PDF geometry extraction + multi-signal scale detection

### PDF geometry extraction

`pdfplumber`/`pypdfium2` are already real dependencies; **pdfplumber is
currently only used for text**, never `page.lines`/`page.rects`/
`page.curves` `(found: app/takeoff/pdf.py has no vector-geometry call at
all)`. New function `index_pdf_geometry(data: bytes, mapping_rules:
list[PdfLayerRule]) -> dict[str, list[GeometricEntity]]` in
`app/takeoff/pdf.py`, keyed by page label — mirrors
`dxf.py::index_dxf_geometry`'s exact return shape so every existing
extractor (`alignment.py`, `pipe_network.py`, `volumes.py`) works
**unchanged** against PDF-sourced entities, because they only ever look at
`GeometricEntity.layer` `(found: entities.py's GeometricEntity.layer is
the one field every extractor filters on via config.layer_hints)`.

PDFs have no layers, so `GeometricEntity.layer` is **synthesized** per
project from a new, small rule table rather than left blank:

```
pdf_layer_mapping_rules       -- project-scoped, ordered, first match wins
  id, tenant_id, project_id
  target_layer        varchar          -- the synthetic layer name written to GeometricEntity.layer
  stroke_color         varchar, nullable    -- hex, e.g. "#FF0000"
  min_line_width, max_line_width  numeric, nullable
  dash_pattern          varchar, nullable   -- "solid" | "dashed" | "dotted" (simplified categorical, from pdfplumber's dash array)
  ocg_name_contains     varchar, nullable   -- substring match against the optional-content-group label, when the PDF has one
  priority               int
```

A default (no rules configured) synthesizes a single layer `"UNMAPPED"` so
extraction never silently produces zero entities on an unconfigured
project — it just produces nothing usable until someone configures rules,
same failure mode as an unmapped DXF layer today.

**OCG**: pdfplumber (via pdfminer.six underneath) exposes optional-content
membership per drawn object when the PDF declares OCGs at all — most
exported CAD-to-PDF files don't. When absent, `ocg_name_contains` rules
simply never match; this is a real, silent degradation the brief
anticipates ("optional... OCG"), not an error.

**Multi-sheet indexing**: already exists (`index_pdf`'s `PdfPageInfo` per
page, `(found: pdf.py)`) — `index_pdf_geometry` reuses the same per-page
loop, adding geometry alongside the text already indexed there, not a
parallel pass.

**Scanned/raster pages**: `PdfPageInfo.is_raster` already exists (a
20-character text threshold) `(found: pdf.py)`. `index_pdf_geometry`
skips geometry extraction entirely for a page already flagged raster and
records why (a page-level `flagged_raster: true` field on the result) --
never attempts vector extraction on something that's actually a scanned
image, and never guesses a substitute.

**Wiring**: `workers/tasks/takeoff.py::_index_sheets_body`'s PDF branch
currently only calls `index_pdf` `(found: line ~147-162, no geometry
call)`. Adds the `index_pdf_geometry` call there, gated behind the same
`settings.takeoff_persist_geometry` flag the DXF branch already uses, so
this is additive and opt-in exactly like DXF's own geometry persistence.

### Multi-signal scale detection

`scale.py`'s own docstring already names the two missing signals:
*"Dimension-entity cross-checking and scale-bar image detection... not
implemented in this slice"* `(found: scale.py docstring)`. Both work in
**vector space** (entity/text coordinates), not pixels — consistent with
this being vector extraction throughout, and avoiding a much larger
image-CV dependency:

1. **Scale annotation** (existing, unchanged): `parse_scale_text`.
2. **Dimension-text-vs-measured-length**: for a DIMENSION entity (DXF) or
   a text label matching a length pattern positioned near a line/leader
   (PDF — no true DIMENSION objects), compute the geometric distance
   between the two referenced points in drawing units and solve for the
   ratio implied by `stated_length / drawing_distance`. Each such pair is
   one candidate signal.
3. **Scale-bar detection**: look for a baseline line with evenly-spaced
   short perpendicular tick segments, paired with nearby text forming an
   arithmetic numeric sequence (`0, x, 2x, 3x, ...`) — a real, common
   scale-bar shape, detected from the same line/text entities already
   extracted, not a raster pattern search.
4. **Units-based fallback** (existing, `derive_scale_from_units`,
   unchanged).

**Fusion**: `estimate_scale(signals: list[ScaleSignal]) -> ScaleEstimate`
— each signal carries `(ratio, confidence, source)`; the combined estimate
is the confidence-weighted signal, and `disagreement = true` when two
signals with confidence ≥ 0.5 disagree by more than 10% — surfaced on
`DrawingSheet` (`scale_disagreement: bool`, new column) so a reviewer sees
it rather than the system silently picking one. Never auto-resolves a
disagreement; a human (or the existing VLM disambiguation fallback, still
called when *every* signal is empty, unchanged) does.

### Manual two-point calibration → recompute

`set_manual_scale` **already exists and is fully audited**
`(found: services/takeoff.py:128)` but (a) has no history — it overwrites
`DrawingSheet.scale_ratio` in place, so a reviewer can't see or revert to
what auto-detection found, and (b) never touches `drawing_measurements`,
so dependent measurements silently go stale relative to the new scale.
Both fixed:

- New table `sheet_scale_calibrations` (append-only, like an audit sub-log
  scoped to this one concern): `sheet_id, ratio, source, confidence,
  set_by, set_at, note`. Every scale change — auto-detected fusion result
  *or* manual two-point — writes a row here; `DrawingSheet.scale_ratio`
  etc. always mirrors the latest row (current-value columns kept for
  every other query's sake, history is additive).
- `set_manual_scale` becomes a thin domain wrapper that (1) writes the
  calibration row, (2) updates the sheet's current scale, (3) re-enqueues
  `extract_geometry_measurements_task` for that sheet so dependent
  `drawing_measurements` recompute against the new ratio — the existing
  task already derives measurements from persisted `DrawingEntity`
  geometry `(found: workers/tasks/takeoff.py, _row_to_geometric_entity)`,
  so recomputing is calling it again, not new logic; it's made idempotent
  per sheet (replace, not append, that sheet's measurement rows) if it
  isn't already.
- A revert is just "apply the previous calibration row's values through
  the same path" — no separate revert mechanism needed.

## 4b. Non-destructive overrides, traceability, trade classification

### Overrides

New table, same reasoning as D1/Module B's own prior split of BOQ
reconciliation state off `boq_line_items` `(found: migration 0014's
docstring, the precedent this mirrors)` — an override needs a looser
write policy (`estimator+`, ordinary operational work) than the
measurement row's own extractor-owned write policy:

```
drawing_measurement_overrides
  id, tenant_id, measurement_id FK, project_id
  value, unit, note (required -- "why")
  overridden_by, overridden_at
  reverted_by, reverted_at   -- nullable; a revert sets these, never deletes the row
```

At most one **active** row (`reverted_at IS NULL`) per measurement,
enforced the same way as `bid_settlements`' one-current-version partial
unique index. `effective_value` = the active override's value if one
exists, else the measurement's own `value` — exposed as a property on
`DrawingMeasurement` reads, same pattern as `BoqLineItem.variance` reading
through to its reconciliation row today `(found: models/boq.py properties)`.
**`app/boq/reconciliation.py` is updated to sum `effective_value`, not
`value`** — the one behavioural change this ripples into, and the reason
this can't be purely additive.

### Traceability for the split pane

`DrawingMeasurement` already references its source geometry
(`source_entity_ids` JSONB) and `DrawingEntity` already carries full
bbox + geometry `(found: models/takeoff.py)` — most of item 4 is
**exposing existing data**, not new storage. Two additions:

- `DrawingMeasurement` gains `source_sheet_id` (FK, denormalized — every
  source entity is already on one sheet, but a direct FK avoids a join for
  the split pane's common case) and a denormalized bounding box
  (`bbox_min_x/min_y/max_x/max_y`, nullable, the union of its source
  entities' boxes) computed once when the measurement is created/recomputed.
- New endpoint `GET /drawing-sheets/{sheet_id}/entities` (optional
  `bbox_min_x`/`bbox_min_y`/`bbox_max_x`/`bbox_max_y` query params —
  intersecting, not just-contained, so a region straddling a boundary
  still returns what overlaps it) returning `DrawingEntity` rows
  (geometry + bbox already on the row) for the frontend to render.

### Trade classification of measurements

Mirrors `BoqTolerance`'s exact per-project/per-override shape
`(found: BoqTolerance — nullable trade_node_id, NULLS NOT DISTINCT unique
on (project_id, trade_node_id))`, but keyed on layer/style instead of
trade directly:

```
drawing_layer_trade_mappings
  id, tenant_id, project_id
  layer_pattern    varchar          -- matched against GeometricEntity.layer (case-insensitive substring, simple and predictable)
  trade_node_id    FK -> trade_nodes
  unique (project_id, layer_pattern)
```

`DrawingMeasurement` gains a nullable `trade_node_id`, resolved from its
source entities' layers against this table at
creation/recompute time (first matching pattern wins; no match leaves it
NULL — never guessed). `list_unlinked_measurements`'s own docstring
already names this exact gap and why it was deferred
`(found: boq_service.py:397-405)` — its `trade_node_id` query filter is
now a straightforward `WHERE` addition, no design change needed there.

## 4c. Clustered typology recognition

Confirmed via the codebase's own words, not assumed: `geometry/stubs.py`'s
`TypologyClusterExtractor` already exists as a named, raising-
`NotImplementedError` placeholder, its docstring calling this out as the
largest deferred item. This plan gives it a real, if intentionally
bounded, implementation.

### Detection

- **DXF**: group `GeometricEntity` rows sharing the same non-null
  `block_name` (already captured today) *and* a matching geometric
  signature — `(bounding_box_aspect_ratio, entity_count,
  total_edge_length)`, each rounded to a tolerance band (configurable,
  default 2%). Two block instances differing only by placement (position/
  rotation) still match; different geometry doesn't.
- **PDF**: no block references exist, so grouping is by a **normalised
  geometry hash**: for a connected cluster of entities in a bounded
  region, translate all vertices so the region's centroid is the origin,
  round to a tolerance grid (configurable, default 5% of the region's own
  diagonal — self-scaling, not a fixed distance), and hash the sorted,
  rounded vertex list. Matching hashes across regions/pages become one
  cluster's instances.

### Confirmation workflow (clusters are proposals until confirmed)

```
typology_clusters                  -- one row per detected/confirmed cluster
  id, tenant_id, project_id
  status              proposed | confirmed | rejected
  master_instance_id  -- which detected instance is the reference unit (estimator's pick, defaults to the first found)
  detection_method     dxf_block | pdf_geometry_hash
  tolerance_pct        numeric     -- what was actually used, for traceability
  confirmed_by, confirmed_at

typology_cluster_instances
  id, tenant_id, cluster_id FK
  sheet_id, bbox_*                 -- where this instance is, for the split pane
  group_label                       -- e.g. "type A", "type B" -- estimator-assigned on confirm, defaults to "type A" for the master's own group
  instance_count                    -- how many identical repeats this *group* represents (a whole group, not per-instance-row -- see rollup below)

typology_variant_deltas
  id, tenant_id, cluster_id FK
  group_label                       -- which non-master group this delta applies to
  description                       -- e.g. "+1 maid room" (free text, human-facing)
  boq_line_item_id     FK, nullable -- an explicit quantity delta against a real BOQ item, when the delta is quantifiable this way
  quantity_delta        numeric, nullable
  unit                   varchar, nullable
```

**Master quantification**: the master instance's own BOQ/measurement
linkage (existing `BoqLineItemMeasurement`/reconciliation machinery,
unchanged) is quantified in the normal, detailed way an estimator already
works — nothing new there; a cluster just groups which BOQ items belong to
"the master."

**Rollup** (the traceable total the brief asks for):
`total(item) = master_quantity(item) × Σ(group.instance_count for every
group) + Σ(delta.quantity_delta × group.instance_count for every group
whose deltas touch this item)` — computed on read, not persisted, so it's
always consistent with the master; a change to the master's own measured
quantity is immediately reflected next time this is read, satisfying "a
change to the master recomputes the cluster" without a separate recompute
step to forget to run.

### Endpoints (both 4b and 4c, summarized — full signatures at
implementation time, following D1-D3's established role/audit conventions)

- `POST /projects/{id}/typology-clusters/detect` — runs detection, creates
  `proposed` clusters (`lead_estimator+`, matches BOQ's own structural-
  write role, audited).
- `POST /typology-clusters/{id}/confirm` — sets master + group labels +
  deltas, moves to `confirmed` (`lead_estimator+`, audited).
- `GET /typology-clusters/{id}/rollup` — the computed totals above.
- `POST /drawing-measurements/{id}/override`, `POST .../override/{id}/revert`.
- `GET /drawing-sheets/{sheet_id}/entities` (region query, §4b).
- `PUT /projects/{id}/pdf-layer-mapping-rules`, `PUT .../drawing-layer-trade-mappings` (config CRUD, `lead_estimator+`).

## Testing plan (all three sub-phases)

- Unit: synthetic PDFs (`pdfplumber`-readable, built with a plain PDF
  library or hand-built content streams) covering colour/width/dash/OCG
  mapping rules; the scale-signal fusion function against constructed
  signal sets (agreement, disagreement, all-empty); the typology hash
  function's tolerance behaviour (near-duplicates match, real
  differences don't) — mirrors `test_dxf_geometry.py`'s existing
  synthetic-fixture convention.
- Integration: override → effective_value → reconciliation sum changes
  and reverts back; calibration change actually replaces (not
  duplicates) a sheet's measurement rows; trade-mapping filter on
  `measurements:unlinked`; typology confirm → rollup arithmetic exactly.
  Role tests at the lowest allowed + a denied role per permission.
- Dev simulation: a synthetic multi-sheet PDF with two near-identical
  "unit" regions (a manual typology fixture) run through ingest → extract
  → detect clusters → confirm → rollup, against the real dev stack.

## Explicitly out of scope for this phase

- Real scale-bar detection against a *rasterized* image (pixel pattern
  matching) — the vector-space heuristic above is what's built; a raster
  fallback for a scanned scale bar is a future, separate slice.
- A full rules-editor UI for PDF layer mapping / trade mapping (Phase 8
  admin screens cover the UI; this phase is the API + storage).
