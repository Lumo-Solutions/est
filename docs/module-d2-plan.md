# Module D2 plan: client BOQ export (generated) and win/loss

Phase 2 of `docs/preconstruction-build-brief.md`. Shares D1's conventions
(RLS-forced project-scoped tables, audit on every state change, role
tests at the lowest allowed + one denied role, Decimal money) --
see `docs/module-d1-plan.md` for those; not repeated here.

Status: **proposal, committed then built straight away per the brief's
autonomy rule (0.1).**

## 1. Scope recap (from the brief)

1. Module B's BOQ import retains the original uploaded workbook (S3) and
   records the sheet + cell coordinates of every imported row. Existing
   imports can't be backfilled -- they get `source_workbook = null` and
   simply can't use D3's original-workbook export later.
2. A freshly-generated `.xlsx` export: client hierarchy/item numbers,
   pre-VAT line rates and amounts, optional VAT summary line. Only from an
   `approved` settlement. Audited (who, when, version, file sha256).
3. A leak test: no cost/markup/margin/overhead/source/vendor/FX data
   anywhere in the file -- including hidden sheets/rows/columns, comments,
   defined names, document properties, custom XML.
4. Win/loss capture: outcome, our price, winning price (optional),
   competitors (free text + optional vendor link), reason codes
   (configurable list), date, notes. `bd_director+`, audited. Valid from
   `approved` **or** `submitted` (not just `approved`); moving to won/lost
   sets `bid_settlements.status`.

## 2. Module B: retain the original workbook + cell coordinates

`app/boq/import_parser.py::ParsedBoqRow` already carries `row_number`
(1-indexed source row) for every parsed row -- that's the hard part of
"record coordinates" already done. What's missing: the column *letters*
for the rate/amount cells (tender BOQs are blank at import time, but the
cells that will eventually hold the rate exist in the template and need
to be known later), and retaining the raw file itself.

### 2a. `BoqImportColumnMapping` gains two optional fields

```
rate_column: str | None = None     # e.g. "F" -- often blank at import time
amount_column: str | None = None   # e.g. "G"
```

Not used for parsing (still blank), purely recorded for D3. `None` when
the caller doesn't know/have these yet (a very plausible case: the
client's template may not even have rate/amount columns until returned
priced) -- D3 will simply refuse original-workbook export for a batch with
neither set (nothing to write into), falling back to the generated export.

### 2b. New table: `boq_import_batches` (migration 0020)

```
boq_import_batches
  id, tenant_id, project_id
  source_filename        varchar
  source_object_key      varchar, nullable   -- S3 key, .xlsx imports only (see 2c)
  source_sha256           char(64), nullable
  sheet_name              varchar, nullable  -- current importer is single-sheet only
  header_row, item_no_column, description_column, uom_column, quantity_column,
  parent_column, rate_column, amount_column   -- mirrors BoqImportColumnMapping, nullable where optional
  imported_by, imported_at
```

`boq_line_items` gains two nullable columns: `import_batch_id` (FK,
`ON DELETE SET NULL` -- deleting a batch record must never cascade-delete
real BOQ data) and `source_row_number` (int). A line item's exact original
cell for e.g. the rate column is then
`f"{batch.rate_column}{item.source_row_number}"`, computed on demand by
D3, never stored per-row (uniform per import, no need to duplicate it on
every row).

### 2c. Retention only for `.xlsx`

CSV imports get `source_object_key = NULL` unconditionally -- D3's whole
premise ("write into the client's original Excel workbook") doesn't apply
to CSV, and "existing imports can't be backfilled, mark
`source_workbook = null`" is exactly this same fallback, so no special
case is needed beyond "CSV never gets one in the first place." The raw
bytes are uploaded to the **existing** `installtec-drawings` bucket
(reusing it rather than adding a new bucket/env var/S3-identity grant --
a tender BOQ workbook is a project source document, the same category as
drawings) under `boq-imports/{project_id}/{batch_id}.xlsx`.

### 2d. `commit_import` changes

After creating every `BoqLineItem` (unchanged logic), for an `.xlsx`
upload: `put_object_streaming(...)` the raw bytes, compute `sha256`,
insert one `boq_import_batches` row, then set
`item.import_batch_id`/`item.source_row_number = row.row_number` on every
created item and flush once more. `preview_import` is untouched (dry-run,
no commit, no S3 write).

## 3. Generated export (D2's actual export path)

`POST /bid-settlements/{id}/export` (not GET -- it's audited and, per
the brief, gated on state, so a side-effect-bearing POST is more honest
than a cacheable GET):

- 409 unless `status == "approved"`.
- Role: `estimator+`. **Default I'm picking**: the `approved` gate is the
  real protection (only reachable after `bd_director`/`managing_director`
  sign-off); preparing the actual file to send is ordinary estimating
  work once that gate has passed, same as how BOQ read access works
  today. Flagging this explicitly since the brief doesn't specify a role.
- Body: `{"include_vat": bool = false, "vat_pct": float = 5.0}` -- VAT is
  opt-in per the brief's "optional"; `5.0` is the shown default, not
  hardcoded (a different rate can be passed).
