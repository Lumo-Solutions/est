# Module C1: procurement packages & RFQ dispatch

Covers the outbound half of Module C (MASTER_SRS.MD §4, "AI Procurement &
Bid Leveling"): grouping BOQ line items into a procurement package, matching
vendors by trade + active prequalification, and dispatching a priced-sheet
RFQ by email. Module C2 (inbound quotation ingestion, normalisation, bid
leveling) is a separate sub-phase built on top of this schema.

## Data model

- `procurement_packages` -- a trade-scoped group of BOQ line items for one
  project (`app/models/procurement.py::ProcurementPackage`).
- `procurement_package_items` -- join to `boq_line_items`.
- `rfqs` -- one row per `(package, vendor)` dispatch. `rfq_ref` (e.g.
  `RFQ-2026-0042`) is assigned by a `BEFORE INSERT` trigger
  (`rfqs_assign_ref_trg`, migration 0015) from a per-tenant/per-year counter
  table (`procurement_rfq_counters`) -- the same "increment under row lock"
  shape `audit_events_chain_trg()` uses, so it's unique and gap-free under
  concurrent draft creation with no client-visible retry.

`rfqs.status`: `draft -> queued -> sent | failed`. `responded`/`expired`
exist in `app.core.enums.RfqStatus` but are not produced by C1 -- reserved
for C2 so no further migration is needed to record a vendor's reply or an
unanswered RFQ.

## Vendor matching (`app/services/procurement.py::match_vendors`)

Matches `vendor_trades` for the package's `trade_node_id`, filtered to
`Vendor.status == "active"`, then checks each candidate's prequalification
(`VendorPrequalification`, Module A) as of today: eligible only if it has an
`approved`/`conditional` row scoped either to that exact trade or to "all
trades" (`scope_trade_node_id IS NULL`, a blanket prequalification). No
matching row, an expired one, or one in `pending`/`suspended`/`rejected`/
`blacklisted` excludes the vendor. Geography is not auto-matched (no
location field on `projects` yet) -- filter the returned list by
`emirate`/`country` client-side, or use `vendors.emirate` in a query.

**Override**: `POST .../rfqs` with an `override_reason` lets a
`procurement_head`+ actor draft an RFQ for a vendor that failed the
eligibility check above. Both the attempt and the reason are captured in the
audit trail (`is_override`/`override_reason` on the `Rfq` row itself, plus
the `AuditAction.CREATE` event's payload).

## RFQ content boundary

An RFQ (email body and the attached `.xlsx`) may only ever show
`item_no`/`description`/`unit`/`quantity` -- never a rate, cost, budget,
estimate, or any vendor's name other than the one being addressed. This is
enforced by `app/procurement/content.py::RfqLineItem`, a dataclass that
*only* carries those four fields: `app/workers/tasks/procurement.py` builds
this dataclass from `BoqLineItem` rows and passes it into both the email
renderer and the pricing-sheet builder, so there is no code path where a
`CostItem`/rate value could leak into either. `ProcurementPackage.notes`
(free-text internal commentary) is likewise never passed to either
renderer. See `tests/unit/test_procurement_content_boundary.py`.

## Dispatch pipeline

`POST /rfqs/{id}/dispatch` (`procurement_head`+, MFA step-up -- see
`app/services/procurement.py::_require_dispatch_authority`) marks the RFQ
`queued` and enqueues `app.workers.tasks.procurement.dispatch_rfq_task` on
the dedicated `email` Celery queue (kept separate from Module B's `ingest`
queue so an SMTP outage never backs up drawing ingestion). The task itself:

1. Re-fetches the package's current BOQ items (so the snapshot reflects
   the latest content, not whatever was true when dispatch was requested).
2. Renders the HTML email (`app/procurement/rendering.py`) and the `.xlsx`
   pricing sheet (`app/procurement/pricing_sheet.py`).
3. Sends via SMTP (`app/procurement/mailer.py`).
4. On success: stores `subject`/`body_html`/`attachment_object_key`/
   `attachment_sha256`/`message_id`/`sent_at` on the `Rfq` row -- the durable
   record of exactly what the vendor received -- uploads the `.xlsx` to
   `S3_BUCKET_PROCUREMENT`, and records an `AuditAction.SEND` event. In the
   dev stack, that bucket needs a SeaweedFS IAM grant, not just to exist --
   see `docs/deploy-deltas.md`'s `seaweedfs` row and
   `deploy/seaweedfs/check-identity-grants.sh`.
5. On failure (SMTP error, misconfiguration, no contactable email): sets
   `status=failed` and `dispatch_error`, and records `AuditAction.SEND` with
   `result=failed`. `attachment_object_key`/`attachment_sha256` stay `NULL`
   -- nothing was actually delivered.

**Idempotency**: the task's first action is to check the RFQ is still
`queued`; a Celery redelivery of a task that already completed (success or
failure already recorded) is a no-op. A `draft`/`failed` RFQ can be
re-dispatched via `POST /rfqs/{id}/dispatch` (retry). An already
`sent`/`queued` RFQ requires the explicit `POST /rfqs/{id}/resend` endpoint
(same role + step-up gate, plus a required `reason`, always audited) -- this
is also the escape hatch for an RFQ stuck in `queued` (e.g. a lost task).

## Dev/test email safety (`EMAIL_REDIRECT_ALL_TO`)

`app/procurement/mailer.py::resolve_recipient` redirects **every** RFQ
email to `EMAIL_REDIRECT_ALL_TO` whenever `APP_ENV != "production"`,
regardless of what `SMTP_HOST` points at, and logs the vendor's real
address as `original_to` (also recorded in the `AuditAction.SEND` payload).
If that setting is blank in a non-production environment, dispatch is
refused outright (`EmailMisconfiguredError`) rather than risk falling
through to the vendor's real address. In production the redirect is a
no-op (RFQs go to the vendor as normal) regardless of whether the setting
happens to be set.

The dev stack's default (`deploy/.env.example`) points `SMTP_HOST` at the
bundled Mailpit service (`http://localhost:8025` for its web UI) and
`EMAIL_REDIRECT_ALL_TO` at an address Mailpit catches regardless of its
literal value (Mailpit accepts any recipient).

## Reply correlation (for Module C2)

Every dispatched RFQ carries two independent correlation handles so C2's
IMAP poller can match an inbound reply back to the exact `Rfq` row without
depending on any single vendor mail client preserving threading headers:

- **`Reply-To` plus-addressing**: `{EMAIL_REPLY_TO_LOCAL_PART}+{reply_token}
  @{EMAIL_REPLY_TO_DOMAIN}` (default `rfq+<token>@installtec.local`), where
  `reply_token` is `Rfq.reply_token` (a `secrets.token_urlsafe(32)` value,
  unique per RFQ). A reply routed to this address lets C2 recover the token
  directly from the recipient address it arrived at.
- **`Message-ID`**: a standard RFC 5322 `Message-ID` (`email.utils.
  make_msgid`), stored on `Rfq.message_id`, for clients that do preserve
  `In-Reply-To`/`References`.
- **The hidden `_meta` worksheet** in the attached `.xlsx`
  (`app/procurement/pricing_sheet.py::_write_meta_sheet`) carries
  `rfq_id`/`rfq_ref`/`reply_token` plus a `pricing_row -> boq_line_item_id`
  map, so a returned spreadsheet can be parsed deterministically even if
  the vendor reorders or deletes rows, and even if the reply's headers and
  envelope recipient are both lost (e.g. forwarded through a shared mailbox).
