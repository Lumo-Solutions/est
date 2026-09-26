"""Module C2: inbound quotation ingestion, normalisation, and bid leveling.

Two tables (InboundEmail, QuotationAttachment) use NullableTenantEntity, not
TenantEntity: an email's tenant is identified from the plus-addressed
recipient embedded in its own To: header (app/procurement/inbound_address.py)
*after* it's already been received, so tenant_id starts NULL and is filled in
during matching (app/procurement/inbound_match.py) -- see migration 0016 for
the bespoke RLS this requires (app/db/ddl.py::tenant_policies assumes
tenant_id is NOT NULL). Quotation/QuotationLineItem/QuotationExclusionFlag
are only ever created once a tenant is known, so they're ordinary
TenantEntity rows.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    Date,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import (
    AttachmentSafetyStatus,
    InboundEmailMatchStatus,
    QuotationLineItemStatus,
    QuotationStatus,
)
from app.db.base import NullableTenantEntity, TenantEntity
from app.db.types import DEFAULT_EMBEDDING_DIM


class InboundEmail(NullableTenantEntity):
    """One polled IMAP message, raw and unmodified in S3 (raw_object_key/
    raw_sha256) as evidence, independent of whatever parsing follows.
    tenant_id/rfq_id are set by app/procurement/inbound_match.py; both stay
    NULL when the recipient's tenant-slug segment matches no tenant at all
    (match_status=quarantined_unknown_tenant) -- see docs on Role.PLATFORM_ADMIN."""

    __tablename__ = "inbound_emails"
    __table_args__ = (
        UniqueConstraint("imap_uid_validity", "imap_uid", name="uq_inbound_emails_imap_uid"),
    )

    rfq_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rfqs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    imap_uid_validity: Mapped[str] = mapped_column(String(32), nullable=False)
    imap_uid: Mapped[str] = mapped_column(String(64), nullable=False)
    message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    from_address: Mapped[str] = mapped_column(String(320), nullable=False)
    from_domain: Mapped[str] = mapped_column(String(255), nullable=False)
    to_address: Mapped[str] = mapped_column(String(320), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(998), nullable=True)
    received_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)

    match_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=InboundEmailMatchStatus.QUARANTINED_UNKNOWN_TENANT.value
    )
    # Set even when match_status == matched (e.g. a free-mail sender whose
    # exact contact address doesn't match, or a failed SPF/DKIM/DMARC check)
    # -- SRS change #5. Auto-processing (deterministic/LLM parsing) only
    # proceeds when match_status == matched AND needs_review is false.
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    review_reasons: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")

    spf_result: Mapped[str] = mapped_column(String(16), nullable=False, server_default="unknown")
    dkim_result: Mapped[str] = mapped_column(String(16), nullable=False, server_default="unknown")
    dmarc_result: Mapped[str] = mapped_column(String(16), nullable=False, server_default="unknown")
    auth_results_raw: Mapped[str | None] = mapped_column(Text, nullable=True)

    raw_object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    raw_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    # Human quarantine/flag review workflow (separate from match_status,
    # which is system-assigned and never edited by a reviewer).
    review_status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="open")
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class QuotationAttachment(NullableTenantEntity):
    """Raw attachment bytes, unmodified in S3, plus the outcome of
    app/procurement/attachment_safety.py -- run in a worker, never the web
    process. tenant_id mirrors its InboundEmail's (may be NULL)."""

    __tablename__ = "quotation_attachments"

    inbound_email_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inbound_emails.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # NULL until the email's attachments are triaged (app/workers/tasks/
    # quotation_ingestion.py::_process_inbound_email_body). All attachments
    # on one inbound email that produce a submission link to the SAME
    # Quotation -- one email is one submission, not one Quotation per
    # attachment -- with is_primary marking which one was actually
    # extracted from (our pricing sheet if present, else the first accepted
    # attachment); the rest are supporting documents (e.g. a signed PDF
    # alongside the priced xlsx), never separately extracted as competing
    # quotes.
    quotation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("quotations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type_declared: Mapped[str | None] = mapped_column(String(128), nullable=True)
    content_type_sniffed: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    raw_object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    raw_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    safety_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=AttachmentSafetyStatus.PENDING.value
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)


