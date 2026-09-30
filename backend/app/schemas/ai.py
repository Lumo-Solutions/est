from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.schemas.common import JsonDecimal, ORMModel


class AiStatusOut(BaseModel):
    """What the UI needs to decide between 'use AI', 'AI not configured' and
    'AI not allowed'. Never contains the key or base URL."""

    provider: str
    external: bool
    configured: bool
    external_ai_allowed: bool
    available: bool
    message: str | None = None
    budget_exceeded: bool = False


class AiSettingsIn(BaseModel):
    external_ai_allowed: bool


class AiSettingsOut(BaseModel):
    external_ai_allowed: bool
    provider: str
    external: bool
    configured: bool


class ProjectAiOverrideIn(BaseModel):
    # false = never send this project to an external provider; null = inherit.
    external_ai_override: bool | None = None


class ProjectAiOverrideOut(BaseModel):
    project_id: UUID
    external_ai_override: bool | None


class AiCallOut(ORMModel):
    """List row. Deliberately has no prompt/response (internal traceability)."""

    id: UUID
    created_at: datetime
    task: str
    provider: str
    model: str
    project_id: UUID | None
    entity_type: str | None
    entity_id: str | None
    status: str
    tokens_in: int
    tokens_out: int
    cost_usd: JsonDecimal
    latency_ms: int
    error: str | None
    created_by: UUID | None


class AiUsageRow(BaseModel):
    task: str
    provider: str
    model: str
    calls: int
    cached: int
    errors: int
    blocked: int
    tokens_in: int
    tokens_out: int
    cost_usd: float


class AiUsageOut(BaseModel):
    month_to_date_usd: float
    monthly_budget_usd: float | None
    project_budget_usd: float | None
    rows: list[AiUsageRow]
    recent: list[AiCallOut]
