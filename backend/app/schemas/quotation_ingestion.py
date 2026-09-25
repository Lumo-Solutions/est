from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class InboundEmailOut(ORMModel):
    id: UUID
    tenant_id: UUID | None
    rfq_id: UUID | None
    from_address: str
    from_domain: str
    to_address: str
    subject: str | None
    received_at: datetime
    match_status: str
    needs_review: bool
    review_reasons: list[str]
    spf_result: str
    dkim_result: str
    dmarc_result: str
    raw_object_key: str
    raw_sha256: str
    review_status: str
    reviewed_by: UUID | None
    reviewed_at: datetime | None
    review_note: str | None
    created_at: datetime


class QuotationAttachmentOut(ORMModel):
    id: UUID
    inbound_email_id: UUID
    filename: str
    content_type_declared: str | None
    content_type_sniffed: str | None
    size_bytes: int
    safety_status: str
    rejection_reason: str | None
    processed_at: datetime | None


class QuotationOut(ORMModel):
    id: UUID
    rfq_id: UUID
    vendor_id: UUID
    package_id: UUID
    project_id: UUID
    extraction_method: str
    version_no: int
    is_current: bool
    currency: str | None
    vat_inclusive: bool | None
    submitted_at: datetime
    is_late: bool
    status: str
    created_at: datetime


class QuotationLineItemOut(ORMModel):
    id: UUID
    quotation_id: UUID
    boq_line_item_id: UUID | None
    vendor_item_text: str | None
    vendor_description_text: str | None
    unit_price: Decimal | None
    quantity: Decimal | None
    extended_price_stated: Decimal | None
    extended_price_computed: Decimal | None
    arithmetic_mismatch: bool
    quantity_mismatch: bool
    confidence: Decimal
    source: str
    match_method: str | None
    remarks_text: str | None
    status: str
    accepted_by: UUID | None
    accepted_at: datetime | None


class QuotationExclusionFlagOut(ORMModel):
    id: UUID
    quotation_id: UUID
    line_item_id: UUID | None
    flag_text: str
    source_quote_text: str
    confidence: Decimal
    status: str
    reviewed_by: UUID | None
    reviewed_at: datetime | None


class ResolveInboundTenantRequest(BaseModel):
    tenant_id: UUID
    note: str = Field(min_length=1)


class DismissInboundEmailRequest(BaseModel):
    note: str = Field(min_length=1)


class AttachInboundEmailRequest(BaseModel):
    rfq_id: UUID
    reason: str = Field(min_length=1)


class ResolveCurrencyVatRequest(BaseModel):
    currency: str = Field(min_length=3, max_length=3)
    vat_inclusive: bool


class RejectQuotationRequest(BaseModel):
    reason: str = Field(min_length=1)


class BidLevelingCellOut(ORMModel):
    quotation_id: UUID
    vendor_id: UUID
    unit_price: Decimal
    currency: str
    vat_inclusive: bool
    confidence: float
    arithmetic_mismatch: bool
    quantity_mismatch: bool


class BidLevelingRowOut(ORMModel):
    boq_line_item_id: UUID
    cells: list[BidLevelingCellOut]