- Builds a **fresh** `openpyxl.Workbook()` (never touches any retained
  original -- that's D3): one visible sheet, the settlement's BOQ
  hierarchy (item_no, description, uom, qty, unit_sell_rate, line_amount),
  section subtotal rows (real `SUM()` formulas over the Amount column
  only -- safe, since that column never holds anything but sell prices),
  a grand total row, and, if `include_vat`, one extra summary row
  (`Subtotal`, `VAT @ {vat_pct}%`, `Total incl. VAT`). No document
  properties beyond openpyxl's own harmless defaults are set explicitly
  (title left as the workbook's own default); no comments, no defined
  names, no hidden anything -- see §4.
- Response: `StreamingResponse`,
  `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`,
  `Content-Disposition: attachment`. sha256 computed over the generated
  bytes before responding.
- Audited (`AuditAction.EXPORT`, entity_type=`bid_settlement`): who, when,
  settlement id + version_no, sha256, `include_vat`/`vat_pct`.

## 4. Leak test

Since the generated file is built entirely from scratch from a fixed,
known column set, the realistic risk is a future edit accidentally adding
a column/property that leaks something -- so the test is written as a
**generic scanner**, not a hardcoded list of today's fields, and run
against a real settlement that has non-trivial cost/markup/vendor/FX data
so there's actually something to leak:

- Every string cell value, across every sheet (including hidden ones),
  checked against a denylist built from the settlement's own live data:
  every line's `direct_unit_cost`, `cost_source`, vendor name/id,
  `fx_rate`, every resolved `plant_pct`/`overhead_pct`/`volatility_pct`/
  `markup_pct`, `source_note`.
- `workbook.sheetnames` -- exactly one, and it isn't `state="hidden"`/
  `"veryHidden"`.
- Every sheet's hidden rows/columns (`row_dimensions[i].hidden`,
  `column_dimensions[c].hidden`) -- none.
- `workbook.defined_names` -- empty.
- Every cell's `.comment` -- none.
- `workbook.properties` (core.xml: title/subject/creator/keywords/
  description/category) -- none contain any denylisted string.
- The raw zip: `zipfile.ZipFile(io.BytesIO(export_bytes))`, every member
  name and every member's raw bytes scanned for every denylisted string
  -- catches custom XML parts and anything openpyxl's object model
  doesn't surface directly.

## 5. Win/loss

Uses `bid_settlements`' existing outcome columns from D1 (already in the
schema, per D1's plan §9 note) plus one addition: migration 0020 also adds
`outcome_competitor_vendor_ids uuid[]` (nullable array -- "competitors...
plus an optional vendor link", i.e. free-text names always, a structured
`Vendor` link only when the competitor happens to be a known vendor).

### 5a. Reason codes are configurable data, not a hardcoded enum

Per the brief's standing constraint (0.5: "configurable values live in
the DB... don't hard-code them"), a new tenant-scoped table:

```
settlement_reason_codes
  id, tenant_id, code (unique per tenant), label, is_active
```

Seeded (via `app.cli seed`, same pattern as the approval policies) with a
starter set: `price`, `technical`, `relationship`, `timeline`, `scope`,
`other`. `record_outcome()` validates every submitted code against active
rows for the tenant, rejecting unknown ones (422) rather than silently
accepting free text -- keeps bid-leveling-style analytics meaningful
later. No admin CRUD endpoint in this phase (brief doesn't ask for one;
the seed + direct DB access covers it for now, same as approval policies
today) -- flagging as a gap, not silently skipping it.

### 5b. Endpoint

`POST /bid-settlements/{id}/outcome`, `bd_director+`, audited:

```
{
  outcome: "won" | "lost",
  our_price: Decimal,                  -- defaults to tender_total if omitted
  winning_price: Decimal | None,
  competitor_names: [str],
  competitor_vendor_ids: [UUID] = [],  -- optional, validated to exist
  reason_codes: [str],                 -- validated against settlement_reason_codes
  note: str | None,
}
```

- 409 unless `status in ("approved", "submitted")` (the brief's exact
  rule -- not "approved only").
- Sets `bid_settlements.status = outcome` (`won`/`lost`) and every
  `outcome_*` column, `outcome_recorded_by/_at`.
- A `won`/`lost` settlement is terminal, same as `rejected` -- no further
  edits; a correction is a new version via `build_settlement_draft`, same
  pattern as everywhere else in D1/D2.

## 6. Endpoints (draft)

| Method | Path | Role | Notes |
|---|---|---|---|
| POST | `/bid-settlements/{id}/export` | `estimator+` | 409 unless `approved`; §3 |
| POST | `/bid-settlements/{id}/outcome` | `bd_director+` | 409 unless `approved`/`submitted`; §5 |
| GET | `/settlement-reason-codes` | `estimator+` | list active codes, for a UI picker |

## 7. Testing plan

- Unit: the generic leak scanner itself (§4) against a deliberately
  "leaky" fixture workbook (to prove the scanner catches real leaks, not
  just that today's generator happens to be clean) and against the real
  generator's output (must be clean).
- Unit: VAT summary arithmetic (subtotal/VAT/total) at a couple of
  boundary rates including `0`.
- Integration: export blocked (409) from `draft`/`submitted`/`rejected`,
  allowed from `approved`; audit event recorded with the right sha256.
  Role gating (lowest allowed `estimator`, denied role with no matching
  role at all).
- Integration: outcome blocked from `draft`; allowed from `submitted` and
  from `approved`; unknown `reason_codes` rejected (422); settlement
  status flips to `won`/`lost`; a further edit attempt after outcome is
  rejected same as D1's post-submit immutability. Role gating
  (`bd_director` lowest allowed, `lead_estimator` denied).
- Integration: `commit_import` on an `.xlsx` retains the workbook in S3
  (byte-identical round trip) and stamps `import_batch_id`/
  `source_row_number` on every created line item; a `.csv` import leaves
  `source_object_key` null.
- Dev simulation: extend `make dev-simulate-settlement` (or a new
  `dev-simulate-export` step) to import a small synthetic tender BOQ
  workbook, run D1 through `approved`, export, and print the sha256 +
  confirm the leak scan passes -- against the real dev stack.

## 8. Explicitly out of scope for D2

- Writing sell rates back into the retained original workbook (D3) --
  this phase only retains it and records coordinates.
- Admin CRUD for `settlement_reason_codes` (seed data only, per §5a).
