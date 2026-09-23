from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class CostRateComponentIn(BaseModel):
    component_type: str
    description: str
    resource_code: str | None = None
    quantity_per_uom: float = 1
    unit_cost: float
    waste_factor: float = 0
    productivity: float | None = None
    sort_order: int = 0


class CostRateComponentOut(ORMModel):
    id: UUID
    component_type: str
    description: str
    resource_code: str | None
    quantity_per_uom: float
    unit_cost: float
    waste_factor: float
    amount: float
    sort_order: int


class CostItemCreate(BaseModel):
    code: str
    description: str
    long_description: str | None = None
    uom: str
    trade_node_id: UUID | None = None
    item_type: str = "material"
    attributes: dict | None = None


class CostItemOut(ORMModel):
    id: UUID
    code: str
    description: str
    uom: str
    trade_node_id: UUID | None
    item_type: str
    is_active: bool


class RecordRateRequest(BaseModel):
    scope_key: str = "GLOBAL"
    currency: str = Field(default="AED", max_length=3)
    valid_from: date
    valid_to: date | None = None
    source: str = "manual"
    source_ref: str | None = None
    confidence: float | None = None
    components: list[CostRateComponentIn] = Field(min_length=1)


class CostItemRateOut(ORMModel):
    id: UUID
    cost_item_id: UUID
    scope_key: str
    currency: str
    total_rate: float
    source: str
    source_ref: str | None
    confidence: float | None
    components: list[CostRateComponentOut] = []
