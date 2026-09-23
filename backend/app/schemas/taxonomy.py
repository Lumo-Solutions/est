from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.schemas.common import ORMModel


class TradeNodeCreate(BaseModel):
    parent_id: UUID | None = None
    code: str
    name: str
    sort_order: int = 0
    attributes: dict | None = None


class TradeNodeUpdate(BaseModel):
    name: str | None = None
    sort_order: int | None = None
    is_active: bool | None = None
    attributes: dict | None = None


class TradeNodeMove(BaseModel):
    new_parent_id: UUID | None = None


class TradeNodeOut(ORMModel):
    id: UUID
    parent_id: UUID | None
    code: str
    name: str
    level: int
    path: str
    sort_order: int
    is_active: bool
    attributes: dict | None
    created_at: datetime
    updated_at: datetime
