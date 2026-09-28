"""Phase 3 gap-fill (docs/ui-qa-brief.md): GET /cost-items --
app/services/costlib.py::list_cost_items. Only get-by-id existed before; a
cost library browsing screen needs to list/search items, mirroring
app/services/vendors.py::list_vendors's pagination shape."""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.services import costlib as costlib_service

pytestmark = pytest.mark.asyncio

TENANT = "8f14e45f-ceea-4e97-8d0c-3d3b3f3c1a00"


@pytest_asyncio.fixture(autouse=True)
async def _set_guc(rls_session) -> None:
    await rls_session.execute(
        text(
            "SELECT set_config('app.tenant_id', :t, false), set_config('app.user_id', :u, false), "
            "set_config('app.roles', 'lead_estimator', false), set_config('app.is_system', 'off', false)"
        ),
        {"t": TENANT, "u": str(uuid.uuid4())},
    )


async def _create_item(session, code: str, description: str, *, is_active: bool = True) -> str:
    result = await session.execute(
        text(
            "INSERT INTO cost_items (tenant_id, code, description, uom, item_type, is_active) "
            "VALUES (:t, :c, :d, 'm3', 'material', :a) RETURNING id"
        ),
        {"t": TENANT, "c": code, "d": description, "a": is_active},
    )
    return str(result.scalar_one())


async def test_lists_items_ordered_by_code_with_total_count(rls_session):
    await _create_item(rls_session, "COST-B", "Ready-mix concrete")
    await _create_item(rls_session, "COST-A", "Rebar")

    rows, total = await costlib_service.list_cost_items(rls_session)

    assert total >= 2
    codes = [r.code for r in rows]
    assert codes.index("COST-A") < codes.index("COST-B")  # ordered by code


async def test_search_matches_code_or_description_case_insensitively(rls_session):
    await _create_item(rls_session, "SEARCH-1", "Ready-mix concrete C30")
    await _create_item(rls_session, "SEARCH-2", "Aluminium formwork")

    rows, total = await costlib_service.list_cost_items(rls_session, search="concrete")

    assert total == 1
    assert rows[0].code == "SEARCH-1"

    rows, total = await costlib_service.list_cost_items(rls_session, search="search-2")
    assert total == 1
    assert rows[0].code == "SEARCH-2"


async def test_is_active_filter(rls_session):
    await _create_item(rls_session, "ACTIVE-1", "Active item", is_active=True)
    await _create_item(rls_session, "INACTIVE-1", "Inactive item", is_active=False)

    rows, total = await costlib_service.list_cost_items(rls_session, is_active=False)

    assert total == 1
    assert rows[0].code == "INACTIVE-1"


async def test_pagination_limit_and_offset(rls_session):
    for i in range(5):
        await _create_item(rls_session, f"PAGE-{i}", "Paged item")

    first_page, total = await costlib_service.list_cost_items(rls_session, search="Paged item", limit=2, offset=0)
    second_page, _ = await costlib_service.list_cost_items(rls_session, search="Paged item", limit=2, offset=2)

    assert total == 5
    assert len(first_page) == 2
    assert len(second_page) == 2
    assert {r.id for r in first_page}.isdisjoint({r.id for r in second_page})
