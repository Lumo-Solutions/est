from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import DATERANGE, TIMESTAMP, UUID
from sqlalchemy.dialects.postgresql.ranges import Range
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import CertificateStatus, PrequalificationStatus
from app.db.base import TenantEntity


class Authority(TenantEntity):
    __tablename__ = "authorities"

    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    jurisdiction: Mapped[str | None] = mapped_column(String(64), nullable=True)


class CertificateType(TenantEntity):
    __tablename__ = "certificate_types"

    authority_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("authorities.id", ondelete="RESTRICT"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    validity_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_mandatory: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    warn_days_before: Mapped[int] = mapped_column(Integer, nullable=False, server_default="60")


class VendorCertificate(TenantEntity):
    __tablename__ = "vendor_certificates"

    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False, index=True
    )
    certificate_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("certificate_types.id", ondelete="RESTRICT"), nullable=False
    )
    certificate_no: Mapped[str | None] = mapped_column(String(128), nullable=True)
    issue_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default=CertificateStatus.PENDING_VERIFICATION.value
    )
    document_object_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    document_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    verified_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)


class VendorPrequalification(TenantEntity):
    """Effective-dated status; overlapping periods for the same
    (vendor, scope_trade_node) are rejected by a GiST exclusion constraint
    created in the migration (SQLAlchemy has no ORM-level EXCLUDE support)."""

    __tablename__ = "vendor_prequalifications"

    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default=PrequalificationStatus.PENDING.value
    )
    grade: Mapped[str | None] = mapped_column(String(16), nullable=True)
    max_award_value: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    scope_trade_node_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trade_nodes.id", ondelete="RESTRICT"), nullable=True
    )
    effective_period: Mapped[Range[date]] = mapped_column(DATERANGE, nullable=False)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vendor_prequalifications.id", ondelete="SET NULL"), nullable=True
    )


class CertificateAlert(TenantEntity):
    __tablename__ = "certificate_alerts"

    vendor_certificate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vendor_certificates.id", ondelete="CASCADE"), nullable=False
    )
    alert_type: Mapped[str] = mapped_column(String(16), nullable=False)  # expiring | expired
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    notified_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