class Quotation(TenantEntity):
    """One vendor submission for one RFQ -- one per *inbound email*, not one
    per attachment: if the email has several attachments (e.g. a priced
    xlsx and a signed cover PDF), they all belong to this one Quotation
    (QuotationAttachment.quotation_id), with source_attachment_id marking
    which one was actually extracted from; the rest are supporting
    documents, never separately extracted as competing quotes.

    Versioned per (rfq_id, vendor_id): a new reply creates a new row with
    version_no += 1. It only becomes is_current=true automatically when
    doing so is safe -- never when it has zero extracted line items
    (status NEEDS_REVIEW/EXTRACTION_EMPTY), and never when the existing
    current version already has an accepted line item (that always requires
    a reviewer to promote_quotation_version() explicitly, audited) -- see
    app/workers/tasks/quotation_ingestion.py::_create_quotation_version. A
    new version never mutates or supersedes an earlier version's own line
    items either way, so an already-accepted QuotationLineItem is never
    overwritten (SRS change #3). A partial unique index (migration 0016)
    enforces at most one is_current=true row per (rfq_id, vendor_id)."""

    __tablename__ = "quotations"
    __table_args__ = (
        UniqueConstraint("rfq_id", "vendor_id", "version_no", name="uq_quotations_rfq_vendor_version"),
    )

    rfq_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rfqs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vendors.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    package_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("procurement_packages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    inbound_email_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inbound_emails.id", ondelete="SET NULL"), nullable=True
    )
    source_attachment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("quotation_attachments.id", ondelete="SET NULL"), nullable=True
    )

    extraction_method: Mapped[str] = mapped_column(String(32), nullable=False)
    version_no: Mapped[int] = mapped_column(nullable=False, server_default="1")
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    # Both must be resolved (non-NULL) before any line item on this
    # quotation may be accepted -- SRS change #4. NULL means the extractor
    # (deterministic header cells or the LLM) could not determine it; a
    # reviewer resolves it explicitly (see
    # app/services/quotation_ingestion.py::resolve_currency_and_vat).
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    vat_inclusive: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    submitted_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    is_late: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    # proposed | needs_review | rejected. Deliberately no "accepted" value --
    # acceptance is a per-line-item decision (QuotationLineItemStatus); this
    # column only ever moves to needs_review (whole sheet failed identity
    # verification, e.g. reordered/duplicated rows -- SRS change #1) or
    # rejected (an explicit bulk reviewer action).
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=QuotationStatus.PROPOSED.value)

    # Module C Phase 6: subtotal-level arithmetic verification -- LLM path
    # only (the deterministic pricing-sheet template has no independent
    # grand-total cell of its own to check the sum of lines against, so
    # these stay NULL/false there; see app.services.quotation_ingestion::
    # _check_stated_total's docstring).
    stated_total: Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)
    total_mismatch: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    # Bid-leveling-stage FX (Module C), deliberately separate from
    # BidSettlementLineItem.fx_rate/fx_rate_date's own acceptance-stage
    # rate (Module D1, migration 0019) -- a quote reviewed today and
    # settled months later may warrant a different recorded rate at each
    # stage. Never auto-populated -- a human records it (set_quotation_fx_rate).
    fx_rate_to_base: Mapped[float | None] = mapped_column(Numeric(14, 6), nullable=True)
    fx_rate_date: Mapped[date | None] = mapped_column(Date, nullable=True)


class QuotationLineItem(TenantEntity):
    __tablename__ = "quotation_line_items"

    quotation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("quotations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # NULL until matched (LLM path only -- the deterministic path always
    # resolves this from the pricing sheet's hidden row-id column, SRS
    # change #1).
    boq_line_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boq_line_items.id", ondelete="SET NULL"), nullable=True, index=True
    )

    vendor_item_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    vendor_description_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Module B/C Phase 5: embeds f"{vendor_item_text or ''} {vendor_description_text}"
    # (same text shape app.procurement.quotation_matching.match_line_item
    # already fuzzy-matches with). NULL under the same degradation
    # contract as BoqLineItem.description_embedding.
    description_embedding: Mapped[list[float] | None] = mapped_column(Vector(DEFAULT_EMBEDDING_DIM), nullable=True)
    unit_price: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    quantity: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    extended_price_stated: Mapped[float | None] = mapped_column(Numeric(16, 4), nullable=True)
    extended_price_computed: Mapped[float | None] = mapped_column(Numeric(16, 4), nullable=True)
    arithmetic_mismatch: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    quantity_mismatch: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # Module C Phase 6: the unit the vendor actually printed against this
    # line (LLM path only, verbatim, not normalized -- the deterministic
    # path matches by hidden row-id against a BOQ item whose own uom is
    # already authoritative, so it never has its own). quantity_mismatch's
    # comparison above converts through this via app.boq.units when it's
    # convertible-but-different from the matched BOQ item's uom;
    # uom_mismatch is set instead when the two units aren't even the same
    # dimension (e.g. M vs M2) -- a stronger, distinct signal from "the
    # numbers don't match."
    vendor_uom: Mapped[str | None] = mapped_column(String(16), nullable=True)
    uom_mismatch: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    confidence: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False, server_default="1.0")
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    match_method: Mapped[str | None] = mapped_column(String(16), nullable=True)
    remarks_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=QuotationLineItemStatus.PROPOSED.value
    )
    accepted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)


class QuotationExclusionFlag(TenantEntity):
    """An NLP-detected exclusion/qualification buried in the vendor's
    quotation text (e.g. "excludes dewatering"). Always a flag for a human
    to review -- never an automatic adjustment to any total (SRS change to
    C2's original bid-leveling requirement)."""

    __tablename__ = "quotation_exclusion_flags"

    quotation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("quotations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    line_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("quotation_line_items.id", ondelete="SET NULL"), nullable=True
    )
    flag_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_quote_text: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False, server_default="0.5")
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="open")
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    # Module C Phase 6: "page or cell" citation (page number for PDF/image,
    # a sheet!row reference for XLSX -- see dump_workbook_text_with_refs)
    # alongside the verbatim source_quote_text this table already had.
    # citation_verified is set by a deterministic substring search against
    # the actual source text sent to the model, NOT trusted from the
    # model's own say-so -- a citation that doesn't verify is kept, never
    # dropped (it might still be real), just flagged for closer review.
    source_location: Mapped[str | None] = mapped_column(String(64), nullable=True)
    citation_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
