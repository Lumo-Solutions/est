from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import JsonDecimal, ORMModel


class CostRunCreate(BaseModel):
    use_ai: bool = True


class MarkupRunCreate(BaseModel):
    use_ai: bool = True


class SettlementAiRunOut(ORMModel):
    id: UUID
    settlement_id: UUID
    project_id: UUID
    kind: str  # costs | markup
    status: str  # queued | running | ready | failed
    use_ai: bool
    progress_done: int
    progress_total: int
    counts: dict
    result: Any | None
    warnings: list[str]
    error: str | None
    ai_calls: int
    ai_cost_usd: JsonDecimal
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class CandidateOut(BaseModel):
    ref: str
    type: str  # quote | library | historical
    label: str
    rate: JsonDecimal
    currency: str
    uom: str | None
    vendor: str | None = None
    as_of: str | None = None
    samples: int = 0
    match_score: float = 0.0
    score: float = 0.0
    reason: str = ""
    selected: bool = False
    flags: list[str] = Field(default_factory=list)
    detail: dict = Field(default_factory=dict)


class ProposalOut(ORMModel):
    id: UUID
    run_id: UUID
    settlement_id: UUID
    settlement_line_id: UUID
    boq_line_item_id: UUID
    item_no: str | None = None
    description: str | None = None
    uom: str | None = None
    quantity: JsonDecimal | None = None
    status: str  # proposed | accepted | overridden | rejected
    source: str  # ai | rules | none
    chosen: CandidateOut | None
    candidates: list[CandidateOut]
    rationale: str | None
    flags: list[str]
    blocked: bool = False
    bulk_acceptable: bool = False
    no_source: bool = False
    confidence: JsonDecimal
    decided_by: UUID | None
    decided_at: datetime | None
    decision_note: str | None
    created_at: datetime


class ProposalPage(BaseModel):
    items: list[ProposalOut]
    total: int
    limit: int
    offset: int


class DecisionIn(BaseModel):
    action: str  # accept | choose | manual | reject
    candidate_ref: str | None = None
    manual_unit_cost: Decimal | None = None
    manual_currency: str | None = None
    note: str | None = None


class BulkAcceptIn(BaseModel):
    min_confidence: float = Field(default=0.85, ge=0.5, le=1.0)


class BulkAcceptOut(BaseModel):
    accepted: int
    skipped: int
