from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TenantEntity


class TypologyCluster(TenantEntity):
    """Module B Phase 4c: one row per detected/confirmed repeating-unit
    group (e.g. "Villa Type A, 12 repeats + 2 variants"). `status` moves
    proposed -> confirmed|rejected (never back); `master_instance_id`
    (nullable FK, set after typology_cluster_instances rows exist -- see
    migration 0024's own docstring for why it can't be NOT NULL at
    creation) names which group is the reference unit an estimator
    quantifies in detail via the existing BOQ/measurement-linking
    machinery, unchanged. See app/takeoff/typology.py for the pure
    detection algorithms and app/services/typology.py for the
    detect/confirm/rollup workflow."""

    __tablename__ = "typology_clusters"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="proposed")
    master_instance_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("typology_cluster_instances.id", ondelete="SET NULL"), nullable=True
    )
    detection_method: Mapped[str] = mapped_column(String(24), nullable=False)  # dxf_block | pdf_geometry_hash
    detection_key: Mapped[str] = mapped_column(String(128), nullable=False)
    tolerance_pct: Mapped[float] = mapped_column(Numeric(6, 3), nullable=False)
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)


class TypologyClusterInstance(TenantEntity):
    """One row per GROUP within a cluster ("type A", "type B", ...), not
    one row per raw detected repeat -- `instance_count` is how many
    repeats this group represents, `source_handles` (every repeat's own
    DrawingEntity.handle, for full traceability) is the exhaustive list,
    and sheet_id/bbox_* give ONE representative repeat's location for the
    split pane to jump to. See migration 0024's docstring."""

    __tablename__ = "typology_cluster_instances"
    __table_args__ = (
        UniqueConstraint("cluster_id", "group_label", name="uq_typology_cluster_instances_cluster_group"),
    )

    cluster_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("typology_clusters.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sheet_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("drawing_sheets.id", ondelete="SET NULL"), nullable=True
    )
    bbox_min_x: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    bbox_min_y: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    bbox_max_x: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    bbox_max_y: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    group_label: Mapped[str] = mapped_column(String(64), nullable=False)
    instance_count: Mapped[int] = mapped_column(Integer, nullable=False)
    source_handles: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")


class TypologyVariantDelta(TenantEntity):
    """An explicit, human-described (and optionally quantified) difference
    a non-master group has from the master unit, e.g. "+1 maid room" ->
    boq_line_item_id + quantity_delta against a real BOQ item when the
    delta is quantifiable that way. boq_line_item_id is SET NULL on
    delete (same "optional reference to something that might be deleted
    later" precedent as boq_line_items.import_batch_id) -- a deleted BOQ
    item doesn't take the delta record itself down with it."""

    __tablename__ = "typology_variant_deltas"

    cluster_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("typology_clusters.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    group_label: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    boq_line_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boq_line_items.id", ondelete="SET NULL"), nullable=True
    )
    quantity_delta: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(16), nullable=True)
