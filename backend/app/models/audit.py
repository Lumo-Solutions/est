from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import ARRAY, BigInteger, Date, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import INET, JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuditChainHead(Base):
    """One row per (tenant, UTC day); the serialization point the chain
    trigger locks (SELECT ... FOR UPDATE) to assign the next seq/prev_hash.
    See migration 0003 and docs/audit-chain.md for the exact algorithm."""

    __tablename__ = "audit_chain_heads"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    chain_date: Mapped[date] = mapped_column(Date, primary_key=True)
    last_seq: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    last_hash: Mapped[str] = mapped_column(String(64), nullable=False, server_default="0" * 64)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)


class AuditEvent(Base):
    """Append-only, hash-chained. All chain fields (seq, prev_hash,
    event_hash, canonical_json, payload_sha256) are computed by the
    BEFORE INSERT trigger `audit_events_chain_trg` -- never set them from
    Python. UPDATE/DELETE are blocked by both a REVOKE and a trigger
    (raise_immutable()); there is deliberately no RLS UPDATE/DELETE policy
    either. See services/audit.py for the Python-side verifier."""

    __tablename__ = "audit_events"
    __table_args__ = (
        UniqueConstraint("tenant_id", "chain_date", "seq", name="uq_audit_events_tenant_date_seq"),
        UniqueConstraint("event_hash", name="uq_audit_events_event_hash"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    chain_date: Mapped[date] = mapped_column(Date, nullable=False)
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)

    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    actor_sub: Mapped[str | None] = mapped_column(String(255), nullable=True)
    actor_roles: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    actor_acr: Mapped[str | None] = mapped_column(String(16), nullable=True)

    action: Mapped[str] = mapped_column(String(16), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    canonical_json: Mapped[str] = mapped_column(Text, nullable=False)


class AuditCheckpoint(Base):
    __tablename__ = "audit_checkpoints"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    chain_date: Mapped[date] = mapped_column(Date, nullable=False)
    head_seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    head_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    hmac: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
