from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.asyncio

TENANT = "8f14e45f-ceea-4e97-8d0c-3d3b3f3c1a00"


async def _set_guc(session) -> None:
    await session.execute(
        text(
            "SELECT set_config('app.tenant_id', :t, false), set_config('app.user_id', :u, false), "
            "set_config('app.roles', 'lead_estimator,managing_director', false), "
            "set_config('app.is_system', 'off', false)"
        ),
        {"t": TENANT, "u": str(uuid.uuid4())},
    )


async def _create_node(session, code: str, parent_id: str | None = None) -> str:
    result = await session.execute(
        text(
            "INSERT INTO trade_nodes (tenant_id, parent_id, code, name, path) "
            "VALUES (:t, :p, :c, :c, 'placeholder') RETURNING id"
        ),
        {"t": TENANT, "p": parent_id, "c": code},
    )
    return str(result.scalar_one())


async def test_root_node_path_is_single_label(rls_session):
    await _set_guc(rls_session)
    node_id = await _create_node(rls_session, "ROOT1")
    result = await rls_session.execute(
        text("SELECT path::text, level FROM trade_nodes WHERE id = :id"), {"id": node_id}
    )
    path, level = result.one()
    assert level == 0
    assert path.count(".") == 0


async def test_child_path_is_prefixed_by_parent(rls_session):
    await _set_guc(rls_session)
    root_id = await _create_node(rls_session, "ROOT2")
    child_id = await _create_node(rls_session, "CHILD2", parent_id=root_id)

    root_path = (
        await rls_session.execute(text("SELECT path::text FROM trade_nodes WHERE id = :id"), {"id": root_id})
    ).scalar_one()
    child_path = (
        await rls_session.execute(text("SELECT path::text FROM trade_nodes WHERE id = :id"), {"id": child_id})
    ).scalar_one()
    assert child_path.startswith(root_path + ".")

    level = (
        await rls_session.execute(text("SELECT level FROM trade_nodes WHERE id = :id"), {"id": child_id})
    ).scalar_one()
    assert level == 1


async def test_moving_a_node_rewrites_descendant_paths(rls_session):
    await _set_guc(rls_session)
    root_a = await _create_node(rls_session, "ROOTA")
    root_b = await _create_node(rls_session, "ROOTB")
    child = await _create_node(rls_session, "MOVER", parent_id=root_a)
    grandchild = await _create_node(rls_session, "GRANDCHILD", parent_id=child)

    await rls_session.execute(text("UPDATE trade_nodes SET parent_id = :p WHERE id = :id"), {"p": root_b, "id": child})

    root_b_path = (
        await rls_session.execute(text("SELECT path::text FROM trade_nodes WHERE id = :id"), {"id": root_b})
    ).scalar_one()
    result = await rls_session.execute(
        text("SELECT id, path::text FROM trade_nodes WHERE id IN (:c, :g)"),
        {"c": child, "g": grandchild},
    )
    paths_by_id = {str(row[0]): row[1] for row in result.all()}
    assert paths_by_id[child].startswith(root_b_path + ".")
    assert paths_by_id[grandchild].startswith(paths_by_id[child] + ".")


async def test_subtree_query_via_ltree_ancestor_operator(rls_session):
    await _set_guc(rls_session)
    root_id = await _create_node(rls_session, "ROOTC")
    child_id = await _create_node(rls_session, "CHILDC", parent_id=root_id)
    await _create_node(rls_session, "UNRELATED")

    result = await rls_session.execute(
        text(
            "SELECT id FROM trade_nodes WHERE path <@ (SELECT path FROM trade_nodes WHERE id = :root)"
        ),
        {"root": root_id},
    )
    ids = {str(r[0]) for r in result.all()}
    assert ids == {root_id, child_id}


async def test_reparenting_under_own_subtree_is_rejected(rls_session):
    await _set_guc(rls_session)
    root_id = await _create_node(rls_session, "ROOTD")
    child_id = await _create_node(rls_session, "CHILDD", parent_id=root_id)

    # pytest.raises must be the OUTER context manager -- see the comment on
    # test_update_is_rejected in test_audit_chain_db.py for why.
    with pytest.raises(Exception, match=r"(?i)own subtree|cycle"):
        async with rls_session.begin_nested():
            await rls_session.execute(
                text("UPDATE trade_nodes SET parent_id = :c WHERE id = :root"),
                {"c": child_id, "root": root_id},
            )
