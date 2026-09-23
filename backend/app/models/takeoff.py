from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import (
    DrawingKind,
    DrawingStatus,
    ExtractionJobStatus,
    ExtractionJobType,
    ScaleSource,
)
from app.db.base import TenantEntity
from app.db.types import EmbeddingVector


class Drawing(TenantEntity):
    __tablename__ = "drawings"
    __table_args__ = (
        UniqueConstraint("tenant_id", "project_id", "sha256", name="uq_drawings_tenant_project_sha256"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, server_default=DrawingKind.UNKNOWN.value)
    bucket: Mapped[str] = mapped_column(String(128), nullable=False)
    object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    sheet_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=DrawingStatus.UPLOADED.value)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    discipline_hint: Mapped[str | None] = mapped_column(String(32), nullable=True)
    revision_label: Mapped[str | None] = mapped_column(String(32), nullable=True)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class DrawingSheet(TenantEntity):
    __tablename__ = "drawing_sheets"
    __table_args__ = (UniqueConstraint("drawing_id", "sheet_index", name="uq_drawing_sheets_drawing_index"),)

    drawing_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("drawings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    sheet_index: Mapped[int] = mapped_column(Integer, nullable=False)
    source_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    width_pt: Mapped[float | None] = mapped_column(Numeric(12, 3), nullable=True)
    height_pt: Mapped[float | None] = mapped_column(Numeric(12, 3), nullable=True)
    units: Mapped[str | None] = mapped_column(String(16), nullable=True)
    is_raster: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    text_char_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title_block: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    drawing_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sheet_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    revision: Mapped[str | None] = mapped_column(String(16), nullable=True)
    issue_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    discipline: Mapped[str | None] = mapped_column(String(32), nullable=True)
    scale_text: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scale_ratio: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)
    scale_source: Mapped[str | None] = mapped_column(String(24), nullable=True, server_default=ScaleSource.UNKNOWN.value)
    scale_confidence: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)
    extraction_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    vlm_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    vlm_raw: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class DrawingEntity(TenantEntity):
    """Text/annotation entities harvested in slice 1. Geometric (non-text)
    entities are gated behind TAKEOFF_PERSIST_GEOMETRY (default off) -- see
    app/takeoff/geometry/ for the extension point this table feeds."""

    __tablename__ = "drawing_entities"

    sheet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("drawing_sheets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(8), nullable=False)  # dxf | pdf
    entity_type: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    layer: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    block_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    text_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    bbox_min_x: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    bbox_min_y: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    bbox_max_x: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    bbox_max_y: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    geometry: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    attributes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    handle: Mapped[str | None] = mapped_column(String(32), nullable=True)


class SheetChunk(TenantEntity):
    """RAG store: sheet_id/drawing_id/project_id + embedding, HNSW-indexed
    (migration 0009). Feeds the Module B "later" BOQ reconciliation work,
    which is out of scope for this slice -- only the ingestion side and a
    thin similarity-probe endpoint (POST /projects/{id}/sheets:search) exist
    today."""

    __tablename__ = "sheet_chunks"

    sheet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("drawing_sheets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    drawing_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_type: Mapped[str] = mapped_column(String(24), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding = mapped_column(EmbeddingVector(), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(128), nullable=False)
    embedding_version: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="1")
    source_ref: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class ExtractionJob(TenantEntity):
    __tablename__ = "extraction_jobs"

    drawing_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("drawings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sheet_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("drawing_sheets.id", ondelete="CASCADE"), nullable=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_type: Mapped[str] = mapped_column(String(24), nullable=False)
    celery_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=ExtractionJobStatus.PENDING.value)
    attempt: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="1")
    started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    metrics: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
