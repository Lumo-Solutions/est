from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.schemas.common import JsonDecimal, ORMModel


class VerificationRunCreate(BaseModel):
    use_ai: bool = True


class VerificationRunOut(ORMModel):
    id: UUID
    project_id: UUID
    status: str  # queued | running | ready | failed
    use_ai: bool
    phase: str | None
    progress_done: int
    progress_total: int
    counts: dict
    summary: dict
    warnings: list[str]
    error: str | None
    ai_calls: int
    ai_cost_usd: JsonDecimal
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class EvidenceOut(BaseModel):
    ref: str
    kind: str
    value: float
    unit: str | None
    label: str
    drawing_id: str | None = None
    sheet_id: str | None = None
    page: int | None = None
    bbox: list[float] | None = None
    layer: str | None = None
    confidence: float = 1.0
    material: str | None = None


class CandidateOut(BaseModel):
    ref: str
    score: float
    reason: str = ""
    source: str = "rules"
    selected: bool = False


class VerificationLineOut(ORMModel):
    id: UUID
    run_id: UUID
    boq_line_item_id: UUID | None
    item_no: str | None
    description: str | None
    trade_name: str | None
    vclass: str
    method: str
    mapped_by: str
    boq_quantity: JsonDecimal | None
    boq_uom: str | None
    drawing_quantity: JsonDecimal | None
    delta: JsonDecimal | None
    delta_pct: JsonDecimal | None
    confidence: JsonDecimal
    note: str | None
    flags: list[str]
    interpretation: dict | None
    evidence: list[EvidenceOut]
    candidates: list[CandidateOut]


class VerificationLinePage(BaseModel):
    items: list[VerificationLineOut]
    total: int
    limit: int
    offset: int


class MappingIn(BaseModel):
    action: str  # accept | reject | include | clear
    evidence_ref: str
    note: str | None = None


class MappingOut(BaseModel):
    line: VerificationLineOut
    run: VerificationRunOut


class EvidenceSearchOut(BaseModel):
    items: list[EvidenceOut]
