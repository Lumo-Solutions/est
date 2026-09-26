"""Module D2: BOQ import retains the original .xlsx workbook in S3 and
records each row's source coordinates; a .csv import never does (D3's
"write into the client's original Excel workbook" doesn't apply to CSV).
See docs/module-d2-plan.md §2."""

from __future__ import annotations

import io
import uuid

import pytest
from openpyxl import Workbook
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.boq.import_parser import BoqImportColumnMapping
from app.core.context import RequestContext
from app.db.rls import set_rls_context
from app.models.boq import BoqImportBatch, BoqLineItem
from app.services import boq_import as boq_import_service

pytestmark = pytest.mark.asyncio


def _ctx(roles: frozenset[str], *, tenant_id: uuid.UUID, is_system: bool = False) -> RequestContext:
    user_id = uuid.uuid4()
    return RequestContext(tenant_id=tenant_id, user_id=user_id, sub=str(user_id), roles=roles, is_system=is_system)


async def _seed_project(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    tenant_id = uuid.uuid4()
    await session.execute(
        text("INSERT INTO tenants (id, slug, name) VALUES (:id, :slug, :name)"),
        {"id": str(tenant_id), "slug": f"acme-{uuid.uuid4().hex[:8]}", "name": "Acme"},
    )
    sys_ctx = _ctx(frozenset(), tenant_id=tenant_id, is_system=True)
    await set_rls_context(session, sys_ctx)
    project_id = (
        await session.execute(
            text("INSERT INTO projects (tenant_id, code, name) VALUES (:t, :c, 'A') RETURNING id"),
            {"t": str(tenant_id), "c": f"D2-{uuid.uuid4().hex[:8]}"},
        )
    ).scalar_one()
    return tenant_id, project_id


def _xlsx_bytes() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(["Item No", "Description", "Unit", "Qty"])
    ws.append(["1", "Excavation", "m3", 100])
    ws.append(["2", "Backfill", "m3", 50])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _csv_bytes() -> bytes:
    return b"Item No,Description,Unit,Qty\n1,Excavation,m3,100\n2,Backfill,m3,50\n"


_MAPPING = BoqImportColumnMapping(
    item_no_column="Item No", description_column="Description", uom_column="Unit", quantity_column="Qty",
    rate_column="E", amount_column="F",
)


async def test_xlsx_import_retains_workbook_and_row_coordinates(rls_session, monkeypatch):
    tenant_id, project_id = await _seed_project(rls_session)
    lead_ctx = _ctx(frozenset({"lead_estimator"}), tenant_id=tenant_id, is_system=True)
    await set_rls_context(rls_session, lead_ctx)

    uploaded: dict[str, bytes] = {}

    async def _fake_put(object_key, data, content_type, *args, **kwargs):
        uploaded[object_key] = data
        import hashlib

        return hashlib.sha256(data).hexdigest()

    monkeypatch.setattr(boq_import_service, "put_object_streaming", _fake_put)

    data = _xlsx_bytes()
    created = await boq_import_service.commit_import(rls_session, lead_ctx, project_id, data, "tender.xlsx", _MAPPING)
    assert len(created) == 2

    batch = (
        await rls_session.execute(select(BoqImportBatch).where(BoqImportBatch.project_id == project_id))
    ).scalar_one()
    assert batch.source_filename == "tender.xlsx"
    assert batch.source_object_key is not None
    assert uploaded[batch.source_object_key] == data
    assert batch.source_sha256 is not None
    assert batch.rate_column == "E"
    assert batch.amount_column == "F"

    items = list(
        (await rls_session.execute(select(BoqLineItem).where(BoqLineItem.project_id == project_id).order_by(BoqLineItem.item_no)))
        .scalars().all()
    )
    assert [i.import_batch_id for i in items] == [batch.id, batch.id]
    # Row 1 is the header (header_row defaults to 1); data starts row 2.
    assert [i.source_row_number for i in items] == [2, 3]


async def test_csv_import_never_retains_a_workbook(rls_session, monkeypatch):
    tenant_id, project_id = await _seed_project(rls_session)
    lead_ctx = _ctx(frozenset({"lead_estimator"}), tenant_id=tenant_id, is_system=True)
    await set_rls_context(rls_session, lead_ctx)

    async def _unexpected_put(*args, **kwargs):
        raise AssertionError("put_object_streaming must never be called for a .csv import")

    monkeypatch.setattr(boq_import_service, "put_object_streaming", _unexpected_put)

    created = await boq_import_service.commit_import(rls_session, lead_ctx, project_id, _csv_bytes(), "tender.csv", _MAPPING)
    assert len(created) == 2

    batch = (
        await rls_session.execute(select(BoqImportBatch).where(BoqImportBatch.project_id == project_id))
    ).scalar_one()
    assert batch.source_object_key is None
    assert batch.source_sha256 is None
    for item in created:
        assert item.import_batch_id == batch.id
        assert item.source_row_number is not None
