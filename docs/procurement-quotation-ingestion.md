# Module C2: inbound quotation ingestion, normalisation, and bid leveling

Covers the inbound half of Module C (MASTER_SRS.MD §4): polling for vendor
replies, matching them to the RFQ they belong to, safety-checking and
parsing whatever they attached, and a human-in-the-loop accept/reject
workflow feeding bid leveling. Builds entirely on Module C1's schema
(`docs/procurement-rfq.md`) -- no changes to `rfqs`/`procurement_packages`
beyond what C1 already reserved (`RfqStatus.RESPONDED`).

## Sender/RFQ matching (`app/procurement/inbound_match.py`)

The Reply-To C1 puts on every dispatched RFQ email embeds both a tenant
slug and the RFQ's `reply_token`:
`{EMAIL_REPLY_TO_LOCAL_PART}+{tenant_slug}.{reply_token}@{EMAIL_REPLY_TO_DOMAIN}`
(`app/procurement/inbound_address.py`). One shared mailbox receives replies
for every tenant -- the poller identifies which tenant a message belongs to
by parsing this address out of the message's own `To:` header, not from
which physical mailbox it landed in. This mirrors a real provider
(Gmail/Office 365/Postfix with `recipient_delimiter=+`) that folds
`local+ext@domain` into `local@domain` for routing but leaves the message
content addressed exactly as the sender's client set it.

Matching order:
1. Parse the recipient address. Unparseable, or a tenant slug matching no
   `tenants` row -> `quarantined_unknown_tenant`, `tenant_id` stays `NULL`.
2. Tenant known -> look up `reply_token` scoped to that tenant. Not found
   -> `quarantined_no_token`. Found but the RFQ isn't `sent`/`responded`
   -> `quarantined_token_closed`.
3. RFQ open -> `matched`. Independently, the sender identity is checked:
   for a free-mail domain (`FREE_MAIL_DOMAINS`), the exact From address
   must equal a known vendor contact email (a domain match proves nothing
   for gmail.com); for any other domain, the From domain must match
   `vendors.email_domain` or a contact's email domain. A mismatch, a
   vendor with no known domain/contacts on file, or an SPF/DKIM/DMARC
   failure (`Authentication-Results` header, `app/procurement/email_auth.py`)
   sets `needs_review=true` and a reason in `review_reasons` -- the email
   still gets `match_status=matched`, but auto-processing is held.

Auto-processing (attachment safety + parsing) only ever runs when
`match_status == matched AND needs_review == false`. Everything else waits
in the review queue -- nothing is ever silently attached to the wrong RFQ.

## Tenancy: quarantine visibility

Tenants are isolated: a resolved-tenant flagged/quarantined email is only
visible to that tenant's own `procurement_head`+ (ordinary RLS). A message
whose tenant-slug segment matches no tenant at all has `tenant_id = NULL`
and is visible only to the cross-tenant `platform_admin` role
(`app.core.enums.Role.PLATFORM_ADMIN`, provisioned the same way as every
other role -- a Keycloak realm role assignment, see
`deploy/keycloak/realm-installtec.json`). `inbound_emails`/
`quotation_attachments` use `NullableTenantEntity` (`app/db/base.py`) and
bespoke RLS (migration 0016) instead of `app/db/ddl.py::tenant_policies`,
which assumes `tenant_id` is `NOT NULL`.

