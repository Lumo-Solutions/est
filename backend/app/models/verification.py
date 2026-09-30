from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TenantEntity


def _project_fk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)


class VerificationRun(TenantEntity):
    __tablename__ = "verification_runs"

    project_id: Mapped[uuid.UUID] = _project_fk()
    status: Mapped[str] = mapped_column(String(12), nullable=False, server_default="queued")
    use_ai: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    phase: Mapped[str | None] = mapped_column(String(16), nullable=True)
    progress_done: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    progress_total: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    counts: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    summary: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    warnings: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_calls: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    ai_cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, server_default="0")
    started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)


class VerificationLine(TenantEntity):
    __tablename__ = "verification_lines"

    project_id: Mapped[uuid.UUID] = _project_fk()
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("verification_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    boq_line_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boq_line_items.id", ondelete="SET NULL"), nullable=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    item_no: Mapped[str | None] = mapped_column(String(32), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    trade_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    vclass: Mapped[str] = mapped_column(String(24), nullable=False)
    method: Mapped[str] = mapped_column(String(12), nullable=False, server_default="none")
    mapped_by: Mapped[str] = mapped_column(String(8), nullable=False, server_default="none")
    boq_quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    boq_uom: Mapped[str | None] = mapped_column(String(16), nullable=True)
    drawing_quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    delta: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    delta_pct: Mapped[Decimal | None] = mapped_column(Numeric(9, 3), nullable=True)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False, server_default="0")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    flags: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    interpretation: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    evidence: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    candidates: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")


class VerificationMapping(TenantEntity):
    __tablename__ = "verification_mappings"
    __table_args__ = (UniqueConstraint("boq_line_item_id", "evidence_ref", name="uq_verification_mappings_line_evidence"),)

    project_id: Mapped[uuid.UUID] = _project_fk()
    boq_line_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boq_line_items.id", ondelete="CASCADE"), nullable=False
    )
    evidence_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    decision: Mapped[str] = mapped_column(String(8), nullable=False)  # include | exclude
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
