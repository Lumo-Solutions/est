# Phase 8b plan: projects, drawings, takeoff split-pane

Per `docs/module-frontend-phase8-plan.md` §2's sub-phase breakdown.

## 0. What already exists (confirmed by reading the backend code)

Read `app/api/v1/routes/projects.py`/`drawings.py`, `app/schemas/projects.py`/
`drawings.py`, and `app/services/takeoff.py` in full before writing this.

- **Projects**: `GET/POST /projects`, `GET /projects/{id}`, `PATCH
  /projects/{id}/location`, `POST /projects/{id}/members` -- all already
  exposed, nothing missing.
- **Drawings/takeoff**: upload, ingest-trigger, get-by-id, list-jobs,
  get-sheet-by-index, manual-scale set/list/revert, measurements list,
  presigned download (whole-document), sheet search, measurement
  override/revert, drawing-entities-in-region, layer-trade-mapping
  CRUD -- all already exposed.
- **Two real, narrow gaps** (confirmed by grepping `services/takeoff.py`
  for every `async def` -- neither exists, not just unexposed):
  1. No way to list all drawings for a project (only upload, which
     returns one, and get-by-id for a single known drawing). The project
     detail / drawing-upload screen needs this. **New**: `GET
     /projects/{id}/drawings` -> `list_drawings()`.
  2. No way to list all sheets of a drawing (only `get_sheet(drawing_id,
     sheet_index)` for one at a time). The sheet-index screen needs this.
     **New**: `GET /drawings/{id}/sheets` -> `list_sheets()`.
  Both are plain, RLS-scoped reads mirroring `list_jobs`/`list_measurements`'s
  own shape exactly (`select(...).where(...).order_by(...)`, no explicit
  tenant filter -- RLS handles that) -- reusing the existing `DrawingOut`/
  `DrawingSheetOut` response models, no new schema types.
- **`docs/module-frontend-phase8-plan.md` §1's DXF-to-SVG assumption was
  wrong** and is corrected here: it assumed a new backend SVG-rendering
  endpoint would likely be needed. It is not. `GET
  /drawing-sheets/{sheet_id}/entities` already returns every entity's
  `geometry` dict (`vertices`, `bulges`, `center`/`radius`,
  `start_angle_deg`/`end_angle_deg`) -- everything needed to render
  lines/polylines-with-bulge/arcs/circles as SVG paths **client-side**.
  DXF sheets are always vector (`is_raster=False`), so no raster fallback
  is needed for them. The SVG is built in the frontend from this existing
  endpoint; no new backend rendering endpoint is added.
  - Caveat found while confirming this: entity persistence is gated by
    `TAKEOFF_PERSIST_GEOMETRY` (default `false`). Dev-verifying the DXF
    viewer needs `TAKEOFF_PERSIST_GEOMETRY=true` in `deploy/.env`, or the
    entities list comes back empty for every DXF sheet -- appended to
    `.env` (a `.env.example` default addition, per the brief's own
    exception for appending to `.env`/`.env.example`), not changed
    silently only in the running container.
- PDF sheets: `download_drawing_endpoint`'s presigned URL is
  whole-document (the entire uploaded PDF, not per-sheet) -- exactly what
  pdf.js wants; `sheet_index + 1` is the PDF page number pdf.js navigates
  to. `DrawingMeasurementOut.confidence` (0-1) is the only confidence
  field -- used directly for the overlay's confidence indicator.

## 1. New backend surface (this sub-phase)

- `app/services/takeoff.py::list_drawings(session, project_id)` /
  `list_sheets(session, drawing_id)` -- read-only, same shape as
  neighbouring list functions.
- Two `GET`-only routes in `drawings.py` (`CurrentUser`, matching every
  other read in this router). No new roles, no schema changes.
- Integration tests: RLS read-visibility for both (project member vs
  non-member), mirroring Module E's own `list_boq_revisions`-style test.

## 2. Frontend screens

- **Projects list** (`/`): table of `GET /projects`; a "New project" form
  (code/name/client/tender ref/base currency) for `bd_director`+ roles,
  gated by `filterVisibleNavItems`-style role check on the button itself
  (the create call still 403s server-side for anyone else -- UI hiding is
  a nicety only).
- **Project detail** (`/projects/:projectId`): `GET /projects/{id}`
  summary card (code, client, status, location) + the new drawings list
  (`GET /projects/{id}/drawings`) with per-drawing status
  (`queued`/`indexing`/`extracting`/`embedding`/`ready`/`failed`) and a
  link into its sheet index; an upload control (`POST
  /projects/{id}/drawings` then `POST /drawings/{id}/ingest`).
- **Sheet index** (`/projects/:projectId/drawings/:drawingId`): the new
  `GET /drawings/{id}/sheets` list, one row per sheet with title-block
  fields (drawing number/title/revision/discipline/scale) and extraction
  status; each row links into the split-pane viewer.
- **Takeoff split-pane** (`/projects/:projectId/drawings/:drawingId/sheets/:sheetIndex`):
  - Left pane: the drawing itself. PDF sheets render via `pdf.js`
    (bundled) against the whole-document presigned URL, navigated to
    page `sheetIndex + 1`. DXF sheets render as an inline SVG built
    client-side from `GET /drawing-sheets/{sheetId}/entities`'s geometry
    (a small pure `entitiesToSvgPaths()` helper, unit-tested against a
    few synthetic entities: a line, an arc, a bulged polyline).
  - Right pane / overlay: `GET /drawings/{id}/measurements?sheet_id=...`
    plotted at their `bbox_min/max_x/y` (already in the same coordinate
    space as the entities), colour-coded by `confidence` (three bands,
    thresholds are a UI-only convention documented in the component, not
    a business rule); clicking one shows its `value`/`unit`/`effective_value`
    and, if overridden, the override note.
  - Non-destructive override: a form (`value`, `unit`, `note` -- all
    required per `MeasurementOverrideIn`) posting to
    `/drawing-measurements/{id}/override`; a "revert" button posting to
    `.../override/revert`. The raw extracted `value` is always shown
    alongside `effective_value`, never hidden.
  - Two-point calibration: click two points on the rendered sheet, enter
    a known real-world length, submit `PATCH
    /drawings/{id}/sheets/{sheetIndex}/scale` (`p1`/`p2`/`known_length_m`);
    the calibration history (`GET .../scale-calibrations`) is listed with
    a revert action per entry.

## 3. Explicitly out of scope for 8b

- BOQ import/reconciliation, typology, procurement, settlement, admin,
  audit -- later sub-phases (8c-8f), only their placeholder routes exist
  today.
- AG Grid -- first real use is 8c's reconciliation grid.
- Any change to extraction/ingestion logic itself (Module B) -- this
  sub-phase only reads/displays what it already produces, plus the two
  new list endpoints above.

## 4. Testing

- vitest: `entitiesToSvgPaths()` (pure, a few synthetic entities),
  confidence-band colour mapping, override-form validation.
- Playwright: one happy path -- upload a drawing on a seeded demo
  project, see it appear in the drawings list (mocks the ingest
  completing; a real vLLM extraction pass is out of scope for a UI
  smoke test, per this build's existing "extraction quality needs a real
  model" caveat from Phase 6's build-log).
- Backend: the two new list endpoints get integration tests (RLS
  visibility) alongside the existing takeoff test module.
