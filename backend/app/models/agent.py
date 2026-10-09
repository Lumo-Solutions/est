"""BOQ agent tables (migration 0041; docs/boq-agent/plan.md section 1)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import ARRAY, Boolean, Date, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TenantEntity


def _project_fk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)


def _json(default: str) -> Mapped:
    return mapped_column(JSONB, nullable=False, server_default=text(f"'{default}'::jsonb"))


class AgentConversation(TenantEntity):
    __tablename__ = "agent_conversations"

    project_id: Mapped[uuid.UUID] = _project_fk()
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)


class AgentRun(TenantEntity):
    __tablename__ = "agent_runs"

    project_id: Mapped[uuid.UUID] = _project_fk()
    kind: Mapped[str] = mapped_column(String(8), nullable=False, server_default="run")
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_conversations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    settlement_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bid_settlements.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="queued", index=True)
    scope: Mapped[dict] = _json("{}")
    limits: Mapped[dict] = _json("{}")
    estimate: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    plan: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(24), nullable=True)
    steps_total: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    page_views: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    ai_calls: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, server_default="0")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    started_by_roles: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)


class AgentRunSection(TenantEntity):
    __tablename__ = "agent_run_sections"
    __table_args__ = (UniqueConstraint("run_id", "section_item_id", name="uq_agent_run_sections_run_section"),)

    project_id: Mapped[uuid.UUID] = _project_fk()
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    section_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boq_line_items.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    line_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # The leaf BOQ lines this section covers (a section is a top-level BOQ group, or a chunk of ungrouped lines).
    line_ids: Mapped[list] = _json("[]")
    steps: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    plan: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    notes: Mapped[list] = _json("[]")
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    coverage: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    stop_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)


class AgentStep(TenantEntity):
    __tablename__ = "agent_steps"
    __table_args__ = (UniqueConstraint("run_id", "seq", name="uq_agent_steps_run_seq"),)

    project_id: Mapped[uuid.UUID] = _project_fk()
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    section_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_run_sections.id", ondelete="CASCADE"), nullable=True, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    tool: Mapped[str] = mapped_column(String(32), nullable=False)
    args: Mapped[dict] = _json("{}")
    note: Mapped[str | None] = mapped_column(String(400), nullable=True)
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_refs: Mapped[list] = _json("[]")
    ai_call_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, server_default="0")
    injection: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")


class AgentLineProposal(TenantEntity):
    __tablename__ = "agent_line_proposals"

    project_id: Mapped[uuid.UUID] = _project_fk()
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    boq_line_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boq_line_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    candidate_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    apply: Mapped[dict] = _json("{}")
    rate: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    uom: Mapped[str | None] = mapped_column(String(16), nullable=True)
    as_of: Mapped[date | None] = mapped_column(Date, nullable=True)
    method: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[list] = _json("[]")
    qty_check: Mapped[dict] = _json("{}")
    flags: Mapped[list] = _json("[]")
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False, server_default="0")
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="proposed")
    applied_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)


class AgentMessage(TenantEntity):
    __tablename__ = "agent_messages"

    project_id: Mapped[uuid.UUID] = _project_fk()
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(10), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True
    )
