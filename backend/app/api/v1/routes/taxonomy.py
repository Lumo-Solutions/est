from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_session, require_roles
from app.core.context import RequestContext
from app.core.enums import Role
from app.schemas.taxonomy import TradeNodeCreate, TradeNodeMove, TradeNodeOut, TradeNodeUpdate
from app.services import taxonomy as taxonomy_service

router = APIRouter(prefix="/taxonomy", tags=["taxonomy"])

_WRITE_ROLES = (Role.LEAD_ESTIMATOR.value, Role.PROCUREMENT_HEAD.value, Role.MANAGING_DIRECTOR.value)


@router.get("", response_model=list[TradeNodeOut])
async def list_nodes_endpoint(
    active_only: bool = True,
    ctx: RequestContext = CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> list[TradeNodeOut]:
    nodes = await taxonomy_service.list_nodes(session, active_only=active_only)
    return [TradeNodeOut.model_validate(n) for n in nodes]


@router.post("", response_model=TradeNodeOut, status_code=201)
async def create_node_endpoint(
    data: TradeNodeCreate,
    ctx: RequestContext = Depends(require_roles(*_WRITE_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> TradeNodeOut:
    node = await taxonomy_service.create_node(session, ctx, data)
    return TradeNodeOut.model_validate(node)


@router.get("/{node_id}", response_model=TradeNodeOut)
async def get_node_endpoint(
    node_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> TradeNodeOut:
    node = await taxonomy_service.get_node(session, node_id)
    return TradeNodeOut.model_validate(node)


@router.get("/{node_id}/subtree", response_model=list[TradeNodeOut])
async def subtree_endpoint(
    node_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> list[TradeNodeOut]:
    nodes = await taxonomy_service.subtree(session, node_id)
    return [TradeNodeOut.model_validate(n) for n in nodes]


@router.patch("/{node_id}", response_model=TradeNodeOut)
async def update_node_endpoint(
    node_id: UUID,
    data: TradeNodeUpdate,
    ctx: RequestContext = Depends(require_roles(*_WRITE_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> TradeNodeOut:
    node = await taxonomy_service.update_node(session, ctx, node_id, data)
    return TradeNodeOut.model_validate(node)


@router.post("/{node_id}/move", response_model=TradeNodeOut)
async def move_node_endpoint(
    node_id: UUID,
    data: TradeNodeMove,
    ctx: RequestContext = Depends(require_roles(*_WRITE_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> TradeNodeOut:
    node = await taxonomy_service.move_node(session, ctx, node_id, data.new_parent_id)
    return TradeNodeOut.model_validate(node)
