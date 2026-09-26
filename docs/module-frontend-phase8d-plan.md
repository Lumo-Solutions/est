# Phase 8d plan: procurement + bid leveling

Per `docs/module-frontend-phase8-plan.md` §2's sub-phase breakdown.

## 0. What already exists (confirmed by reading the backend code)

Read `app/api/v1/routes/{procurement,quotation_ingestion}.py` and their
schemas in full before writing this, and cross-checked every route
against every `async def` in the corresponding service files (the same
audit method that found Phase 8b's two gaps and confirmed Phase 8c had
none).

- **Procurement**: package create/list/get, add/list package items,
  matched-vendors (eligible/ineligible + reason), RFQ create (one per
  vendor, `override_reason` for an ineligible vendor)/list/get/dispatch/
  resend -- all already exposed. Dispatch/resend's role + MFA step-up
  check happens inside the service, not a route dependency, so the UI's
  step-up interception (Phase 8a's API client) is what actually handles
  a 403 here, same as everywhere else.
- **Quotation ingestion**: the quarantine queue
  (`GET /quotation-inbound-review`, resolve-tenant [`platform_admin`
  only]/dismiss/attach), quotations per RFQ, quotation line items,
  attachments, **version promotion** (`POST /quotations/{id}/promote`,
  keyed off `Quotation.version_no`/`is_current`), currency/VAT
  resolution, quotation reject, line-item accept/reject (quote
  "acceptance" is at line-item granularity -- there is no whole-quotation
  accept, only reject), the bid-leveling matrix, quotation totals, and
  FX-rate recording -- all already exposed.
- **One real, narrow gap found** (mirrors Phase 8b's pattern; Phase 8c
  had none): **no endpoint listed a quotation's exclusion flags** --
  `acknowledge_exclusion_flag` takes a caller-supplied `flag_id`, but
  nothing let the UI discover which flags exist for a quotation in the
  first place. The brief's "bid-leveling matrix with exclusion flags and
  citations" cannot be built without this. **Fixed**: `app/services/
  quotation_ingestion.py::list_exclusion_flags()` (mirrors
  `list_quotation_line_items`'s exact shape) + `GET
  /quotations/{id}/exclusion-flags`, reusing the existing
  `QuotationExclusionFlagOut` schema (already fully shaped for this --
  `source_location`/`citation_verified` were already there from Phase 6,
  just never listable). Integration-tested by extending the existing
  Phase 6 citation-verification test with one more assertion, rather than
  writing a new seed from scratch.
- `BidLevelingCellOut` carries `quotation_id` per cell but no embedded
  exclusion-flag data -- the UI fetches a selected cell's quotation's
  flags separately via the new endpoint, keeping the matrix response
  itself unchanged (additive-only, no risk to Phase 6's existing shape).

## 1. Screens

- **Procurement packages and RFQs** (`/projects/:id/procurement/packages`):
  package list + create; selecting a package shows its BOQ items (add
  more via a multi-select from the project's own BOQ items), matched
  vendors (eligible/ineligible + reason), an RFQ-creation form (vendor
  multi-select, due date, an override-reason field that only becomes
  required -- client-side, the server is the real check -- when an
  ineligible vendor is selected), and the RFQ list with dispatch/resend
  (resend requires a reason, per `RfqResendRequest`).
- **Quarantine and review queue**
  (`/projects/:id/procurement/quarantine`): the inbound-review list
  (`needs_review`/`review_reasons`, SPF/DKIM/DMARC results) with
  resolve-tenant (role-gated to `platform_admin` in the UI, matching the
  server), dismiss (note), and attach-to-RFQ (pick an RFQ + reason)
  actions.
- **Quote review and acceptance, plus version promotion**
  (`/projects/:id/procurement/quotes`): pick a package, then an RFQ
  within it, then see every quotation version submitted against that
  RFQ (`version_no`, `is_current`); each quotation's line items can be
  accepted/rejected individually, currency/VAT resolved, the whole
  quotation rejected, or a specific version promoted to current.
- **Bid-leveling matrix with exclusion flags and citations**
  (`/projects/:id/procurement/bid-leveling`): pick a package, see the
  matrix (rows = BOQ items, cells = per-vendor `unit_price`/`currency`/
  `normalized_unit_price`, mismatch flags); selecting a cell fetches and
  shows that quotation's exclusion flags (`flag_text`,
  `source_quote_text`, `source_location`, `citation_verified`) via the
  new endpoint above, plus the package's `quotation-totals` summary.

## 2. Explicitly out of scope for 8d

- Settlement, export, win/loss, admin, audit -- 8e-8f.
- Any change to dispatch/email-sending behaviour itself -- this phase
  only adds a UI in front of the existing dispatch/resend endpoints.
