from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.schemas.common import ORMModel


class ApprovalRequestCreate(BaseModel):
    project_id: UUID | None = None
    entity_type: str
    entity_id: UUID
    amount: float
    currency: str = "AED"
    payload_snapshot: dict | None = None


class ApprovalStepOut(ORMModel):
    id: UUID
    seq: int
    required_role: str
    status: str
    decided_by: UUID | None
    decided_at: datetime | None
    decision_note: str | None


class ApprovalRequestOut(ORMModel):
    id: UUID
    project_id: UUID | None
    entity_type: str
    entity_id: UUID
    amount: float
    currency: str
    status: str
    current_seq: int
    requested_by: UUID
    requested_at: datetime
    completed_at: datetime | None
    steps: list[ApprovalStepOut] = []


class ApprovalDecision(BaseModel):
    approve: bool
    note: str | None = None
