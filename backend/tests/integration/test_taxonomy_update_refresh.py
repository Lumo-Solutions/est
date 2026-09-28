"""Phase 3 gap-fill (docs/ui-qa-brief.md): update_node AND move_node
(app/services/taxonomy.py) never refreshed updated_at after their own
session.flush(). updated_at (app/db/base.py's TenantEntity) is
server_default/onupdate=func.now() driven, so SQLAlchemy marks it expired
after an UPDATE rather than populating it from a RETURNING clause -- the
next attribute access (here, TradeNodeOut.model_validate in the route)
tries a lazy SELECT, which crashes with MissingGreenlet under the async
driver outside an awaited context. Found live, one at a time, via Phase
3's new taxonomy tree editor: a rename or active-toggle 500'd first
(update_node fixed), then moving a node 500'd the same way (move_node had
its own refresh for path/level already, added for the same underlying
reason per its own pre-existing comment, but still missed updated_at)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.core.context import RequestContext
from app.schemas.taxonomy import TradeNodeOut, TradeNodeUpdate
from app.services import taxonomy as taxonomy_service

pytestmark = pytest.mark.asyncio

TENANT = "8f14e45f-ceea-4e97-8d0c-3d3b3f3c1a00"


def _ctx() -> RequestContext:
    user_id = uuid.uuid4()
    return RequestContext(
        tenant_id=uuid.UUID(TENANT),
        user_id=user_id,
        sub=str(user_id),
        roles=frozenset({"lead_estimator"}),
    )


async def _set_guc(session) -> None:
    await session.execute(
        text(
            "SELECT set_config('app.tenant_id', :t, false), set_config('app.user_id', :u, false), "
            "set_config('app.roles', 'lead_estimator,managing_director', false), "
            "set_config('app.is_system', 'off', false)"
        ),
        {"t": TENANT, "u": str(uuid.uuid4())},
    )


async def _create_node(session, code: str) -> str:
    result = await session.execute(
        text(
            "INSERT INTO trade_nodes (tenant_id, code, name, path) VALUES (:t, :c, :c, 'placeholder') RETURNING id"
        ),
        {"t": TENANT, "c": code},
    )
    return str(result.scalar_one())


async def test_update_node_response_serializes_without_a_missing_greenlet_crash(rls_session):
    """Reproduces the exact route-level failure: TradeNodeOut.model_validate
    reading updated_at off the just-updated ORM object, not just the service
    call succeeding on its own."""
    await _set_guc(rls_session)
    node_id = await _create_node(rls_session, "REFRESH1")

    node = await taxonomy_service.update_node(
        rls_session, _ctx(), uuid.UUID(node_id), TradeNodeUpdate(name="Renamed")
    )

    out = TradeNodeOut.model_validate(node)
    assert out.name == "Renamed"
    assert out.updated_at is not None


async def test_update_node_active_toggle_also_serializes_cleanly(rls_session):
    await _set_guc(rls_session)
    node_id = await _create_node(rls_session, "REFRESH2")

    node = await taxonomy_service.update_node(
        rls_session, _ctx(), uuid.UUID(node_id), TradeNodeUpdate(is_active=False)
    )

    out = TradeNodeOut.model_validate(node)
    assert out.is_active is False


async def test_move_node_response_serializes_without_a_missing_greenlet_crash(rls_session):
    await _set_guc(rls_session)
    root_id = await _create_node(rls_session, "REFRESH3-ROOT")
    child_id = await _create_node(rls_session, "REFRESH3-CHILD")

    node = await taxonomy_service.move_node(rls_session, _ctx(), uuid.UUID(child_id), uuid.UUID(root_id))

    out = TradeNodeOut.model_validate(node)
    assert out.parent_id == uuid.UUID(root_id)
    assert out.updated_at is not None

    # And back to root (new_parent_id=None) -- the other branch move_node's
    # own logic takes, exercised separately since it's a different SQL path.
    node = await taxonomy_service.move_node(rls_session, _ctx(), uuid.UUID(child_id), None)
    out = TradeNodeOut.model_validate(node)
    assert out.parent_id is None
