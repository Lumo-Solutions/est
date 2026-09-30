from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, Date, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TenantEntity


def _project_fk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)


class TenderPackage(TenantEntity):
    """One upload batch / transmittal."""

    __tablename__ = "tender_packages"

    project_id: Mapped[uuid.UUID] = _project_fk()
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    transmittal_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    received_date: Mapped[date] = mapped_column(Date, nullable=False, server_default=text("CURRENT_DATE"))
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="processing")
    file_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class ProjectDocument(TenantEntity):
    __tablename__ = "project_documents"

    project_id: Mapped[uuid.UUID] = _project_fk()
    package_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tender_packages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_documents.id", ondelete="SET NULL"), nullable=True
    )
    archive_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    ext: Mapped[str] = mapped_column(String(16), nullable=False, server_default="")
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    bucket: Mapped[str] = mapped_column(String(128), nullable=False)
    object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_type_sniffed: Mapped[str | None] = mapped_column(String(32), nullable=True)
    safety_status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="pending")
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    doc_class: Mapped[str | None] = mapped_column(String(32), nullable=True)
    sub_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    document_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    revision_label: Mapped[str | None] = mapped_column(String(32), nullable=True)
    doc_metadata: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    evidence: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    flags: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="received")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    duplicate_of_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_documents.id", ondelete="SET NULL"), nullable=True
    )
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_documents.id", ondelete="SET NULL"), nullable=True
    )
    routed_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    routed_ref: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    # Who decided the current class: 'ai' | 'rules' | 'user'. auto_accepted: routed without a person.
    classified_by: Mapped[str | None] = mapped_column(String(16), nullable=True)
    auto_accepted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)


class DocumentClassification(TenantEntity):
    """Append-only: every proposal, with where it came from."""

    __tablename__ = "document_classifications"

    project_id: Mapped[uuid.UUID] = _project_fk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    doc_class: Mapped[str] = mapped_column(String(32), nullable=False)
    sub_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    evidence: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    doc_metadata: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")


class Addendum(TenantEntity):
    __tablename__ = "addenda"
    __table_args__ = (UniqueConstraint("document_id", name="uq_addenda_document"),)

    project_id: Mapped[uuid.UUID] = _project_fk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_documents.id", ondelete="CASCADE"), nullable=False
    )
    package_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tender_packages.id", ondelete="SET NULL"), nullable=True
    )
    addendum_no: Mapped[str | None] = mapped_column(String(32), nullable=True)
    issue_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    routed_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))
    flagged_settlement_ids: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))


class AddendumLink(TenantEntity):
    __tablename__ = "addendum_links"

    project_id: Mapped[uuid.UUID] = _project_fk()
    addendum_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("addenda.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_documents.id", ondelete="SET NULL"), nullable=True
    )
    reference_text: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False, server_default="supersedes")
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")


class TenderClassConfig(TenantEntity):
    """Per-tenant override of a default class (rename / disable). Defaults live in code."""

    __tablename__ = "tender_class_config"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_tender_class_config_tenant_code"),)

    code: Mapped[str] = mapped_column(String(32), nullable=False)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
