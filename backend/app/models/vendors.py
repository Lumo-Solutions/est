from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import DuplicateCandidateStatus, VendorStatus
from app.db.base import TenantEntity


class Vendor(TenantEntity):
    __tablename__ = "vendors"

    legal_name: Mapped[str] = mapped_column(String(255), nullable=False)
    trading_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False)
    trade_license_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    normalized_license: Mapped[str | None] = mapped_column(String(64), nullable=True)
    license_authority: Mapped[str | None] = mapped_column(String(64), nullable=True)
    trn_vat_no: Mapped[str | None] = mapped_column(String(32), nullable=True)
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    emirate: Mapped[str | None] = mapped_column(String(32), nullable=True)
    address_line: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    primary_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    email_domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    primary_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    phone_e164: Mapped[str | None] = mapped_column(String(20), nullable=True)
    phone_last9: Mapped[str | None] = mapped_column(String(9), nullable=True)
    website_domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=VendorStatus.DRAFT.value)
    merged_into_vendor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vendors.id", ondelete="SET NULL"), nullable=True
    )
    contact_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class VendorContact(TenantEntity):
    __tablename__ = "vendor_contacts"

    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role_title: Mapped[str | None] = mapped_column(String(128), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")


class VendorTrade(TenantEntity):
    __tablename__ = "vendor_trades"
    __table_args__ = (
        UniqueConstraint("vendor_id", "trade_node_id", name="uq_vendor_trades_vendor_trade"),
    )

    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False, index=True
    )
    trade_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trade_nodes.id", ondelete="RESTRICT"), nullable=False
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    capability_notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class VendorServiceRegion(TenantEntity):
    """Module C Phase 6: which emirates a vendor is willing to serve --
    distinct from Vendor.emirate (the vendor's own registered/home-base
    location, single-valued). A vendor with zero rows here is "region
    unknown": app.services.procurement::_vendor_eligibility never treats
    that as either "available everywhere" or "ineligible" on its own --
    see that function's own docstring."""

    __tablename__ = "vendor_service_regions"
    __table_args__ = (UniqueConstraint("vendor_id", "emirate", name="uq_vendor_service_regions_vendor_emirate"),)

    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False, index=True
    )
    emirate: Mapped[str] = mapped_column(String(32), nullable=False)


class VendorDuplicateCandidate(TenantEntity):
    __tablename__ = "vendor_duplicate_candidates"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "vendor_a_id", "vendor_b_id", name="uq_vendor_dupes_tenant_pair"
        ),
    )

    vendor_a_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False
    )
    vendor_b_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False
    )
    score: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    signals: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default=DuplicateCandidateStatus.OPEN.value
    )
    detected_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
