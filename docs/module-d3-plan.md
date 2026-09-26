# Module D3 plan: export into the client's original workbook

Phase 3 of `docs/preconstruction-build-brief.md` -- the actual SRS
requirement D2 only laid groundwork for. Shares D1/D2's conventions (RLS,
audit, role tests at lowest-allowed + a denied role); see those plans for
the parts not repeated here.

Status: **proposal, committed then built straight away per 0.1.**

## 1. Scope recap

- Open the retained original (`boq_import_batches.source_object_key`,
  from D2) with openpyxl. Reject `.xlsm` and encrypted files.
- Write **only** the rate cells, and the amount cells **when those cells
  are not formulas**. Never touch formulas, merged ranges, styles, sheet
  order, print areas, or defined names anywhere else.
- **Fidelity check**: re-open the output and compare against the
  original -- formulas, merged ranges, sheet names/order, and every cell
  outside the written set must be unchanged. Detect features openpyxl
  drops (images, charts, some data validation/conditional formatting,
  pivots, external links) and **report them before download**. Default:
  refuse if anything would be lost, unless the user explicitly accepts
  the loss (audited).
- Same leak test and audit as D2.

## 2. A small fix to D2's own groundwork, found while planning this

`boq_import_batches.sheet_name` exists (migration 0020) but
`commit_import()` never actually populated it -- D3 needs to know which
sheet to write into for a multi-sheet workbook. Fixed in `commit_import`
itself (reads `load_workbook(..., read_only=True).active.title` for an
`.xlsx` import, same file already in memory) -- no new migration, and
existing batches simply keep `sheet_name = NULL` like everything else D2
couldn't backfill.

## 3. Eligibility -- a settlement either qualifies for this path or it doesn't

Before opening anything, `check_original_export()` verifies, cheaply, from
already-loaded rows (no S3 fetch needed to fail fast):

1. Every settlement line's `BoqLineItem.import_batch_id` is the **same**,
   single, non-NULL batch. (A project whose BOQ came from more than one
   import, or has any manually-created line with no batch at all, simply
   isn't eligible -- "the client's original workbook" is singular by
   construction. This is a hard, unconditional 409, distinct from a
   fidelity loss -- there's no "accept it anyway" for a missing file.)
2. That batch has `source_object_key IS NOT NULL` (an `.xlsx` import that
   actually got retained -- not a `.csv` import, not one predating D2).
3. That batch has `rate_column IS NOT NULL` (nothing to write into
   otherwise).

Any failure here returns a clear 409 naming the reason, and the caller
falls back to D2's generated export (always available once approved,
regardless of import provenance).

## 4. Reject `.xlsm` and encrypted files

- `.xlsm`: `batch.source_filename` can only end in `.xlsx` in practice
  (Module B's importer already rejects anything else at import time, per
  `app/boq/import_parser.py::parse_boq_file`) -- checked again here anyway,
  defensively, plus a **content**-based check: an OOXML file with macros
  carries `xl/vbaProject.bin` in its zip regardless of what its extension
  claims, so that member's presence is checked directly and rejected too.
- Encrypted: a password-protected `.xlsx` is stored as an OLE/CFB
  container, not a zip at all -- `zipfile.is_zipfile(...)` returns `False`
  for it. No new dependency (e.g. `msoffcrypto`) needed just to detect
  this; decrypting one is out of scope entirely (rejected, not attempted).

## 5. Writing (the only mutation allowed)

