from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class ProcurementPackageCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    trade_node_id: UUID | None = None
    due_at: datetime | None = None
    notes: str | None = None


class ProcurementPackageOut(ORMModel):
    id: UUID
    project_id: UUID
    trade_node_id: UUID | None
    name: str
    status: str
    due_at: datetime | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class ProcurementPackageItemsAdd(BaseModel):
    boq_line_item_ids: list[UUID] = Field(min_length=1)


class ProcurementPackageItemOut(ORMModel):
    id: UUID
    package_id: UUID
    boq_line_item_id: UUID


class MatchedVendorOut(BaseModel):
    vendor_id: UUID
    legal_name: str
    primary_email: str | None
    emirate: str | None
    country: str | None
    eligible: bool
    ineligible_reason: str | None = None
    service_regions: list[str] = []


class RfqCreateRequest(BaseModel):
    """Drafts one RFQ per vendor_id against the package's current items.
    `override_reason` is required (and only usable by procurement_head+) for
    any vendor_id that app.services.procurement.match_vendors would not have
    returned as eligible -- see MASTER_SRS.MD Module C default #6."""

    vendor_ids: list[UUID] = Field(min_length=1)
    due_at: datetime | None = None
    override_reason: str | None = None


class RfqOut(ORMModel):
    id: UUID
    package_id: UUID
    project_id: UUID
    vendor_id: UUID
    vendor_contact_id: UUID | None
    rfq_ref: str | None
    status: str
    due_at: datetime | None
    is_override: bool
    override_reason: str | None
    message_id: str | None
    dispatch_attempts: int
    dispatch_error: str | None
    queued_at: datetime | None
    sent_at: datetime | None
    created_at: datetime


class RfqResendRequest(BaseModel):
    reason: str = Field(min_length=1)
