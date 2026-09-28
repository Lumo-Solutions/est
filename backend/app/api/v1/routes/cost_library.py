from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_session, require_roles
from app.core.context import RequestContext
from app.core.enums import Role
from app.core.errors import NotFoundError
from app.schemas.common import Page
from app.schemas.costlib import (
    CostItemCreate,
    CostItemOut,
    CostItemRateOut,
    CostRateComponentOut,
    RecordRateRequest,
)
from app.services import costlib as costlib_service

router = APIRouter(prefix="/cost-items", tags=["cost-library"])

_WRITE_ROLES = (Role.LEAD_ESTIMATOR.value, Role.PROCUREMENT_HEAD.value, Role.MANAGING_DIRECTOR.value)


@router.get("", response_model=Page)
async def list_cost_items_endpoint(
    search: str | None = None,
    trade_node_id: UUID | None = None,
    is_active: bool | None = None,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    ctx: RequestContext = CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> Page:
    rows, total = await costlib_service.list_cost_items(
        session, search=search, trade_node_id=trade_node_id, is_active=is_active, limit=limit, offset=offset
    )
    return Page(items=[CostItemOut.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


async def _to_rate_out(session: AsyncSession, rate) -> CostItemRateOut:
    components = await costlib_service.list_components(session, rate.id)
    out = CostItemRateOut.model_validate(rate)
    out.components = [CostRateComponentOut.model_validate(c) for c in components]
    return out


@router.post("", response_model=CostItemOut, status_code=201)
async def create_cost_item_endpoint(
    data: CostItemCreate,
    ctx: RequestContext = Depends(require_roles(*_WRITE_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> CostItemOut:
    item = await costlib_service.create_cost_item(session, ctx, data)
    return CostItemOut.model_validate(item)


@router.get("/{cost_item_id}", response_model=CostItemOut)
async def get_cost_item_endpoint(
    cost_item_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> CostItemOut:
    return CostItemOut.model_validate(await costlib_service.get_cost_item(session, cost_item_id))


@router.post("/{cost_item_id}/rates", response_model=CostItemRateOut, status_code=201)
async def record_rate_endpoint(
    cost_item_id: UUID,
    data: RecordRateRequest,
    ctx: RequestContext = Depends(require_roles(*_WRITE_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> CostItemRateOut:
    rate = await costlib_service.record_rate(session, ctx, cost_item_id, data)
    return await _to_rate_out(session, rate)


@router.get("/{cost_item_id}/rate", response_model=CostItemRateOut)
async def get_rate_as_of_endpoint(
    cost_item_id: UUID,
    valid_on: date = Query(default_factory=date.today),
    as_known_at: datetime | None = None,
    scope_key: str = "GLOBAL",
    ctx: RequestContext = CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> CostItemRateOut:
    rate = await costlib_service.get_rate_as_of(
        session, ctx, cost_item_id, valid_on=valid_on, known_at=as_known_at, scope_key=scope_key
    )
    if rate is None:
        raise NotFoundError(f"No rate for cost item {cost_item_id} valid on {valid_on}")
    return await _to_rate_out(session, rate)
