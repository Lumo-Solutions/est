"""Module B/C Phase 5: continuous-learning feedback for semantic-match
suggestions -- accepted/rejected outcomes, used to re-rank future
suggestions by nearest-neighbor precedent (app.services.semantic_matching).
No model training; see docs/module-b-c-phase5-plan.md §6."""

from __future__ import annotations

import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TenantEntity
from app.db.types import DEFAULT_EMBEDDING_DIM


class SemanticMatchFeedback(TenantEntity):
    __tablename__ = "semantic_match_feedback"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    match_type: Mapped[str] = mapped_column(String(24), nullable=False, index=True)  # "boq_measurement" | "quote_boq"
    query_embedding: Mapped[list[float]] = mapped_column(Vector(DEFAULT_EMBEDDING_DIM), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)  # "accepted" | "rejected"
