from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import INET, JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import ApprovalEntityType, ApprovalRequestStatus, ApprovalStepStatus
from app.db.base import TenantEntity


class ApprovalPolicy(TenantEntity):
    __tablename__ = "approval_policies"
    __table_args__ = (
        UniqueConstraint("tenant_id", "entity_type", "version", name="uq_approval_policies_tenant_type_version"),
    )

    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    mode: Mapped[str] = mapped_column(String(32), nullable=False, server_default="sequential_up_to_tier")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")


class ApprovalPolicyTier(TenantEntity):
    __tablename__ = "approval_policy_tiers"

    policy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("approval_policies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    min_amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, server_default="0")
    max_amount: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    required_role: Mapped[str] = mapped_column(String(32), nullable=False)
    quorum: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="1")
    sla_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    requires_mfa: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")


class ApprovalRequest(TenantEntity):
    __tablename__ = "approval_requests"

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="AED")
    policy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("approval_policies.id", ondelete="RESTRICT"), nullable=False
    )
    policy_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=ApprovalRequestStatus.PENDING.value
    )
    current_seq: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="1")
    payload_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    requested_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)


class ApprovalStep(TenantEntity):
    __tablename__ = "approval_steps"
    __table_args__ = (UniqueConstraint("request_id", "seq", name="uq_approval_steps_request_seq"),)

    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("approval_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    seq: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    required_role: Mapped[str] = mapped_column(String(32), nullable=False)
    assignee_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=ApprovalStepStatus.PENDING.value
    )
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    decided_ip: Mapped[str | None] = mapped_column(INET, nullable=True)
    decided_acr: Mapped[str | None] = mapped_column(String(16), nullable=True)
