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
from sqlalchemy.orm import Mapped, mapped_column, relationship

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
    # Module B Phase 4a: set when two signals confident enough to trust
    # (>=0.5) disagree by more than 10% -- see app/takeoff/scale.py::
    # estimate_scale. Surfaced to a reviewer, never auto-resolved.
    scale_disagreement: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")


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


class DrawingMeasurement(TenantEntity):
    """Persisted output of the geometry extractors (Phase 2:
    app/takeoff/geometry/) -- one row per Measurement each extractor's
    extract() call returns. Written by
    app.workers.tasks.takeoff.extract_geometry_measurements, which runs
    after index_sheets, gated behind TAKEOFF_PERSIST_GEOMETRY (no
    persisted drawing_entities.geometry to extract from otherwise). Never
    written to from request code -- read-only via
    GET /drawings/{id}/measurements."""

    __tablename__ = "drawing_measurements"

    drawing_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("drawings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sheet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("drawing_sheets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    capability: Mapped[str] = mapped_column(String(32), nullable=False, index=True)  # e.g. "alignment"
    kind: Mapped[str] = mapped_column(String(48), nullable=False)  # e.g. "alignment_length_m"
    value: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False)
    unit: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False)
    source_entity_ids: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    extractor_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Module B Phase 4b: resolved from source entities' layers against
    # drawing_layer_trade_mappings at creation/recompute time (first
    # matching pattern wins; no match leaves this NULL -- never guessed).
    trade_node_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trade_nodes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Denormalized union of source_entity_ids' own bboxes, computed once
    # at creation/recompute -- lets the split pane render a measurement's
    # extent without a join back through DrawingEntity for the common case.
    bbox_min_x: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    bbox_min_y: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    bbox_max_x: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    bbox_max_y: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)

    # The active override, if any (migration 0023) -- see DrawingMeasurementOverride.
    # Same 1:1-via-separate-table-with-a-looser-write-policy pattern as
    # BoqLineItem.reconciliation (app/models/boq.py).
    override: Mapped[DrawingMeasurementOverride | None] = relationship(
        "DrawingMeasurementOverride", uselist=False, lazy="joined",
        primaryjoin="and_(DrawingMeasurement.id == DrawingMeasurementOverride.measurement_id, "
        "DrawingMeasurementOverride.reverted_at.is_(None))",
        viewonly=True,
    )

    @property
    def effective_value(self) -> float:
        """The active override's value if one exists, else the
        extractor-computed value -- app/boq/reconciliation.py sums this,
        not `value` directly, so an override actually changes BOQ
        reconciliation (the one behavioural ripple this phase's plan
        calls out)."""
        return self.override.value if self.override is not None else self.value


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


class PdfLayerMappingRule(TenantEntity):
    """Module B Phase 4a: PDFs have no layers, so app.takeoff.pdf::
    index_pdf_geometry() synthesizes GeometricEntity.layer from stroke
    colour / line width / dash pattern / (best-effort) OCG name via this
    project-scoped, ordered rule set. See docs/module-b-phase4-plan.md §4a
    and app.takeoff.pdf::PdfLayerRule (the DB-free dataclass this mirrors)."""

    __tablename__ = "pdf_layer_mapping_rules"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_layer: Mapped[str] = mapped_column(String(128), nullable=False)
    stroke_color: Mapped[str | None] = mapped_column(String(16), nullable=True)
    min_line_width: Mapped[float | None] = mapped_column(Numeric(8, 3), nullable=True)
    max_line_width: Mapped[float | None] = mapped_column(Numeric(8, 3), nullable=True)
    dash_pattern: Mapped[str | None] = mapped_column(String(16), nullable=True)
    ocg_name_contains: Mapped[str | None] = mapped_column(String(128), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class SheetScaleCalibration(TenantEntity):
    """Module B Phase 4a: append-only history of every scale change on a
    sheet -- auto-detected (app.takeoff.scale::estimate_scale) or manual
    two-point (app.services.takeoff::set_manual_scale) -- so a reviewer
    can see, and a revert can restore, what auto-detection originally
    found. DrawingSheet.scale_ratio/scale_source/scale_confidence always
    mirror the latest row here; this table is the history, not a
    replacement for those current-value columns."""

    __tablename__ = "sheet_scale_calibrations"

    sheet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("drawing_sheets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    ratio: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)
    source: Mapped[str] = mapped_column(String(24), nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False)
    set_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    set_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class DrawingMeasurementOverride(TenantEntity):
    """Module B Phase 4b: one row per override *event* -- never deleted,
    only reverted (reverted_by/reverted_at set, row kept) -- so the row
    itself is the audit trail, same idea as SheetScaleCalibration above
    but with an explicit revert flag instead of always-append-a-new-row,
    since "was this ever overridden and by whom" needs a yes/no per
    measurement, not just a latest-wins history. At most one row per
    measurement has reverted_at IS NULL (migration 0023's partial unique
    index) -- setting a new override while one is active supersedes it
    (the old row's reverted_at is set in the same transaction, see
    app.services.takeoff::override_measurement), never violates that
    index. Own (estimator+) write policy, looser than drawing_measurements'
    extractor-owned one -- same split as BoqLineItemReconciliation off
    boq_line_items (app/models/boq.py)."""

    __tablename__ = "drawing_measurement_overrides"

    measurement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("drawing_measurements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    value: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False)
    unit: Mapped[str] = mapped_column(String(16), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    overridden_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    overridden_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    reverted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reverted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)


class DrawingLayerTradeMapping(TenantEntity):
    """Module B Phase 4b: project-scoped mapping from a layer-name
    substring (matched case-insensitively against GeometricEntity.layer,
    same "simple and predictable" convention as AlignmentConfig.
    layer_hints) to a trade_node_id, used to resolve
    DrawingMeasurement.trade_node_id at creation/recompute time (first
    matching pattern wins; no match leaves it NULL). Config-CRUD write
    policy (lead_estimator+, migration 0023) mirrors BoqTolerance's own,
    not drawing_measurement_overrides' operational estimator+ one."""

    __tablename__ = "drawing_layer_trade_mappings"
    __table_args__ = (
        UniqueConstraint("project_id", "layer_pattern", name="uq_drawing_layer_trade_mappings_project_pattern"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    layer_pattern: Mapped[str] = mapped_column(String(128), nullable=False)
    trade_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trade_nodes.id", ondelete="CASCADE"), nullable=False
    )
