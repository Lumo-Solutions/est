# Phase 6 plan: Module C, remaining procurement features

Per `docs/preconstruction-build-brief.md`'s Phase 6. The brief says "check
against the SRS and complete... only build what's missing, and list in the
log what already existed" -- this plan is grounded in an actual read of the
current C1/C2 code, not assumption. §0 below is that audit.

## 0. What already exists (confirmed by reading the code, not assumed)

- **Vendor matching + eligibility**: `app/services/procurement.py::
  match_vendors()`/`_vendor_eligibility()` already gate on ACTIVE status +
  effective prequalification (trade-scoped or blanket). **No geography
  filter at all today** -- `Vendor.emirate`/`Vendor.country` exist as
  columns and are already returned in `MatchedVendorOut`, but never
  compared against anything.
- **Override mechanism**: `create_rfqs()` already has the exact pattern the
  brief asks to mirror -- an ineligible vendor requires `RfqCreateRequest.
  override_reason`, gated on `_DISPATCH_ROLES` (`procurement_head`,
  `bd_director`, `managing_director`), stored on the RFQ
  (`is_override`/`override_reason`) and audited. **Reused as-is**, not
  reinvented -- geography ineligibility just becomes another reason
  `_vendor_eligibility()` can return, going through this same gate.
- **Arithmetic verification, per-line**: both ingestion paths already
  compute `extended_price_computed = unit_price * quantity` and set
  `arithmetic_mismatch`/`quantity_mismatch` (`app/workers/tasks/
  quotation_ingestion.py`). **Missing**: subtotal-level verification (the
  brief's own "and subtotals") -- nothing today captures or checks a
  vendor's stated grand total against the sum of their own line items.
- **Unit conversion**: `app/boq/units.py` (dimension-aware
  convert/convertible, already used for BOQ-line-to-measurement
  compatibility) exists and is proven. **Missing**: it is never applied to
  vendor quote lines at all -- `QuotationLineItem` has no `uom` field, and
  `quantity_mismatch` compares raw quantities with no unit awareness, so a
  vendor quoting "per LM" against a BOQ line in "M" (same thing) can't be
  told apart from a genuine dimensional mismatch today.
- **Currency**: `Quotation.currency`/`vat_inclusive` are captured and
  `resolve_currency_and_vat()` exists. `get_bid_leveling_matrix()`'s own
  docstring is explicit and deliberate: "never mixing currency/VAT bases --
  shown separately, no automatic FX conversion" (SRS requirement #8) --
  this already matches the standing project-wide rule (Module D1: "currency
  requires recorded FX rate, no auto-conversion"). **Missing**: there is no
  way to even *record* an FX rate at the procurement/bid-leveling stage at
  all (D1's `BidSettlementLineItem.fx_rate` only exists post-acceptance,
  inside a settlement) -- so a reviewer comparing quotes across currencies
  during bid leveling has no recorded-rate normalization option, only raw
  numbers side by side.
- **Exclusion detection**: `extract_quotation()` already returns
  `exclusions: [{flag_text, source_quote_text}]`, persisted to
  `QuotationExclusionFlag` and shown in `get_bid_leveling_matrix()`'s
  underlying data. The "explicit source-text citation... quoted span" half
  already exists. **Missing**: the brief's other half, "page or cell" --
  neither the schema nor the persisted row records *where* in the document
  the quote was found. `page_number` is already known to the extraction
  call (PDF/image path) but never captured per-exclusion; the XLSX path
  (`dump_workbook_text()`) discards cell coordinates entirely when
  flattening the workbook to text.

## 1. Location + geography

- `projects` gains `emirate varchar(32)`, `area varchar(128)`, `latitude
  numeric(9,6)`, `longitude numeric(9,6)` (all nullable -- existing
  projects have none of this; never backfilled, same "can't backfill
  historical data" precedent as D2's import retention). No RLS change
  (existing table).
- New `vendor_service_regions` table (tenant-scoped, RLS-forced):
  `vendor_id FK, emirate varchar(32)`, unique `(vendor_id, emirate)`. A
  vendor with **zero** rows here is treated as "region unknown" -- same
  default-excludes-unless-overridden posture as "no effective
  prequalification" (SRS default #6's own precedent), not "assume
  available everywhere." Write role: vendor-admin tier (same as editing
  any other `Vendor`-owned data -- `app/services/vendors.py`'s existing
  `WRITE_ROLES`, confirmed at implementation time to match, not
  reinvented).
- `_vendor_eligibility()` gains a geography check, evaluated alongside
  (not instead of) the existing prequalification check: if the project has
  an `emirate` set AND the vendor has at least one `vendor_service_regions`
  row, the vendor is geography-eligible only if its regions include the
  project's emirate. If the project has no emirate set, or the vendor has
  no service regions recorded at all, geography is **not** evaluated
  (nothing to filter on) -- consistent with "never guess," same posture as
  an unrecognized unit in `app.boq.units`. The first failing reason
  (prequalification, then geography) is what `MatchedVendorOut.
  ineligible_reason` reports -- one override reason still covers whichever
  check(s) failed, matching `create_rfqs()`'s existing single-reason
  design.
- `MatchedVendorOut` gains `service_regions: list[str]` (informational, so
  a reviewer sees why a vendor was flagged before deciding to override).

## 2. Arithmetic verification: subtotals

- `Quotation` gains `stated_total numeric(16,2)` (nullable) and
  `total_mismatch boolean` (server default false).
- LLM schema (`quotation_extraction.schema.json`) gains a top-level
  `stated_total: number | null` ("the vendor's own overall grand total for
  this quotation, if printed anywhere -- e.g. a 'Grand Total' or 'Total
  Amount' line. Null if not stated."), threaded through
  `ExtractedLineItem`'s sibling `QuotationExtractionResult`. Deterministic
  path: `pricing_sheet_parser.py`'s own template has a fixed subtotal
  formula cell (`app/procurement/pricing_sheet.py::build_pricing_workbook`,
  confirmed at implementation time) -- read that cell's own computed value
  the same way `parse_pricing_sheet` already reads rate cells.
- `total_mismatch = stated_total is not None and abs(stated_total -
  sum(extended_price_computed or extended_price_stated for each line)) >
  tolerance` (tolerance: 0.01 * line_item_count, i.e. one cent of
  accumulated rounding per line -- consistent with the per-line 0.01
  absolute tolerance already in use, scaled for a sum). Computed once,
  right after all of a quotation's line items are created (same
  transaction), not recomputed later.
- Shown in bid leveling as a quotation-level (not per-cell) flag --
  `BidLevelingRow`/`BidLevelingCell` are per-BOQ-line already; a new
  top-level `get_bid_leveling_matrix()` return also includes
  `quotation_totals: [{quotation_id, vendor_id, stated_total,
  total_mismatch}]` alongside the existing rows.

## 3. Unit conversion for vendor quote lines

- `QuotationLineItem` gains `vendor_uom varchar(16)` (nullable).
- LLM schema: `ExtractedLineItem` gains `vendor_uom: string | null` ("the
  unit of measure printed against this line, e.g. 'M', 'M2', 'NO' -- exactly
  as printed, verbatim, not normalized. Null if not stated."). Deterministic
  path doesn't need this -- it matches by hidden row-id against a BOQ item
  whose own `uom` is authoritative already (SRS change #1), so the vendor
  never independently states a unit there.
- `quantity_mismatch`'s comparison (`app/workers/tasks/
  quotation_ingestion.py`'s LLM-path block) is extended: when
  `vendor_uom` and the matched `boq_item.uom` are both set and
  `app.boq.units.convertible(vendor_uom, boq_item.uom)` but they're not the
  *same* unit string, convert the vendor's `quantity` through
  `app.boq.units.convert()` into the BOQ's own unit before comparing
  against `boq_item.boq_quantity` -- exactly the existing tolerance
  check, just fed a converted value instead of the raw one. When the two
  units are set but **not** convertible (genuinely different dimensions,
  e.g. `M` vs `M2`), that's a stronger, distinct signal than a quantity
  mismatch -- gets its own `QuotationLineItem.uom_mismatch: bool` column
  (server default false) rather than being folded into
  `quantity_mismatch`, so a reviewer can tell "the numbers don't match"
  apart from "these aren't even the same kind of quantity."

## 4. Currency normalisation with recorded FX (bid-leveling stage)

- `Quotation` gains `fx_rate_to_base numeric(14,6)` and `fx_rate_date
  date` (both nullable) -- one rate per quotation (not per line): every
  line in one quotation already shares that quotation's single `currency`,
  so a per-line rate would be redundant. Mirrors `BidSettlementLineItem.
  fx_rate`/`fx_rate_date`'s own shape (Module D1), a **separate** field
  from it -- this is the bid-leveling-stage rate, recorded before any line
  is ever accepted into a settlement, not a replacement for D1's own
  acceptance-time rate (a quote reviewed today and settled three months
  later should be allowed a different recorded rate at each stage; forcing
  one to feed the other would silently couple two independently-timed
  decisions).
- New `set_quotation_fx_rate()` service function + `PATCH
  /quotations/{id}/fx-rate` endpoint, same review-authority role tier as
  `resolve_currency_and_vat()` (confirmed at implementation time, not
  reinvented), audited. Never auto-populated, never inferred -- a human
  types it in, exactly like D1's own rule.
- `get_bid_leveling_matrix()`'s `BidLevelingCell` gains
  `normalized_unit_price: Decimal | None` = `unit_price * fx_rate_to_base`
  when the quotation's rate is recorded, else `None` -- shown **alongside**
  `unit_price`/`currency`, never replacing them (the raw figure is always
  present; normalization is an addition a reviewer can ask for, not a
  silent substitution). `Project.base_currency` (already exists) is the
  normalization target.

## 5. LLM exclusion detection: source-text citations (page or cell)

- `ExtractedExclusion` (schema + Pydantic model) gains `source_location:
  string | null` -- for the PDF/image path, the prompt is told to state
  the page number itself if visually determinable (falling back to the
  already-known `page_number` template variable when the model doesn't
  name one); for the XLSX path, a cell/row reference the model copies from
  the now-annotated dump (below). Null when genuinely undeterminable --
  never guessed.
- `dump_workbook_text()` is extended (new `dump_workbook_text_with_refs()`,
  old one kept for any other caller) to prefix each non-empty row with its
  own `SheetName!row<N>:` marker before the tab-joined cell values, so the
  text the LLM actually reads already carries a citable coordinate it can
  copy verbatim, rather than being asked to infer one from nothing.
- **Deterministic verification, not just trusting the model**:
  `QuotationExclusionFlag` gains `citation_verified: boolean` (server
  default false) -- after extraction, a plain substring search for
  `source_quote_text` (normalized: collapsed whitespace, case-preserved)
  within the actual source text that was sent to the model (the PDF page's
  own text layer, or the annotated workbook dump) sets this true on an
  exact match. A citation that doesn't verify is **not** dropped (it might
  still be real -- e.g. from the image the text layer didn't capture) but
  is flagged for a reviewer to double-check specifically, the same
  "surfaced, never silently trusted or silently discarded" posture as
  Phase 4a's `scale_disagreement`.
- `QuotationExclusionFlag.source_location` (nullable) persists the
  citation from `ExtractedExclusion.source_location` above.

## Endpoints (new/changed)

- `PUT /vendors/{id}/service-regions` (vendor-admin tier, whole-set
  replace, same convention as the layer/trade-mapping config tables) /
  `GET` counterpart.
- `PATCH /projects/{id}/location` (structural project-edit tier, confirmed
  at implementation time against the existing project-edit role check).
- `PATCH /quotations/{id}/fx-rate`.
- `get_bid_leveling_matrix()`'s existing endpoint response gains
  `quotation_totals` and each cell's `normalized_unit_price`/
  `uom_mismatch` -- additive, not a breaking response-shape change (new
  optional fields).
- `MatchedVendorOut` gains `service_regions`.

## Testing plan

- Unit: geography-eligibility resolution (project+vendor combinations:
  both set and matching, both set and not matching, either side unset);
  subtotal-mismatch tolerance math; unit-conversion-before-quantity-check
  (convertible-and-converts-clean, convertible-but-genuinely-mismatched,
  not-convertible-at-all); `dump_workbook_text_with_refs()`'s row-marker
  format; citation substring-verification (exact match, whitespace-only
  difference, genuinely absent).
- Integration: `create_rfqs()`'s override flow extended to geography
  (denied without override, allowed with one + audited, at the lowest
  allowed role + a denied role); bid-leveling matrix surfaces
  `quotation_totals`/`normalized_unit_price`/`uom_mismatch` correctly
  end-to-end against real seeded quotations; FX-rate endpoint role gating.
- Dev simulation: extend `simulate-quotes` (or a small new command) to
  exercise a vendor outside the project's emirate (override required), a
  quotation with a deliberately mismatched stated total, a vendor line
  quoted in a convertible-but-different unit, and an exclusion whose
  citation both does and doesn't verify against the source text.

## Explicitly out of scope for this phase

- Geocoding project/vendor addresses into lat/lng automatically -- the
  columns exist for a human (or a later phase) to populate; no external
  geocoding API call is added (standing constraint: no external calls).
- A live FX-rate feed -- recorded rates are always manually entered, per
  the standing "no auto-conversion" rule; this phase does not add any
  external rate-lookup integration.
