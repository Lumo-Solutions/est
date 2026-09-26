from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.schemas.common import ORMModel


class DrawingOut(ORMModel):
    id: UUID
    project_id: UUID
    original_filename: str
    content_type: str | None
    kind: str
    size_bytes: int
    sha256: str
    sheet_count: int | None
    status: str
    error_message: str | None
    created_at: datetime


class DrawingSheetOut(ORMModel):
    id: UUID
    drawing_id: UUID
    sheet_index: int
    source_name: str | None
    is_raster: bool
    text_char_count: int | None
    title_block: dict | None
    drawing_number: str | None
    sheet_title: str | None
    revision: str | None
    issue_date: str | None
    discipline: str | None
    scale_text: str | None
    scale_ratio: float | None
    scale_source: str | None
    scale_confidence: float | None
    scale_disagreement: bool
    extraction_status: str | None


class ManualScaleCalibration(BaseModel):
    p1: tuple[float, float]
    p2: tuple[float, float]
    known_length_m: float


class ExtractionJobOut(ORMModel):
    id: UUID
    job_type: str
    status: str
    attempt: int
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None
    error: str | None


class DrawingMeasurementOut(ORMModel):
    id: UUID
    drawing_id: UUID
    sheet_id: UUID
    capability: str
    kind: str
    value: float
    unit: str
    confidence: float
    source_entity_ids: list[str]
    extractor_metadata: dict | None
    created_at: datetime


class SheetSearchQuery(BaseModel):
    query: str
    top_k: int = 10


class SheetSearchResult(BaseModel):
    sheet_id: UUID
    drawing_id: UUID
    chunk_type: str
    content: str
    distance: float


# --------------------------------------------------------------------------
# Module B Phase 4a
# --------------------------------------------------------------------------


class PdfLayerMappingRuleIn(BaseModel):
    target_layer: str
    stroke_color: str | None = None
    min_line_width: float | None = None
    max_line_width: float | None = None
    dash_pattern: str | None = None
    ocg_name_contains: str | None = None
    priority: int = 0


class PdfLayerMappingRuleOut(ORMModel):
    id: UUID
    project_id: UUID
    target_layer: str
    stroke_color: str | None
    min_line_width: float | None
    max_line_width: float | None
    dash_pattern: str | None
    ocg_name_contains: str | None
    priority: int


class SheetScaleCalibrationOut(ORMModel):
    id: UUID
    ratio: float | None
    source: str
    confidence: float
    set_by: UUID | None
    set_at: datetime
    note: str | None
