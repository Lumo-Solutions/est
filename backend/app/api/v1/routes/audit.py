from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_session, require_roles
from app.core.context import RequestContext
from app.core.enums import Role
from app.models.audit import AuditEvent
from app.schemas.audit import AuditEventOut, ChainVerifyResult
from app.services import audit as audit_service
from app.services.audit import ChainVerificationError

router = APIRouter(prefix="/audit", tags=["audit"])

_READ_ROLES = (
    Role.LEAD_ESTIMATOR.value,
    Role.PROCUREMENT_HEAD.value,
    Role.BD_DIRECTOR.value,
    Role.MANAGING_DIRECTOR.value,
)


@router.get("/events", response_model=list[AuditEventOut])
async def list_events_endpoint(
    entity_type: str | None = None,
    entity_id: str | None = None,
    limit: int = Query(default=100, le=500),
    ctx: RequestContext = Depends(require_roles(*_READ_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> list[AuditEventOut]:
    stmt = select(AuditEvent).order_by(AuditEvent.occurred_at.desc()).limit(limit)
    if entity_type:
        stmt = stmt.where(AuditEvent.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(AuditEvent.entity_id == entity_id)
    rows = (await session.execute(stmt)).scalars().all()
    return [AuditEventOut.model_validate(r) for r in rows]


@router.get("/verify", response_model=ChainVerifyResult)
async def verify_chain_endpoint(
    date_from: date,
    date_to: date,
    ctx: RequestContext = Depends(require_roles(Role.MANAGING_DIRECTOR.value)),
    session: AsyncSession = Depends(get_session),
) -> ChainVerifyResult:
    try:
        await audit_service.verify_chain(session, ctx.tenant_id, date_from, date_to)
    except ChainVerificationError as exc:
        return ChainVerifyResult(
            tenant_id=ctx.tenant_id, date_from=date_from.isoformat(), date_to=date_to.isoformat(),
            ok=False, detail=str(exc),
        )
    return ChainVerifyResult(
        tenant_id=ctx.tenant_id, date_from=date_from.isoformat(), date_to=date_to.isoformat(), ok=True
    )
