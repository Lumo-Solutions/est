from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import ORMModel


class VendorCreate(BaseModel):
    legal_name: str = Field(min_length=1, max_length=255)
    trading_name: str | None = None
    trade_license_no: str | None = None
    license_authority: str | None = None
    trn_vat_no: str | None = None
    country: str | None = Field(default=None, max_length=2)
    emirate: str | None = None
    address_line: str | None = None
    primary_email: EmailStr | None = None
    primary_phone: str | None = None
    website_domain: str | None = None
    notes: str | None = None


class VendorOut(ORMModel):
    id: UUID
    legal_name: str
    trading_name: str | None
    trade_license_no: str | None
    license_authority: str | None
    trn_vat_no: str | None
    country: str | None
    emirate: str | None
    address_line: str | None
    primary_email: str | None
    primary_phone: str | None
    website_domain: str | None
    status: str
    notes: str | None
    created_at: datetime
    updated_at: datetime


class DuplicateSignal(BaseModel):
    score: float
    signals: dict[str, float]


class DuplicateCandidateOut(ORMModel):
    id: UUID
    vendor_a_id: UUID
    vendor_b_id: UUID
    score: float
    signals: dict[str, float] | None
    status: str
    detected_at: datetime


class DuplicateCandidatePreview(BaseModel):
    """Result of a pre-flight duplicate check (POST /vendors:check-duplicates)
    -- no candidate row is persisted, so there is no `id` yet."""

    existing_vendor_id: UUID
    existing_vendor_name: str
    score: float
    signals: dict[str, float]


class DuplicateCheckResult(BaseModel):
    candidates: list[DuplicateCandidatePreview]
    highest_score: float


class DuplicateResolveRequest(BaseModel):
    resolution: str = Field(pattern="^(confirmed_duplicate|not_duplicate|merged)$")
    resolution_note: str | None = None
