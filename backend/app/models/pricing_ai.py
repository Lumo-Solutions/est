from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TenantEntity


def _project_fk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)


class SettlementAiRun(TenantEntity):
    __tablename__ = "settlement_ai_runs"

    project_id: Mapped[uuid.UUID] = _project_fk()
    settlement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bid_settlements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, server_default="queued")
    use_ai: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    progress_done: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    progress_total: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    params: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    counts: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    result: Mapped[Any | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    warnings: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_calls: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    ai_cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, server_default="0")
    started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)


class SettlementAiProposal(TenantEntity):
    __tablename__ = "settlement_ai_proposals"

    project_id: Mapped[uuid.UUID] = _project_fk()
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("settlement_ai_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    settlement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bid_settlements.id", ondelete="CASCADE"), nullable=False
    )
    settlement_line_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bid_settlement_line_items.id", ondelete="CASCADE"), nullable=False
    )
    boq_line_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boq_line_items.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(12), nullable=False, server_default="proposed")
    source: Mapped[str] = mapped_column(String(6), nullable=False, server_default="none")
    chosen: Mapped[Any | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    candidates: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    flags: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False, server_default="0")
    decided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    applied: Mapped[Any | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
