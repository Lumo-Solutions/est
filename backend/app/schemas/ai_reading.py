from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import JsonDecimal, ORMModel

# ------------------------------------------------------------------ PDF BOQ extraction


class BoqPdfRowIn(BaseModel):
    row_id: str | None = None
    item_no: str | None = None
    description: str = ""
    uom: str | None = None
    quantity: float | None = None
    page: int | None = None


class BoqPdfRowsIn(BaseModel):
    rows: list[BoqPdfRowIn] = Field(max_length=20_000)


class BoqPdfRowOut(BaseModel):
    row_id: str
    page: int
    item_no: str | None
    description: str
    uom: str | None
    quantity: float | None
    bbox: list[float]
    page_size: list[float]
    source: str  # table | ai | manual
    confidence: float
    edited: bool
    ai_read: bool
    errors: list[str]


class BoqPdfPageOut(BaseModel):
    page: int
    status: str  # table | ai | skipped_collection | empty | needs_ai | ai_unavailable
    note: str = ""
    rows: int = 0
    quality: float = 0.0


class BoqPdfExtractionOut(ORMModel):
    id: UUID
    project_id: UUID
    document_id: UUID | None
    source_filename: str
    status: str  # queued | running | ready | failed | committed
    use_ai: bool
    pages_total: int
    pages_done: int
    warnings: list[str]
    error: str | None
    batch_id: UUID | None
    committed_at: datetime | None
    created_at: datetime


class BoqPdfExtractionDetail(BoqPdfExtractionOut):
    pages: list[BoqPdfPageOut]
    rows: list[BoqPdfRowOut]
    valid_count: int
    error_count: int
    ai_row_count: int
    # The original workbook cannot be written back for a PDF source.
    original_workbook_export_available: bool = False


class BoqPdfCommitOut(BaseModel):
    created_count: int
    batch_id: UUID
    created_item_ids: list[UUID]


# ------------------------------------------------------------------ drawing annotations


class AnnotationReadIn(BaseModel):
    drawing_id: UUID | None = None
    force: bool = False


class AnnotationReadAccepted(BaseModel):
    queued_sheets: int


class DrawingAnnotationOut(ORMModel):
    id: UUID
    project_id: UUID
    drawing_id: UUID
    sheet_id: UUID
    page: int
    text: str
    kind: str
    value: JsonDecimal | None
    unit: str | None
    material: str | None
    bbox: list[float] | None
    source: str
    confidence: JsonDecimal | None


class AnnotationSummaryOut(BaseModel):
    sheets: int
    done: int
    queued: int
    unavailable: int
    failed: int
    skipped: int
    unread: int
    annotations: int


class AnnotationPage(BaseModel):
    items: list[DrawingAnnotationOut]
    total: int
    limit: int
    offset: int
