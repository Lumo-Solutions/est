from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import field_validator

from app.schemas.common import ORMModel


class AuditEventOut(ORMModel):
    id: int
    occurred_at: datetime
    actor_sub: str | None
    actor_roles: list[str]
    action: str
    entity_type: str
    entity_id: str | None
    project_id: UUID | None
    ip_address: str | None
    seq: int
    event_hash: str

    @field_validator("ip_address", mode="before")
    @classmethod
    def _stringify_ip(cls, v: object) -> str | None:
        return None if v is None else str(v)


class ChainVerifyResult(ORMModel):
    tenant_id: UUID
    date_from: str
    date_to: str
    ok: bool
    detail: str | None = None
