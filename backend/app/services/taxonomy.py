from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import RequestContext
from app.core.enums import AuditAction
from app.core.errors import ConflictError, NotFoundError
from app.models.taxonomy import TradeNode
from app.schemas.taxonomy import TradeNodeCreate, TradeNodeUpdate
from app.services import audit


async def get_node(session: AsyncSession, node_id: UUID) -> TradeNode:
    result = await session.execute(select(TradeNode).where(TradeNode.id == node_id))
    node = result.scalar_one_or_none()
    if node is None:
        raise NotFoundError(f"Trade node {node_id} not found")
    return node


async def list_nodes(session: AsyncSession, *, active_only: bool = True) -> list[TradeNode]:
    stmt = select(TradeNode).order_by(TradeNode.path)
    if active_only:
        stmt = stmt.where(TradeNode.is_active.is_(True))
    return list((await session.execute(stmt)).scalars().all())


async def subtree(session: AsyncSession, node_id: UUID) -> list[TradeNode]:
    node = await get_node(session, node_id)
    result = await session.execute(
        text("SELECT id FROM trade_nodes WHERE path <@ (SELECT path FROM trade_nodes WHERE id = :id)"),
        {"id": str(node.id)},
    )
    ids = [row[0] for row in result.all()]
    rows = await session.execute(select(TradeNode).where(TradeNode.id.in_(ids)).order_by(TradeNode.path))
    return list(rows.scalars().all())


async def create_node(session: AsyncSession, ctx: RequestContext, data: TradeNodeCreate) -> TradeNode:
    node = TradeNode(
        tenant_id=ctx.tenant_id,
        parent_id=data.parent_id,
        code=data.code,
        name=data.name,
        sort_order=data.sort_order,
        attributes=data.attributes,
        path="placeholder",  # overwritten by the trade_nodes_path_trg trigger
    )
    session.add(node)
    await session.flush()
    # path/level are computed by the trade_nodes_path_trg BEFORE INSERT
    # trigger (app/migrations/versions/0004_taxonomy.py); SQLAlchemy has no
    # visibility into that server-side write (unlike a declared
    # Computed()/server_default), so the ORM object still holds our
    # placeholder value until explicitly refreshed.
    await session.refresh(node, attribute_names=["path", "level"])
    await audit.record(
        session, ctx, action=AuditAction.CREATE, entity_type="trade_node", entity_id=node.id,
        payload={"code": node.code, "name": node.name},
    )
    return node


async def update_node(session: AsyncSession, ctx: RequestContext, node_id: UUID, data: TradeNodeUpdate) -> TradeNode:
    node = await get_node(session, node_id)
    changes = data.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(node, field, value)
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.UPDATE, entity_type="trade_node", entity_id=node.id, payload=changes
    )
    return node


async def move_node(session: AsyncSession, ctx: RequestContext, node_id: UUID, new_parent_id: UUID | None) -> TradeNode:
    node = await get_node(session, node_id)
    if new_parent_id == node.id:
        raise ConflictError("A node cannot be its own parent")
    node.parent_id = new_parent_id
    await session.flush()  # trade_nodes_path_trg rewrites path + descendants; raises on cycles
    await session.refresh(node, attribute_names=["path", "level"])
    await audit.record(
        session, ctx, action=AuditAction.UPDATE, entity_type="trade_node", entity_id=node.id,
        payload={"reparented_to": str(new_parent_id) if new_parent_id else None},
    )
    return node
