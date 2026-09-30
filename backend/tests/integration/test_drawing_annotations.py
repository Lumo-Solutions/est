"""Drawing annotation reading against Postgres (RLS on): the AI reads what is PRINTED on a sheet,
values are stored as read (never measured), re-reading replaces, an unavailable AI marks the sheet
instead of failing, and tenants cannot see each other's annotations."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.errors import AIDisabledForTenant
from app.ai.gateway import AIGateway
from app.ai.providers.mock import MockProvider, clear_mock_handlers, register_mock_handler
from app.ai.store import MemoryStore
from app.core.config import Settings
from app.core.context import RequestContext
from app.db.rls import set_rls_context
from app.models.takeoff import Drawing, DrawingAnnotation, DrawingSheet
from app.services import annotations as svc

pytestmark = pytest.mark.asyncio

SETTINGS = Settings(APP_DATABASE_URL="postgresql://x/y", MIGRATOR_DATABASE_URL="postgresql://x/y", S3_ENDPOINT="http://s3",
                    VLLM_API_BASE="http://vllm.internal/v1", AI_PROVIDER="mock")


def _ctx(tenant_id: uuid.UUID) -> RequestContext:
    uid = uuid.uuid4()
    return RequestContext(tenant_id=tenant_id, user_id=uid, sub=str(uid), roles=frozenset(), is_system=True)


async def _seed(session: AsyncSession, *, kind="dxf", raw_text="L=245.0m D300 uPVC 12 nos"):
    tenant_id = uuid.uuid4()
    await session.execute(text("INSERT INTO tenants (id, slug, name) VALUES (:i, :s, 'T')"), {"i": str(tenant_id), "s": f"an-{uuid.uuid4().hex[:8]}"})
    await set_rls_context(session, _ctx(tenant_id))
    project_id = (await session.execute(text("INSERT INTO projects (tenant_id, code, name) VALUES (:t, :c, 'P') RETURNING id"),
                                        {"t": str(tenant_id), "c": f"AN-{uuid.uuid4().hex[:8]}"})).scalar_one()
    drawing = Drawing(tenant_id=tenant_id, project_id=project_id, original_filename="c-101.dxf", kind=kind, bucket="b",
                      object_key="x", size_bytes=1, sha256=uuid.uuid4().hex.ljust(64, "0"), status="ready", sheet_count=1)
    session.add(drawing)
    await session.flush()
    sheet = DrawingSheet(tenant_id=tenant_id, drawing_id=drawing.id, project_id=project_id, sheet_index=0, units="mm", raw_text=raw_text)
    session.add(sheet)
    await session.flush()
    return tenant_id, project_id, drawing, sheet


def _gw(tenant_id, allowed=True, external=False):
    class P(MockProvider):
        pass

    p = P()
    p.external = external
    return AIGateway(settings=SETTINGS, store=MemoryStore(external_allowed=allowed), provider=p, ctx=_ctx(tenant_id)), p


@pytest.fixture(autouse=True)
def _clean():
    yield
    clear_mock_handlers()


READING = {
    "confidence": 0.95,
    "title_block": {"drawing_number": "C-101", "sheet_title": "Sewer plan", "revision": "B", "scale_text": "1:500"},
    "scale_notes": ["ALL DIMENSIONS IN METRES"],
    "legend": [{"symbol": "dashed blue", "label": "Proposed 300mm uPVC sewer"}],
    "schedule": [["MH-01", "12.35", "1200"], ["MH-02", "12.10", "1200"]],
    "annotations": [
        {"text": "L=245.0m", "kind": "length", "value": 245.0, "unit": "m", "material": "uPVC SN8 D300", "bbox": [0.1, 0.2, 0.3, 0.22]},
        {"text": "12 nos", "kind": "count", "value": 12, "unit": "nos"},
        {"text": "weird", "kind": "other", "value": None, "action": "delete"},
    ],
}


async def test_read_stores_annotations_notes_and_status(rls_session):
    register_mock_handler("drawing_annotations", lambda req: READING)
    tenant_id, project_id, _drawing, sheet = await _seed(rls_session)
    gw, provider = _gw(tenant_id)
    n = await svc.read_sheet_annotations(rls_session, _ctx(tenant_id), sheet.id, gateway=gw)
    assert n == 3 and provider.calls[0].images == []  # DXF: text only
    rows = (await rls_session.execute(select(DrawingAnnotation).where(DrawingAnnotation.sheet_id == sheet.id).order_by(DrawingAnnotation.text))).scalars().all()
    by_text = {r.text: r for r in rows}
    assert float(by_text["L=245.0m"].value) == 245.0 and by_text["L=245.0m"].unit == "m" and by_text["L=245.0m"].bbox == [0.1, 0.2, 0.3, 0.22]
    assert by_text["12 nos"].kind == "count" and by_text["weird"].kind == "other"  # injected `action` key was dropped
    assert all(r.source == "ai" and float(r.confidence) <= 0.85 for r in rows)
    await rls_session.refresh(sheet)
    assert sheet.annotations_status == "done" and sheet.ai_notes["legend"][0]["label"].startswith("Proposed 300mm")
    assert sheet.ai_notes["schedule"][1][0] == "MH-02"


async def test_rereading_replaces_and_summary_counts(rls_session):
    tenant_id, project_id, _d, sheet = await _seed(rls_session)
    gw, _ = _gw(tenant_id)
    register_mock_handler("drawing_annotations", lambda req: READING)
    await svc.read_sheet_annotations(rls_session, _ctx(tenant_id), sheet.id, gateway=gw)
    register_mock_handler("drawing_annotations", lambda req: {"annotations": [{"text": "L=10.0m", "kind": "length", "value": 10, "unit": "m"}]})
    await svc.read_sheet_annotations(rls_session, _ctx(tenant_id), sheet.id, gateway=gw)
    rows, total = await svc.list_annotations(rls_session, project_id)
    assert total == 1 and rows[0].text == "L=10.0m"
    s = await svc.summary(rls_session, project_id)
    assert s["sheets"] == 1 and s["done"] == 1 and s["annotations"] == 1


async def test_queue_skips_done_sheets_unless_forced(rls_session):
    register_mock_handler("drawing_annotations", lambda req: READING)
    tenant_id, project_id, drawing, sheet = await _seed(rls_session)
    ctx = _ctx(tenant_id)
    assert await svc.queue_sheets(rls_session, ctx, project_id) == [sheet.id]
    gw, _ = _gw(tenant_id)
    await svc.read_sheet_annotations(rls_session, ctx, sheet.id, gateway=gw)
    assert await svc.queue_sheets(rls_session, ctx, project_id) == []
    assert await svc.queue_sheets(rls_session, ctx, project_id, drawing_id=drawing.id, force=True) == [sheet.id]


async def test_unavailable_ai_marks_the_sheet_and_stores_nothing(rls_session):
    tenant_id, project_id, _d, sheet = await _seed(rls_session)
    gw, _ = _gw(tenant_id, allowed=False, external=True)
    n = await svc.read_sheet_annotations(rls_session, _ctx(tenant_id), sheet.id, gateway=gw)
    assert n == 0
    await rls_session.refresh(sheet)
    assert sheet.annotations_status == "unavailable" and sheet.ai_notes == {"unavailable": AIDisabledForTenant.code}
    assert (await svc.list_annotations(rls_session, project_id))[1] == 0


async def test_dxf_sheet_without_text_is_skipped_without_an_ai_call(rls_session):
    tenant_id, _p, _d, sheet = await _seed(rls_session, raw_text="  ")
    gw, provider = _gw(tenant_id)
    assert await svc.read_sheet_annotations(rls_session, _ctx(tenant_id), sheet.id, gateway=gw) == 0
    await rls_session.refresh(sheet)
    assert sheet.annotations_status == "skipped" and provider.calls == []


async def test_annotations_are_tenant_isolated_and_rls_enforced(rls_session):
    register_mock_handler("drawing_annotations", lambda req: READING)
    tenant_a, project_a, _d, sheet_a = await _seed(rls_session)
    gw, _ = _gw(tenant_a)
    await svc.read_sheet_annotations(rls_session, _ctx(tenant_a), sheet_a.id, gateway=gw)
    tenant_b, project_b, _d2, _s2 = await _seed(rls_session)
    other = RequestContext(tenant_id=tenant_b, user_id=uuid.uuid4(), sub="b", roles=frozenset({"managing_director"}))
    await set_rls_context(rls_session, other)
    assert (await rls_session.execute(text("SELECT count(*) FROM drawing_annotations"))).scalar_one() == 0
    row = (await rls_session.execute(text("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname='drawing_annotations'"))).one()
    assert tuple(row) == (True, True)


async def test_out_of_schema_kind_is_rejected_not_stored(rls_session):
    """A model that returns a kind outside the enum is an invalid answer: the sheet is marked
    unavailable and nothing is stored (parse_reading additionally neutralises unknown kinds)."""
    bad = {"annotations": [{"text": "L=1m", "kind": "delete_everything", "value": 1}]}
    register_mock_handler("drawing_annotations", lambda req: bad)
    tenant_id, project_id, _d, sheet = await _seed(rls_session)
    gw, _ = _gw(tenant_id)
    assert await svc.read_sheet_annotations(rls_session, _ctx(tenant_id), sheet.id, gateway=gw) == 0
    await rls_session.refresh(sheet)
    assert sheet.annotations_status == "unavailable"
    assert (await svc.list_annotations(rls_session, project_id))[1] == 0