For each settlement line, via its `BoqLineItem.source_row_number` (the
real spreadsheet row, from D2's fix) and the batch's `rate_column`/
`amount_column` letters:

```
ws[f"{rate_column}{row}"] = float(line.unit_sell_rate)
if amount_column:
    cell = ws[f"{amount_column}{row}"]
    if cell.data_type != "f":   # not a formula -- brief's exact rule
        cell.value = float(line.line_amount)
    # else: left untouched -- it's presumably already computing from the rate cell
```

Loaded with `load_workbook(..., data_only=False)` (formulas preserved as
formulas, not their last-computed value) on the batch's `sheet_name`
(falling back to `wb.active` if `sheet_name` is NULL -- an import that
predates §2's fix). Nothing else in the workbook is touched, read, or
re-written by this code -- the whole rest of the file passes through
openpyxl's own load/save cycle unmodified except for whatever fidelity
loss openpyxl itself introduces on any round trip (exactly what §6 exists
to catch).

## 6. Fidelity check

Two independent kinds of check, both required to pass (or be explicitly
accepted) before a download is allowed:

### 6a. Structural equality (blocking, never overridable)

Re-open both the original and the freshly-written output with openpyxl
and assert, sheet by sheet:

- `wb.sheetnames` -- identical list, identical order.
- Each sheet's `ws.merged_cells.ranges` -- identical set.
- Every cell **outside** the written set (§5) -- `original.value ==
  output.value`, including formula cells (compared as their formula
  string, `data_only=False`) so a formula is provably untouched, not just
  "still present."

Any mismatch here is a bug in this code, not an inherent openpyxl
limitation -- it's asserted in tests, not just checked at runtime, but the
runtime check stays too (defense in depth: a workbook openpyxl mishandles
in a way today's tests don't cover must never silently ship a corrupted
file).

### 6b. Feature-loss detection (reportable, overridable with `accept_loss`)

openpyxl is known to drop or degrade features it doesn't fully model on a
load/save round trip. Rather than trying to predict this from
documentation, the check **observes it directly for this exact file**:
before writing, list the original's raw zip members matching each
category below; after writing, list the same categories in the output;
anything present before and missing (or reduced) after is a real,
file-specific loss, not a hypothetical one.

| Category | Zip signal |
|---|---|
| Images | `xl/media/*` |
| Charts | `xl/charts/*` |
| Pivot tables | `xl/pivotTables/*`, `xl/pivotCache/*` |
| External links | `xl/externalLinks/*` |
| Extended conditional formatting / data validation | `<extLst>` blocks referencing the `x14` namespace inside `xl/worksheets/sheet*.xml` (openpyxl's classic parser reads the base CF/DV rule types reliably; `x14`-namespaced extensions -- databars/icon sets with extra options, some newer validation types -- are the ones known to not round-trip) |

Any non-empty loss list makes the response `ok=False`; the caller
(`POST .../export-original/preview`) can inspect it before ever
requesting the actual file.

## 7. Endpoints

| Method | Path | Role | Notes |
|---|---|---|---|
| POST | `/bid-settlements/{id}/export-original/preview` | `estimator+` | Runs §3-§6 against a real write attempt held **in memory only** (never returned, never persisted) -- returns the fidelity report. 409 if not eligible at all (§3); 200 with `ok: false` and the loss list otherwise. |
| POST | `/bid-settlements/{id}/export-original` | `estimator+` | Body `{"accept_loss": bool = false}`. Re-runs the same check; 409 (with the report) if lossy and not accepted; otherwise streams the file, same headers/sha256/audit shape as D2's export. `accept_loss=true` is itself audited (payload includes the accepted loss list and who accepted it) whether or not this particular run was actually lossy. |

Both require `status == "approved"`, same as D2's generated export -- no
new state rule.

## 8. Leak test and audit

Same generic scanner as D2 (`docs/module-d2-plan.md` §4), run against the
**output** file -- rewritten cells only ever carry `unit_sell_rate`/
`line_amount`, so the risk profile is identical to D2's, but this path
also carries forward whatever the *client's own original file* already
contained (their own formulas, their own formatting) -- none of which is
settlement data, so the same scanner (denylist built from the
settlement's live cost/vendor/FX data) is exactly the right tool, unchanged.

`AuditAction.EXPORT`, `entity_type="bid_settlement"`, payload adds
`export_kind: "original"` (vs. D2's implicit `"generated"`) and, when
applicable, `accepted_loss`/`lost_features`.

## 9. Testing plan

- Unit: build synthetic client workbooks (openpyxl, in the test) covering
  each brief-required shape -- formulas referencing the rate/amount cells,
  merged cells, multiple sheets, subtotal rows, a hidden sheet -- and
  assert:
  - the rate/amount cells change, formulas elsewhere don't;
  - merged ranges, sheet names/order survive exactly;
  - a workbook with no images/charts/pivots/external links reports
    `ok=True`;
  - a workbook carrying a fixture image/chart/pivot-table/external-link
    zip member is detected as lossy (§6b) -- built by injecting a minimal
    real OOXML part into the zip in the test, not by trusting openpyxl to
    create one, so the test doesn't depend on openpyxl's own (limited)
    write support for these.
  - `.xlsm` and a password-protected fixture are both rejected outright.
- Integration: eligibility (§3) -- multi-batch/no-batch/no-rate-column
  settlements all 409 before any S3 fetch; happy path end-to-end
  (approved settlement, single-batch import, clean fidelity) returns a
  file whose rate cells match `unit_sell_rate`; a deliberately-lossy
  fixture blocks without `accept_loss` and succeeds (audited) with it.
  Role gating (estimator lowest allowed, denied role with none).
- Dev simulation: extend `make dev-simulate-settlement` to import a small
  synthetic client workbook (with a formula and a merged header) instead
  of relying on `boq_service.create_line_item` directly, then attempt
  `export-original` after approval and print the fidelity report.

## 10. Explicitly out of scope

- Decrypting a password-protected original -- rejected, never attempted.
- Recovering/re-embedding a lost image/chart/pivot table -- reported only;
  the user chooses generated export or explicit accept.
- Editing anything in the original beyond the rate/amount cells -- no
  "also fix a typo while we're in there."
