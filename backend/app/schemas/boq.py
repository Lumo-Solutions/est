from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.schemas.common import ORMModel


class BoqLineItemCreate(BaseModel):
    parent_id: UUID | None = None
    item_no: str
    description: str
    uom: str | None = None
    boq_quantity: float | None = None
    trade_node_id: UUID | None = None
    sort_order: int = 0


class AddMeasurementLink(BaseModel):
    measurement_id: UUID


class BoqLineItemOut(ORMModel):
    id: UUID
    project_id: UUID
    parent_id: UUID | None
    item_no: str
    description: str
    uom: str | None
    boq_quantity: float | None
    trade_node_id: UUID | None
    level: int
    path: str
    sort_order: int
    variance: float | None
    variance_pct: float | None
    discrepancy_class: str | None
    reconciliation_note: str | None
    reconciled_at: datetime | None
    created_at: datetime


class LinkedMeasurementOut(ORMModel):
    id: UUID
    drawing_id: UUID
    sheet_id: UUID
    capability: str
    kind: str
    value: float
    unit: str
    confidence: float


class BoqToleranceSet(BaseModel):
    trade_node_id: UUID | None = None  # None sets the project's own default
    tolerance_pct: float


class BoqToleranceOut(ORMModel):
    id: UUID
    project_id: UUID
    trade_node_id: UUID | None
    tolerance_pct: float
    created_at: datetime
    updated_at: datetime


class BoqImportColumnMappingIn(BaseModel):
    """Mirrors app.boq.import_parser.BoqImportColumnMapping (a plain
    dataclass, kept schema-import-free) -- converted to that dataclass at
    the API boundary."""

    item_no_column: str
    description_column: str
    uom_column: str | None = None
    quantity_column: str | None = None
    parent_column: str | None = None
    header_row: int = 1


class BoqImportRowOut(BaseModel):
    row_number: int
    item_no: str | None
    description: str | None
    uom: str | None
    boq_quantity: float | None
    parent_item_no: str | None
    errors: list[str]


class BoqImportPreviewOut(BaseModel):
    rows: list[BoqImportRowOut]
    valid_count: int
    error_count: int


class BoqImportCommitOut(BaseModel):
    created_item_ids: list[UUID]
    created_count: int
