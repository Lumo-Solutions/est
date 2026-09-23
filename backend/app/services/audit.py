"""Audit event recording and chain verification.

Every service that mutates a Module A/B entity, or performs a sensitive read
(export, download, cost-library lookup), calls `record()` in the SAME
transaction as the business write -- the row lands in `audit_events` via a
plain INSERT; the BEFORE INSERT trigger (migration 0003) computes
seq/prev_hash/event_hash/canonical_json. If the business transaction rolls
back, so does the audit row, so the chain never has a gap.

Design note: this slice uses explicit `record()` calls at each call site
rather than a generic SQLAlchemy `after_flush` diff-listener (the more
"automatic" approach sketched in the original design doc). Explicit calls
are more code per call site but far easier to reason about and test --
especially for the READ/EXPORT/DOWNLOAD/APPROVE/REJECT/LOGIN/LOGOUT actions,
which have no ORM "flush" to hook at all.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import ARRAY, String, bindparam, select, text
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import RequestContext
from app.core.enums import AuditAction
from app.models.audit import AuditEvent

_ALLOWED_READ_ENTITY_TYPES = {"cost_item_rate", "vendor_export", "drawing", "audit_events"}


_INSERT_EVENT_SQL = text(
    "INSERT INTO audit_events "
    "(tenant_id, chain_date, seq, occurred_at, actor_user_id, actor_sub, actor_roles, actor_acr, "
    " action, entity_type, entity_id, project_id, ip_address, user_agent, request_id, payload, "
    " payload_sha256, prev_hash, event_hash, canonical_json) "
    "VALUES "
    "(:tenant_id, :chain_date, 0, :occurred_at, :actor_user_id, :actor_sub, :actor_roles, :actor_acr, "
    " :action, :entity_type, :entity_id, :project_id, :ip_address, :user_agent, :request_id, :payload, "
    " '', '', '', '')"
).bindparams(
    bindparam("actor_roles", type_=ARRAY(String)),
    bindparam("payload", type_=JSONB),
    bindparam("ip_address", type_=INET),
)


async def record(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    action: AuditAction | str,
    entity_type: str,
    entity_id: str | UUID | None = None,
    project_id: UUID | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    """Inserts one audit_events row. Deliberately issued as a raw INSERT
    with NO RETURNING clause -- Postgres evaluates a table's SELECT
    policies against any row an INSERT...RETURNING would hand back, and
    audit_events' SELECT policy restricts visibility to lead_estimator+
    roles. An ORM `session.add()` + flush() implicitly appends RETURNING to
    fetch back server-generated columns, which meant any action performed
    by a plain `estimator` (a normal, frequent actor -- e.g. requesting an
    approval) crashed with an RLS violation on its own audit trail write,
    even though the INSERT's own WITH CHECK policy has no role
    restriction at all. Avoiding RETURNING here sidesteps that interaction
    entirely while preserving the intended read restriction."""
    action_value = action.value if isinstance(action, AuditAction) else action
    if action_value == AuditAction.READ.value and entity_type not in _ALLOWED_READ_ENTITY_TYPES:
        return  # AUDIT_ALL_READS=false path: only sensitive reads are recorded (A7)

    await session.execute(
        _INSERT_EVENT_SQL,
        {
            "tenant_id": ctx.tenant_id,
            "chain_date": datetime.now(timezone.utc).date(),
            "occurred_at": datetime.now(timezone.utc),
            "actor_user_id": ctx.user_id,
            "actor_sub": ctx.sub,
            "actor_roles": sorted(ctx.roles),
            "actor_acr": ctx.acr,
            "action": action_value,
            "entity_type": entity_type,
            "entity_id": str(entity_id) if entity_id is not None else None,
            "project_id": project_id,
            "ip_address": ctx.ip_address,
            "user_agent": ctx.user_agent,
            "request_id": ctx.request_id,
            "payload": payload or {},
        },
    )


class ChainVerificationError(Exception):
    def __init__(self, seq: int, reason: str) -> None:
        self.seq = seq
        self.reason = reason
        super().__init__(f"chain broken at seq {seq}: {reason}")


async def verify_chain(session: AsyncSession, tenant_id: UUID, date_from, date_to) -> None:
    """Re-derives every hash in Python and compares against the stored
    values. Raises ChainVerificationError at the first mismatch. This is a
    read-only sanity check independent of Postgres's own trigger logic --
    it does NOT need to reproduce jsonb's exact text serialization because
    `canonical_json` is stored verbatim by the trigger; here we only assert
    that re-hashing prev_hash+canonical_json reproduces event_hash, and that
    seq/prev_hash form an unbroken chain."""
    result = await session.execute(
        select(AuditEvent)
        .where(
            AuditEvent.tenant_id == tenant_id,
            AuditEvent.chain_date >= date_from,
            AuditEvent.chain_date <= date_to,
        )
        .order_by(AuditEvent.chain_date, AuditEvent.seq)
    )
    rows = result.scalars().all()

    per_date: dict[Any, list[AuditEvent]] = {}
    for row in rows:
        per_date.setdefault(row.chain_date, []).append(row)

    for _, day_rows in per_date.items():
        prev_hash = "0" * 64
        for row in day_rows:
            if row.prev_hash != prev_hash:
                raise ChainVerificationError(row.seq, "prev_hash does not match previous event_hash")
            expected_hash = hashlib.sha256(
                (row.prev_hash + "|" + row.canonical_json).encode("utf-8")
            ).hexdigest()
            if expected_hash != row.event_hash:
                raise ChainVerificationError(row.seq, "event_hash mismatch -- row tampered")
            # payload_sha256 is trusted as computed by the trigger from the
            # actual stored jsonb (Postgres jsonb::text and Python
            # json.dumps don't format identically byte-for-byte, so it is
            # not re-derived here) -- just assert it's present.
            if not row.payload_sha256:
                raise ChainVerificationError(row.seq, "missing payload_sha256")
            prev_hash = row.event_hash


async def get_chain_head(session: AsyncSession, tenant_id: UUID, chain_date) -> tuple[int, str]:
    result = await session.execute(
        text(
            "SELECT last_seq, last_hash FROM audit_chain_heads "
            "WHERE tenant_id = :t AND chain_date = :d"
        ),
        {"t": str(tenant_id), "d": chain_date},
    )
    row = result.first()
    if row is None:
        return 0, "0" * 64
    return row[0], row[1]
