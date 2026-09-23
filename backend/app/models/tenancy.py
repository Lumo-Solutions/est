from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ARRAY, Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import ProjectStatus
from app.db.base import Base, PKMixin, TenantEntity, TimestampMixin


class Tenant(Base, PKMixin, TimestampMixin):
    __tablename__ = "tenants"

    slug: Mapped[str] = mapped_column(String(63), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="AED")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")


class User(TenantEntity):
    """Local shadow of a Keycloak user, keyed 1:1 by keycloak_sub (which is
    also this row's `id`, see security/middleware.py:_principal_user_id).
    Upserted best-effort for display; authorization always derives from the
    JWT, never from roles_cache."""

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("keycloak_sub", name="uq_users_keycloak_sub"),)

    keycloak_sub: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    last_login_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    roles_cache: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)


class Project(TenantEntity):
    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_projects_tenant_code"),)

    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    client_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=ProjectStatus.PROSPECT.value
    )
    tender_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    submission_due_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="AED")


class ProjectMember(Base):
    __tablename__ = "project_members"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    project_role: Mapped[str | None] = mapped_column(String(64), nullable=True)
