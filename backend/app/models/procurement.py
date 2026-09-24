from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import ProcurementPackageStatus, RfqStatus
from app.db.base import TenantEntity


class ProcurementPackage(TenantEntity):
    """A trade-scoped group of BOQ line items sent out for pricing together
    (e.g. "Earthworks - Villas Cluster A"). Module C1 covers draft -> sent;
    "closed" (award recorded) is Module D's settled-bid territory."""

    __tablename__ = "procurement_packages"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    trade_node_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trade_nodes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=ProcurementPackageStatus.DRAFT.value)
    due_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class ProcurementPackageItem(TenantEntity):
    """Join row: one boq_line_items row included in one package's RFQ
    content. Many-to-one from the package side, same shape as
    BoqLineItemMeasurement (app/models/boq.py)."""

    __tablename__ = "procurement_package_items"
    __table_args__ = (
        UniqueConstraint("package_id", "boq_line_item_id", name="uq_procurement_package_items_pair"),
    )

    package_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("procurement_packages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    boq_line_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boq_line_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )


class Rfq(TenantEntity):
    """One RFQ dispatch to one vendor for one package. `rfq_ref` is assigned
    by a BEFORE INSERT trigger (migration 0015) from a per-tenant/per-year
    counter -- never set from Python -- so it stays unique and gap-free
    even under concurrent draft creation. subject/body_html/
    attachment_object_key/attachment_sha256 are populated at dispatch time
    and are the durable record of exactly what the vendor received (see
    app/services/procurement.py::dispatch_rfq); they stay NULL for a
    not-yet-dispatched draft."""

    __tablename__ = "rfqs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "rfq_ref", name="uq_rfqs_tenant_ref"),
        UniqueConstraint("reply_token", name="uq_rfqs_reply_token"),
    )

    package_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("procurement_packages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vendors.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    vendor_contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vendor_contacts.id", ondelete="SET NULL"), nullable=True
    )

    # Server-assigned (trigger); nullable only so the ORM can insert a row
    # before the trigger fires -- always non-null once committed.
    rfq_ref: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=RfqStatus.DRAFT.value)
    due_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    # Vendor-matching override (SRS default #6): set when this vendor did not
    # pass the trade-prequalification filter and a procurement_head+ actor
    # explicitly overrode it with a reason -- both audited (AuditAction.CREATE
    # payload) at creation time in app/services/procurement.py.
    is_override: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- dispatch snapshot: exactly what the vendor received, frozen at
    # send time. Re-dispatch (resend) overwrites these with a fresh render. ---
    subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    body_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    attachment_object_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    attachment_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # --- reply correlation (for C2) ---
    message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reply_token: Mapped[str] = mapped_column(String(43), nullable=False)  # secrets.token_urlsafe(32)

    # --- dispatch bookkeeping ---
    dispatch_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    dispatch_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    celery_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    queued_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
