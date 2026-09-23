from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TenantEntity
from app.db.types import Ltree


class TradeNode(TenantEntity):
    __tablename__ = "trade_nodes"
    __table_args__ = (
        UniqueConstraint("tenant_id", "parent_id", "code", name="uq_trade_nodes_tenant_parent_code"),
    )

    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trade_nodes.id", ondelete="RESTRICT"), nullable=True
    )
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    path: Mapped[str] = mapped_column(Ltree, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    attributes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