`app/services/quotation_ingestion.py::resolve_inbound_email_tenant`
(platform_admin-only) attaches an unresolved email to a tenant the operator
identified some other way. **Gotcha found while testing this**: Postgres's
RLS for `UPDATE` requires the *post-update* row to still pass the table's
`SELECT` policy, not just the `UPDATE` policy's own `WITH CHECK` -- once
`tenant_id` moves off `NULL`, the platform_admin's own SELECT-policy
branches both go false (neither "IS NULL" nor "= their own unrelated
tenant"), so an ordinary write would violate RLS even though the
*authorization* decision was already correctly enforced at the application
layer. The fix is the same shape as `app/services/audit.py::record`'s
raw-INSERT-with-no-RETURNING: this one write runs under a tenant-scoped
system context (`set_rls_context`), not the caller's own, then restores it.
See that function's docstring and
`tests/integration/test_quotation_ingestion_review.py`.

Once attached to an RFQ (`attach_inbound_email_to_rfq`, requires a reason,
audited -- same `is_override`/`override_reason` shape as C1's vendor-match
override), a tenant's own `procurement_head`+ takes over from their normal
queue; `resolve_inbound_email_tenant` never matches a reply token itself.

## Attachment safety (`app/procurement/attachment_safety.py`)

Runs only in a Celery worker (`quotation` queue), never the web process.
Content-sniffed by magic bytes, not the declared filename extension:

- Allow-list: `.xlsx`, `.csv`, `.pdf`, `.jpg`/`.jpeg`, `.png`. `.xlsm` is
  rejected by extension alone, and any zip-based file containing a
  `vbaProject.bin` is rejected regardless of extension.
- Size cap (`QUOTATION_MAX_ATTACHMENT_SIZE_BYTES`) checked before any
  parsing. PDF page cap (`QUOTATION_MAX_PDF_PAGES`).
- Zip-bomb guard: entry count, per-entry and total uncompressed size, and
  compression-ratio thresholds, checked via `zipfile.ZipFile.infolist()`
  *before* ever handing bytes to `openpyxl`.
- Password-protected/legacy-binary Office files are rejected by their OLE
  compound-file signature (`D0 CF 11 E0 A1 B1 1A E1`) before parsing.
  Encrypted PDFs are rejected via `pypdf`'s `is_encrypted`.
- Images go through Pillow's built-in decompression-bomb guard
  (`Image.MAX_IMAGE_PIXELS`).

## Deterministic parsing (`app/procurement/pricing_sheet_parser.py`)

Only attempted when the attachment is an `.xlsx` whose sheet names match
our own template (`_meta` + `Pricing`, `looks_like_our_pricing_sheet`).
Trusts the hidden, always-locked column **G** on the `Pricing` sheet
(`G{row}` = that row's `boq_line_item_id`, written by
`app/procurement/pricing_sheet.py::build_pricing_workbook`) for row
identity -- never row position. If the returned sheet's set of row-ids
doesn't exactly match what was sent (a row reordered is fine -- the id
moves with it; inserted, deleted, or duplicated is not), the whole
quotation goes to `needs_review` with **no line items created** rather than
a best-effort partial mapping. `_meta`'s `rfq_id`/`reply_token` must also
match the RFQ the inbound email was matched to.

