from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, Integer, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TenantEntity


class TenantAiSettings(TenantEntity):
    """One row per tenant. A missing row means external AI is NOT allowed."""

    __tablename__ = "tenant_ai_settings"
    __table_args__ = (UniqueConstraint("tenant_id", name="uq_tenant_ai_settings_tenant"),)

    external_ai_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # Tender intake: AI classifications at or above this confidence are accepted and routed without a person.
    intake_auto_accept_min: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False, server_default="0.850")
    # Disciplines whose drawings are measured automatically when intake routes them (default: none).
    intake_auto_measure: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    # Per-file AI classification at upload. Off by default: upload is a fast, AI-free index and the BOQ agent reads on demand.
    intake_ai_classify: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")


class AiCall(TenantEntity):
    """Append-only audit of every AI gateway call (including blocked and
    cached ones). prompt/response are internal traceability only and are
    never returned by list endpoints."""

    __tablename__ = "ai_calls"

    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    task: Mapped[str] = mapped_column(String(48), nullable=False)
    provider: Mapped[str] = mapped_column(String(24), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False, server_default="1")
    entity_type: Mapped[str | None] = mapped_column(String(48), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    response: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    tokens_cached: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, server_default="0")
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    external: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")


class AiCacheEntry(TenantEntity):
    __tablename__ = "ai_cache"
    __table_args__ = (
        UniqueConstraint("tenant_id", "task", "input_sha256", "model", "prompt_version", name="uq_ai_cache_key"),
    )

    task: Mapped[str] = mapped_column(String(48), nullable=False)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    response: Mapped[Any] = mapped_column(JSONB, nullable=False)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
