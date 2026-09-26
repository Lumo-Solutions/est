# Phase 8c plan: typology + BOQ

Per `docs/module-frontend-phase8-plan.md` §2's sub-phase breakdown.

## 0. What already exists (confirmed by reading the backend code)

Read `app/api/v1/routes/{typology,boq,semantic_matching}.py` and their
schemas in full before writing this. Unlike Phase 8b, **nothing is
missing** -- every screen this sub-phase needs already has a backend
endpoint:

- **Typology**: `POST .../typology-clusters/detect`, `GET
  .../typology-clusters` (list), `GET /typology-clusters/{id}` (+
  `/instances`, `/deltas`, `/rollup`), `POST .../confirm`, `POST
  .../reject`. Confirming assigns every instance's DXF/PDF handles to a
  named group, picks one group as `master_group_label`, and records
  per-group quantity deltas against specific BOQ line items; the rollup
  (`total(item) = master_quantity x sum(group.instance_count) +
  sum(delta.quantity_delta x group.instance_count)`) is computed on read,
  never persisted (`docs/module-b-phase4-plan.md`).
- **BOQ**: full line-item CRUD, measurement link/unlink/list, reconcile
  (recompute variance), tolerances, and -- the two endpoints this screen
  actually needs -- `GET /projects/{id}/measurements:unlinked` and the
  two-step import flow: `POST .../boq-items:import-preview` (multipart
  `file` + a `mapping` form field, itself a JSON-encoded
  `BoqImportColumnMappingIn` string -- dry run, no DB write) then `POST
  .../boq-items:import-commit` (same shape, all-or-nothing commit).
  There is no third "mapping" step as a separate persisted call -- mapping
  is just the form state kept client-side until the commit request.
- **Link suggestions**: `GET
  /boq-line-items/{id}/measurement-suggestions?top_k=` already *is* the
  suggestion list the brief means by "link suggestions to accept or
  reject" -- accepting one is just calling the existing `POST
  /boq-items/{id}/measurements` link endpoint with the suggested
  `target_id`, then (optionally, but done here since it's what trains
  future ranking) `POST /semantic-matching/feedback` with
  `match_type="boq_measurement"`, `outcome="accepted"` (or `"rejected"`
  when dismissed without linking).
- **No pagination anywhere** -- `list_boq_items`/`list_typology_clusters`
  return an entire project's rows in one response; virtualisation is
  purely a client-side (AG Grid) concern, matching the brief's own
  phrasing ("smooth at 4,200+ rows" describes the grid, not the API).

## 1. Screens

- **Typology cluster review** (`/projects/:projectId/typology`): cluster
  list with status (proposed/confirmed/rejected) and a "Detect" button;
  selecting a cluster shows its instances (grouped, with each group's
  `instance_count`) and variant deltas; a confirm form assigns each
  instance to a named group, picks the master group, and lets the
  reviewer add/edit deltas against specific BOQ line items before
  submitting `ConfirmClusterRequest`; a reject button; the rollup table
  once confirmed.
- **BOQ import wizard** (`/projects/:projectId/boq/import`): file picker
  + a column-mapping form (`item_no_column`, `description_column`, and
  the optional ones) -> "Preview" (import-preview, shows
  valid/error counts and every row's own errors) -> "Commit" (only
  enabled once a preview has run against the *same* file+mapping;
  re-running preview after any change invalidates a stale commit-ready
  state client-side, since the backend re-parses from scratch every call
  anyway and there is no server-side "preview session" to key off).
- **BOQ reconciliation** (`/projects/:projectId/boq`): the AG Grid
  Community virtualised grid (item_no, description, uom, boq_quantity,
  variance, variance_pct, discrepancy_class, reconciliation_note),
  row-click opens a detail panel with: linked measurements (list +
  unlink), a "Reconcile" button (recompute), and the measurement-link
  suggestions list (accept/reject, per §0 above) when the item has no
  links yet or the reviewer wants more; a separate "Unlinked
  measurements" panel (the `:unlinked` endpoint, filterable by drawing/
  trade) for the opposite direction -- picking an unlinked measurement
  and linking it to a chosen BOQ item.

## 2. AG Grid performance test

A vitest test renders the reconciliation grid with 5,000 synthetic
`BoqLineItemOut` rows (generated in the test, not a real import) and
asserts the number of mounted row DOM nodes stays bounded regardless of
the dataset size -- AG Grid's row virtualisation means only the rows
actually scrolled into view exist in the DOM at all, so a bounded node
count is the correct, deterministic thing to assert (not a subjective
"feels smooth" measure), per the brief's own phrasing and this build's
existing "assert exact counts, not vibes" testing convention.

## 3. Explicitly out of scope for 8c

- Procurement, settlement, admin, audit -- 8d-8f.
- Any change to the typology/BOQ backend -- confirmed complete in §0,
  nothing to add.
