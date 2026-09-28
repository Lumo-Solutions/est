from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel

from app.schemas.common import ORMModel


class AuthorityOut(ORMModel):
    id: UUID
    code: str
    name: str
    jurisdiction: str | None


class CertificateTypeOut(ORMModel):
    id: UUID
    authority_id: UUID
    code: str
    name: str
    validity_months: int | None
    is_mandatory: bool
    warn_days_before: int


class VendorCertificateCreate(BaseModel):
    vendor_id: UUID
    certificate_type_id: UUID
    certificate_no: str | None = None
    issue_date: date | None = None
    expiry_date: date | None = None
    document_object_key: str | None = None
    document_sha256: str | None = None


class VendorCertificateOut(ORMModel):
    id: UUID
    vendor_id: UUID
    certificate_type_id: UUID
    certificate_no: str | None
    issue_date: date | None
    expiry_date: date | None
    status: str
    verified_by: UUID | None
    verified_at: datetime | None


class ExpiringVendorCertificateOut(ORMModel):
    """Phase 3 gap-fill (docs/ui-qa-brief.md): the home dashboard's
    "certificates expiring" tile needs a vendor name to be useful -- a bare
    VendorCertificateOut's vendor_id alone isn't human-readable."""

    id: UUID
    vendor_id: UUID
    vendor_name: str
    certificate_type_id: UUID
    expiry_date: date
    status: str


class PrequalificationDecision(BaseModel):
    status: str
    grade: str | None = None
    max_award_value: float | None = None
    scope_trade_node_id: UUID | None = None
    effective_from: date
    decision_note: str | None = None


class VendorPrequalificationOut(ORMModel):
    id: UUID
    vendor_id: UUID
    status: str
    grade: str | None
    max_award_value: float | None
    scope_trade_node_id: UUID | None
    decided_by: UUID | None
    decided_at: datetime | None
    decision_note: str | None
