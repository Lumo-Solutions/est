# Module B Phase 3 (+3 fixes, +3b): BOQ reconciliation

## Scope

**Implemented**: a hierarchical BOQ line item (`boq_line_items`, migration
`0011`) per project -- same ltree pattern as trade taxonomy
(`trade_nodes`/migration `0004`), scoped by `project_id` instead of
`tenant_id`. Each item can link **several** `drawing_measurements` rows
(`boq_line_item_measurements`, migration `0013` -- summed, not just one),
optionally carries a trade classification (`trade_node_id`) for a
per-trade tolerance override, and can be imported in bulk from an Excel/CSV
tender BOQ. Linking, unlinking, or re-running reconciliation recomputes and
persists a variance and a three-class discrepancy flag via
`app/boq/reconciliation.py`; a lazy self-heal (`app/services/boq.py::
_refresh_if_stale`) keeps that persisted value correct even when nothing
explicitly re-reconciles after a linked measurement changes or disappears.

**Explicitly deferred** (see MASTER_SRS.MD's one-line Module B spec:
"Hierarchical tender BOQ parsing, semantic cross-referencing against AI
takeoff using `pgvector` RAG, and three-class discrepancy flagging"):
- **Semantic cross-referencing** (pgvector RAG) to automatically find which
  measurement(s) a BOQ line item's *description* refers to. Linking is
  always a manual, explicit action (`POST /boq-items/{id}/measurements`)
  -- there is no auto-matching by description similarity. The natural
  starting point for this later: `sheet_chunks`' embeddings (already built
  for Module B's similarity-probe endpoint), surfaced as *suggestions* an
  estimator accepts via the same explicit link endpoint -- never an
  automatic link, per the standing instruction that produced
  `boq_line_item_measurements` in the first place (see "3b(a)" below).
- **PDF tender BOQs.** Import supports `.xlsx`/`.csv` only
  (`app/boq/import_parser.py`); a PDF BOQ needs table-extraction (closer in
  kind to `docs/takeoff-pipeline.md`'s PDF page indexing than to a
  structured-file parse) and isn't attempted here.
- A **trade filter** on the unlinked-measurements endpoint (see "3b(b)"
  below) -- `drawing_measurements` carries no trade classification of its
  own (only `boq_line_items` does, via `trade_node_id`, for tolerance
  lookups), and a measurement with no BOQ line linking to it by definition
  can't inherit one from a line item either. Mapping an extractor
  `capability` (alignment/corridor_area/trench_prismoidal_volume/
  pipe_network_topology) to a trade would need a real convention this
  codebase doesn't have yet -- not invented here.
- Any pricing (unit rates, extended amounts) -- the SRS assigns that to
  Module D (Bid Settlement); this stays a pure quantity comparison.

## The three-class discrepancy taxonomy

**Not specified numerically anywhere in the SRS** -- only "three-class
discrepancy flagging" is named. This taxonomy, the tolerance default, and
the unit-dimension/alias table are this implementation's own choices and
should be validated against real QS/tender practice before being relied on:

| Class | Meaning |
|---|---|
| `match` | At least one measurement is linked; the **sum** of all linked measurements (each converted into the BOQ item's own `uom` -- see `app/boq/units.py`) is within `tolerance_pct` of the tendered quantity. Symmetric (over- and under-measurement treated the same). |
| `variance` | Linked, but outside that tolerance. |
| `unmatched` | No measurement is linked yet, **or** a linked measurement's unit is a different *dimension* (length/area/volume/count) than the BOQ item's `uom` -- comparing a length against a volume isn't "close" or "far", it's not comparable at all (`reconciliation_note` says which dimension each side is). Same-dimension, different-unit pairs (e.g. BOQ in "LM", measurement in "m") are converted, not rejected. |

Unit conversion (`app/boq/units.py`) covers length/area/volume/count with
common SI units plus a starting set of Gulf/British QS abbreviations
(`LM`, `RM`, `SQM`, `CUM`, `NR`, `NO`, `EA`, ...) -- extend it as real
tender BOQs turn up ones it doesn't recognize; an unrecognized unit is
never guessed at, only ever "not convertible" -> `unmatched`.

Edge case: a BOQ item tendering exactly zero has an undefined percentage
variance; `reconcile()` treats a zero-vs-zero link as `match` and any
zero-vs-nonzero link as `variance` (with `variance_pct=None` either way)
rather than dividing by zero. See `tests/unit/test_boq_reconciliation.py`
and `test_boq_units.py` for every case above worked by hand.

## Configurable tolerance (`boq_tolerances`, migration `0012`)

Default 2.0% (`app/boq/reconciliation.py::DEFAULT_RECONCILIATION_CONFIG`)
is overridable per project (`trade_node_id IS NULL` row) and per
project-and-trade (`trade_node_id` set), resolved in that order by
`app/services/boq.py::_resolve_tolerance_pct()`. `UNIQUE NULLS NOT
DISTINCT (project_id, trade_node_id)` (PG15+) guarantees at most one
project-default row -- a plain `UniqueConstraint` would silently allow
duplicate defaults, since Postgres's default NULL-is-distinct behavior
treats every `NULL` as unique. `PUT /projects/{id}/boq-tolerances` sets a
tolerance (structural role, audited); `GET` lists current overrides.

## Staleness self-heals on read, and audits when it does

`variance`/`discrepancy_class` are persisted (for cheap filtering/sorting
in what the SRS itself expects to be a "4,200+ line" AG Grid), which means
they can go stale: a linked measurement gets deleted (its
`boq_line_item_measurements` row is `ON DELETE CASCADE`, so the link just
disappears) or, in the future, updated in place. `app/services/boq.py::
_refresh_if_stale()` recomputes on every read of a previously-reconciled
item (`reconciled_at is not None`) and writes an `audit_events` row only
when the *classification* actually changed (avoiding an audit entry on
every read of an unchanged item). A freshly created, never-linked item
intentionally stays at `discrepancy_class=None` until an estimator
actually reconciles it -- a different, meaningful state from "reconciled,
then went stale" that this never silently collapses into `unmatched`.

Recomputing on every read of a previously-reconciled item is a real
per-request cost (a tolerance lookup + a join query per item) -- fine for
a single `GET`, and for realistically-sized project BOQs in `list`, but a
genuine "4,200+ line" BOQ listed all at once would be worth batching or
caching properly; not attempted here.

## Roles

Three role sets, gated at the API layer and mirrored by the migrations'
RLS write policies for the structural set:

- **Structural edits** (create/reparent a line item, set a tolerance,
  import): `lead_estimator`, `procurement_head`, `managing_director` --
  same precedent as trade taxonomy (`trade_nodes`' own write roles), on
  the reasoning that editing the master tender BOQ tree (or importing one
  wholesale) is more senior than day-to-day reconciliation.
- **Reconciliation** (add/remove a measurement link, re-reconcile): the
  same role set as everywhere else in Module B (`estimator` and up) --
  `app/api/v1/routes/boq.py::_RECONCILE_ROLES`, matching `drawings.py`'s
  `_UPLOAD_ROLES`. This is a normal, frequent estimating task.
- **Delete**: same as structural edits.

Every mutating operation (create/link/unlink/reconcile/delete/set
tolerance/import commit, including the *automatic* re-reconciliation
`_refresh_if_stale()` performs) records an `audit_events` row
(`app/services/audit.py`), same as every other Module B write.

## Cross-project safety

`managing_director`/`bd_director`/`procurement_head` bypass
`project_members` entirely (`app_can_see_project()`), so RLS visibility
alone does not stop one of those roles from accidentally cross-linking
data between two different projects. Explicit application-side checks
exist for exactly this, all verified against the live stack:

- The ltree trigger's parent lookup is scoped `WHERE id = NEW.parent_id
  AND project_id = NEW.project_id` (migration `0011`) -- a `parent_id`
  from a different project raises, rather than silently succeeding.
- `app/services/boq.py::add_measurement_link()` explicitly checks
  `measurement.project_id == item.project_id` before linking, raising
  `ValidationAppError` otherwise.

## 3b(a): many-to-one measurement links

`boq_line_item_measurements` (migration `0013`) replaced a single optional
`linked_measurement_id` FK on `boq_line_items` -- one line can now
aggregate several measurements (e.g. a pipe run's length summed across
several sheets), summed via `app/boq/reconciliation.py::
aggregate_measurement_values()` (each converted into the BOQ item's uom;
refuses to silently drop a dimension-mismatched one and sum the rest into
a partial, misleading total). `POST/DELETE /boq-items/{id}/measurements`
add/remove one link at a time; `GET .../measurements` lists what's linked.
Existing single links were migrated into the join table before the old
column was dropped.

## 3b(b): reverse direction -- unlinked measurements

`GET /projects/{id}/measurements:unlinked` (optional `drawing_id` filter)
lists measurements with **no** `boq_line_item_measurements` row at all --
"possible missed scope": something the AI takeoff found that no BOQ line
item currently accounts for. See "Explicitly deferred" above for why there
is no trade filter.

## 3b(c): BOQ import (Excel/CSV)

`app/boq/import_parser.py` is pure (no DB) so the preview and commit
endpoints share identical parsing/validation logic and can never disagree
about what would be created:

- **Column mapping** is explicit, not auto-detected: the caller names
  which spreadsheet column holds the item number, description, uom,
  quantity, and (optionally) an explicit parent reference
  (`BoqImportColumnMapping`) -- real tender BOQ exports vary too much in
  header naming to guess reliably. `header_row` handles a title/logo block
  above the real header row (an `.xlsx`-only concern; CSV always uses row 1).
- **Hierarchy** is inferred from the item number's own dot-numbering by
  default ("1.1.2"'s parent is "1.1", found within the same file) -- the
  common case needs no separate column at all. An explicit
  `parent_column`, when mapped and non-empty for a row, overrides that
  inference, for a BOQ with a real "Section" column instead. Both a
  missing parent and a parent cycle (only reachable via an explicit
  `parent_column`) are per-row errors, not a crash.
- `POST /projects/{id}/boq-items:import-preview` parses and validates
  without writing anything -- returns every row plus its errors, if any.
- `POST /projects/{id}/boq-items:import-commit` re-parses and
  re-validates (never trusts a client's "I already previewed this" claim)
  and refuses the *entire* import (422, with every row's errors) if even
  one row has a problem -- creation is all-or-nothing, in the request's
  own transaction, in topological (parents-before-children) order.
- See `tests/unit/test_boq_import_parser.py` for a small, realistic sample
  BOQ (two sections, dot-numbered sub-items, a blank quantity on section
  headings) parsed by hand-checkable assertion, plus every error case
  (missing item_no/description, non-numeric quantity, duplicate item_no,
  unresolvable/self/circular parent reference, unsupported file type).

## Real bugs found verifying this against the live stack

- **`create_line_item()`'s trigger-refresh gap.** `path`/`level` are
  computed by the `boq_line_items_path_trg` `BEFORE INSERT` trigger (same
  pattern as `trade_nodes_path_trg`), which SQLAlchemy has no visibility
  into -- the ORM object silently kept the client-submitted
  `path="placeholder"` value while the actual database row held the
  correct trigger-computed path. Caught by creating a real BOQ item
  through the live API and noticing the response body's `path` field
  literally said `"placeholder"`. Fixed with `session.refresh(item,
  attribute_names=["path", "level"])`, matching the exact pattern
  `app/services/taxonomy.py::create_node` already established for
  `trade_nodes` -- missed on the first pass despite reading that file's
  create function while designing this one.
- **`add_measurement_link()`'s missing flush before recomputing.** This
  session is created with `autoflush=False`
  (`app/db/session.py::_session_factory`), so a newly `session.add()`-ed
  `BoqLineItemMeasurement` row is *not* visible to a `SELECT` run against
  the same session immediately afterward -- `_apply_reconciliation()`'s
  join query would only ever see links as of one call behind, so linking
  two measurements in a row silently computed the sum of the *first* link
  only, one request late. Caught immediately by hand-verifying the
  aggregation fixture (10.0 m + 25.71 m) against the live API: the first
  link's response showed `unmatched` (no measurement seen at all yet), and
  the second showed the variance for *one* measurement, not both. Fixed
  with an explicit `await session.flush()` right after adding the link row,
  before `_apply_reconciliation()` reads it back.