A Rate cell that's a formula with no cached value (openpyxl never computes
formulas itself), or non-numeric text, is flagged `needs_review` at the
*line* level -- never silently read as `0`/blank. A genuinely empty Rate
cell (vendor didn't price that line) is not an error.

Currency (`B2`, pre-filled with the tendering project's `base_currency`)
and "prices include VAT?" (`E2`) are also on the template, editable by the
vendor -- both `NULL` until recognized text is found, same as the LLM path.

## LLM extraction (`app/procurement/quotation_extraction.py`)

Used for anything else the safety check accepts: PDF (rendered to a page
image via `app.takeoff.pdf.render_page_png`, reused from Module B), a
photo/scan, a non-template spreadsheet (cell text dumped via
`dump_workbook_text`), or CSV. Calls the same `extract_json` guided-JSON
primitive Module B's title-block extraction uses
(`app/integrations/vllm.py`), constrained to
`ai-service/schemas/quotation_extraction.schema.json`.

That schema has **no field for a BOQ line item id, an action, or a
status** -- matching an extracted row to a BOQ item is a separate,
deterministic step (`app/procurement/quotation_matching.py`, rapidfuzz text
matching against the RFQ's own known items; below `MIN_MATCH_SCORE` the
line is created unmatched, `needs_review`, for manual mapping). The
system prompt also explicitly instructs the model to treat any
instruction-like text inside the document as content, never a command --
see `tests/unit/test_quotation_llm_output_boundary.py` for the schema/
Pydantic-model boundary this depends on, and `ai-service/tests/test_prompt_contract.py`
for the prompt-injection-warning assertion.

Every LLM-extracted `QuotationLineItem` also gets `arithmetic_mismatch`
(unit price × quantity vs. the vendor's own stated total) and
`quantity_mismatch` (vendor-stated quantity vs. the BOQ's) flags -- review
signals, never automatic total adjustments.

## Quote versions (SRS change #3)

Every new parse for the same `(rfq_id, vendor_id)` is a new `quotations`
row: `version_no` increments, the previous row's `is_current` flips to
`false` in the same transaction
(`app/workers/tasks/quotation_ingestion.py::_create_quotation_version`), and
a partial unique index (`uq_quotations_current_per_rfq_vendor`, migration
0016) enforces exactly one current version. A new version **never**
mutates an earlier version's own `quotation_line_items` rows -- an accepted
line stays accepted regardless of what a later reply contains. A reviewer
can accept a line item from any version, not only the current one.

## Human-in-the-loop accept/reject (`app/services/quotation_ingestion.py`)

Every extracted price is `status=proposed` (or `needs_review`) until a
`procurement_head`+ actor calls `accept_line_item`/`reject_line_item`.
**Accepting is blocked** (`ValidationAppError`) until the quotation's
`currency` and `vat_inclusive` are both resolved -- either by the
extractor, or explicitly by a reviewer (`resolve_currency_and_vat`,
defaulting the tenant/project's own base currency as the visible template
suggestion, never assumed silently). Confidence and source
(`deterministic` vs `llm`) are shown per line so a reviewer knows how much
scrutiny a row needs.

## Bid leveling (`get_bid_leveling_matrix`)

Reads only `status=accepted` line items, grouped by `boq_line_item_id`
across vendors. Each cell carries its own `currency`/`vat_inclusive` --
there is no FX conversion or VAT normalisation anywhere in this module;
mismatched bases are shown side by side for a human to reconcile, never
merged or silently converted.

## Dev/test IMAP: GreenMail, not Mailpit

Mailpit (C1's dev SMTP sink) has **no IMAP server** at all -- verified
against the pinned `axllent/mailpit` image's own `--help` output (only
SMTP/POP3/HTTP). [GreenMail](https://greenmail-mail-test.github.io/greenmail/)
is the dev/test IMAP source instead (`deploy/docker-compose.yml`).
`app/workers/tasks/quotation_ingestion.py::_assert_dev_imap_host_is_safe`
mirrors `resolve_recipient`'s fail-closed posture: whenever
`APP_ENV != "production"`, `IMAP_HOST` must equal `IMAP_DEV_ALLOWED_HOST`
(default `greenmail`) or the poller refuses to start.

GreenMail creates one mailbox per *exact* recipient address on SMTP
delivery -- it does not fold `+extensions` into a base mailbox the way a
real provider does. To simulate a vendor reply against GreenMail, send it
with the **envelope** RCPT TO set to the poller's bare mailbox
(`IMAP_USER`, e.g. `rfq@installtec.local`) while the message's own `To:`
header carries the real plus-addressed recipient -- exactly what a real
folding provider itself hands to IMAP after routing. The poller identifies
tenant/token from the header, not from which mailbox it polled, so this is
a faithful simulation, not a divergent shortcut:

```python
import smtplib
msg = ...  # To: header = "rfq+<tenant-slug>.<reply_token>@installtec.local"
with smtplib.SMTP("localhost", 3025) as s:
    s.sendmail("vendor@example.com", ["rfq@installtec.local"], msg.as_string())
```

## Queues

`poll_inbound_mailbox` (IMAP I/O only) shares C1's `email` queue.
`process_attachment` (untrusted-input safety checks + deterministic
parsing) runs on its own `quotation` queue/worker, isolated from both the
SMTP/IMAP worker and the vLLM worker so a hostile or oversized attachment
can never back up outbound dispatch, inbound polling, or Module B's
drawing ingestion. `extract_quotation` shares Module B's vLLM-backed `vlm`
queue.
