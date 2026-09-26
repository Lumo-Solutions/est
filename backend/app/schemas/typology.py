from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.schemas.common import ORMModel


class TypologyClusterOut(ORMModel):
    id: UUID
    project_id: UUID
    status: str
    master_instance_id: UUID | None
    detection_method: str
    detection_key: str
    tolerance_pct: float
    confirmed_by: UUID | None
    confirmed_at: datetime | None
    created_at: datetime


class TypologyClusterInstanceOut(ORMModel):
    id: UUID
    cluster_id: UUID
    sheet_id: UUID | None
    bbox_min_x: float | None
    bbox_min_y: float | None
    bbox_max_x: float | None
    bbox_max_y: float | None
    group_label: str
    instance_count: int
    source_handles: list[str]


class TypologyVariantDeltaOut(ORMModel):
    id: UUID
    cluster_id: UUID
    group_label: str
    description: str
    boq_line_item_id: UUID | None
    quantity_delta: float | None
    unit: str | None


class ConfirmClusterGroupIn(BaseModel):
    group_label: str
    handles: list[str]


class ConfirmClusterDeltaIn(BaseModel):
    group_label: str
    description: str
    boq_line_item_id: UUID | None = None
    quantity_delta: float | None = None
    unit: str | None = None


class ConfirmClusterRequest(BaseModel):
    groups: list[ConfirmClusterGroupIn]
    master_group_label: str
    deltas: list[ConfirmClusterDeltaIn] = []


class TypologyRollupDeltaOut(BaseModel):
    group_label: str
    quantity_delta: float
    instance_count: int
    contribution: float


class TypologyRollupItemOut(BaseModel):
    boq_line_item_id: UUID
    item_no: str
    master_quantity: float
    total_instance_count: int
    total: float
    deltas: list[TypologyRollupDeltaOut]


class TypologyRollupOut(BaseModel):
    cluster_id: UUID
    total_instance_count: int
    items: list[TypologyRollupItemOut]
    note: str | None = None
