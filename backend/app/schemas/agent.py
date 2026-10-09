"""API shapes for the BOQ agent (docs/boq-agent/api-contract.md)."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import JsonDecimal, ORMModel


class AgentRunCreate(BaseModel):
    sections: list[str] | None = Field(default=None, description="BOQ section ids or item numbers; default: all sections")
    line_ids: list[UUID] | None = Field(default=None, max_length=500)
    notes: dict[str, str] | None = Field(default=None, description="section id -> a note the agent is told for that section")
    limits: dict[str, float] | None = Field(default=None, description="max_steps, max_page_views, max_usd (capped by hard ceilings)")
    create_draft: bool = Field(default=False, description="start a new draft version when the current settlement is already submitted")


class AgentSectionOut(ORMModel):
    id: UUID
    section_item_id: UUID
    label: str
    seq: int
    status: str
    line_count: int
    steps: int
    plan: dict | None
    summary: str | None
    coverage: dict | None
    stop_reason: str | None
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None


class AgentRunOut(ORMModel):
    id: UUID
    project_id: UUID
    kind: str
    settlement_id: UUID | None
    status: str
    scope: dict
    limits: dict
    estimate: dict | None
    plan: dict | None
    summary: dict | None
    provider: str | None
    steps_total: int
    page_views: int
    ai_calls: int
    cost_usd: JsonDecimal
    error: str | None
    started_by: UUID | None
    confirmed_by: UUID | None
    confirmed_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class AgentRunDetail(AgentRunOut):
    sections: list[AgentSectionOut] = []


class AgentStepOut(ORMModel):
    id: UUID
    run_id: UUID
    section_id: UUID | None
    seq: int
    tool: str
    args: dict
    note: str | None
    ok: bool
    result_summary: str | None
    file_refs: list
    tokens_in: int
    tokens_out: int
    cost_usd: JsonDecimal
    injection: bool
    created_at: datetime


class AgentProposalOut(ORMModel):
    id: UUID
    run_id: UUID
    boq_line_item_id: UUID
    kind: str
    candidate_ref: str | None
    rate: JsonDecimal | None
    currency: str | None
    uom: str | None
    as_of: date | None
    method: str | None
    evidence: list
    qty_check: dict
    flags: list
    confidence: JsonDecimal
    rationale: str | None
    status: str
    applied_at: datetime | None


class AgentLineOut(BaseModel):
    line_id: UUID
    boq_line_item_id: UUID
    cost_source: str
    direct_unit_cost: JsonDecimal | None
    source_currency: str
    agent_proposal_id: UUID | None
    agent_confirmed_by: UUID | None
    agent_confirmed_at: datetime | None
    proposal: AgentProposalOut | None


class AgentLineConfirm(BaseModel):
    proposal_id: UUID = Field(description="the proposal the person looked at; refused if the line has moved on")


class BulkConfirmResult(BaseModel):
    confirmed: int
    skipped: dict[str, int]


class AgentSummaryOut(BaseModel):
    agent_lines: int
    unconfirmed: int


class ChatPost(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: UUID | None = None


class ChatMessageOut(ORMModel):
    id: UUID
    conversation_id: UUID
    role: str
    content: str
    run_id: UUID | None
    created_at: datetime


class ChatPostOut(BaseModel):
    conversation_id: UUID
    message: ChatMessageOut
    run_id: UUID


class ConversationOut(ORMModel):
    id: UUID
    title: str | None
    created_at: datetime
