"""PDF BOQ extraction through the HTTP API and the worker body: upload -> read -> edit ->
validate -> commit; provenance (page, region, ai_read) lands on the BOQ lines; roles;
AI pages are flagged; the original-workbook export is honestly unavailable."""

from __future__ import annotations

import hashlib
import io
import uuid

import pytest
from sqlalchemy import text

from app.ai.gateway import AIGateway
from app.ai.providers.mock import MockProvider, clear_mock_handlers, register_mock_handler
from app.ai.store import MemoryStore
from app.core.config import Settings
from app.core.context import RequestContext
from app.core.enums import Role
from app.demo.boq_pdf import BoqItem, build_boq_pdf, build_scanned_pdf, sample_items

pytestmark = pytest.mark.asyncio

TENANT = uuid.UUID("8f14e45f-ceea-4e97-8d0c-3d3b3f3c1a00")


@pytest.fixture(autouse=True)
def _fakes(monkeypatch):
    from app.services import boq_pdf as svc
    from app.workers.tasks import ai_reading as worker

    store: dict[str, bytes] = {}

    async def put(object_key, data, content_type, *args, bucket=None, **kwargs):
        store[object_key] = data
        return hashlib.sha256(data).hexdigest()

    async def get(object_key, *args, **kwargs):
        return store[object_key]

    monkeypatch.setattr(svc, "put_object_streaming", put)
    monkeypatch.setattr(svc, "get_object_bytes", get)
    dispatched: list = []
    monkeypatch.setattr(worker.extract_boq_pdf, "apply_async", lambda args=None, countdown=0, **kw: dispatched.append(args))
    yield {"store": store, "dispatched": dispatched}
    clear_mock_handlers()


def _mock_gateway_factory(monkeypatch) -> MockProvider:
    mock = MockProvider()
    s = Settings(APP_DATABASE_URL="postgresql://x/y", MIGRATOR_DATABASE_URL="postgresql://x/y", S3_ENDPOINT="http://s3",
                 VLLM_API_BASE="http://vllm.internal/v1", AI_PROVIDER="mock")
    ctx = RequestContext(tenant_id=TENANT, user_id=uuid.uuid4(), sub="w", roles=frozenset({"lead_estimator"}))
    monkeypatch.setattr("app.boq.pdf_ai.default_gateway", lambda settings=None: AIGateway(settings=s, store=MemoryStore(), provider=mock, ctx=ctx))
    return mock


async def _run_worker(extraction_id: str, lead, roles=("lead_estimator",)) -> None:
    """Runs the Celery task body as the uploader (same identity the route dispatches with)."""
    import app.db.session as dbs
    from app.workers.base import build_worker_context
    from app.workers.tasks.ai_reading import _extract

    dbs.get_worker_engine.cache_clear()
    sub = (await lead.get("/api/v1/auth/me")).json()["sub"]
    ctx = build_worker_context(str(TENANT), sub, list(roles))
    await _extract(ctx, extraction_id)


async def _project(authed_client) -> str:
    md = authed_client(frozenset({Role.MANAGING_DIRECTOR.value}))
    return (await md.post("/api/v1/projects", json={"code": f"PDF-{uuid.uuid4().hex[:6]}", "name": "PDF BOQ"})).json()["id"]


async def _lead(authed_client, app_engine, pid: str):
    """A lead_estimator who is a member of the project. Identity is fixed by the FIRST call to
    authed_client, so use the returned client without calling authed_client again."""
    from sqlalchemy.ext.asyncio import AsyncSession

    lead = authed_client(frozenset({Role.LEAD_ESTIMATOR.value}))
    sub = (await lead.get("/api/v1/auth/me")).json()["sub"]
    async with AsyncSession(app_engine) as session, session.begin():
        await session.execute(text("SELECT set_config('app.tenant_id', :t, false), set_config('app.is_system', 'on', false)"), {"t": str(TENANT)})
        await session.execute(text("INSERT INTO project_members (project_id, user_id, tenant_id) VALUES (:p, :u, :t)"),
                              {"p": pid, "u": sub, "t": str(TENANT)})
    return lead


def _upload(client, pid, data, name="boq.pdf", **form):
    return client.post(f"/api/v1/projects/{pid}/boq-pdf-extractions", files={"file": (name, io.BytesIO(data), "application/pdf")}, data=form)


async def test_clean_pdf_end_to_end_edit_validate_commit(authed_client, app_engine, _fakes):
    pid = await _project(authed_client)
    lead = await _lead(authed_client, app_engine, pid)
    resp = await _upload(lead, pid, build_boq_pdf(sample_items()))
    assert resp.status_code == 202 and resp.json()["status"] == "queued"
    eid = resp.json()["id"]
    assert _fakes["dispatched"] and _fakes["dispatched"][0][0] == eid

    await _run_worker(eid, lead)
    detail = (await lead.get(f"/api/v1/boq-pdf-extractions/{eid}")).json()
    assert detail["status"] == "ready" and detail["pages_done"] == detail["pages_total"] >= 4
    assert len(detail["rows"]) == len(sample_items()) and detail["ai_row_count"] == 0
    assert detail["error_count"] == 0 and detail["original_workbook_export_available"] is False
    assert any(p["status"] == "skipped_collection" for p in detail["pages"])
    row = next(r for r in detail["rows"] if r["item_no"] == "1.1")
    assert row["source"] == "table" and row["page"] == 1 and row["bbox"][2] > row["bbox"][0]

    # edit one row, add one, and break one -> validation reports it and commit refuses
    rows = [{k: r[k] for k in ("row_id", "item_no", "description", "uom", "quantity", "page")} for r in detail["rows"]]
    rows[1]["quantity"] = 999.0
    rows[2]["description"] = ""
    rows.append({"item_no": "3", "description": "Added by hand", "uom": None, "quantity": None})
    saved = (await lead.put(f"/api/v1/boq-pdf-extractions/{eid}/rows", json={"rows": rows})).json()
    assert saved["error_count"] == 1
    bad = next(r for r in saved["rows"] if r["errors"])
    assert "description is required" in bad["errors"]
    assert next(r for r in saved["rows"] if r["item_no"] == "3")["source"] == "manual"
    assert next(r for r in saved["rows"] if r["row_id"] == rows[1]["row_id"])["edited"] is True
    assert (await lead.post(f"/api/v1/boq-pdf-extractions/{eid}/commit")).status_code == 422

    rows[2]["description"] = "Fixed description"
    await lead.put(f"/api/v1/boq-pdf-extractions/{eid}/rows", json={"rows": rows})
    commit = await lead.post(f"/api/v1/boq-pdf-extractions/{eid}/commit")
    assert commit.status_code == 201 and commit.json()["created_count"] == len(rows)
    assert (await lead.post(f"/api/v1/boq-pdf-extractions/{eid}/commit")).status_code == 409  # only once
    assert (await lead.put(f"/api/v1/boq-pdf-extractions/{eid}/rows", json={"rows": rows})).status_code == 409

    async with __import__("app.db.session", fromlist=["x"]).session_scope(
        RequestContext(tenant_id=TENANT, user_id=uuid.uuid4(), sub="x", roles=frozenset(), is_system=True)
    ) as s:
        got = (await s.execute(text(
            "SELECT count(*), count(*) FILTER (WHERE source_kind='pdf'), count(*) FILTER (WHERE ai_read), "
            "count(*) FILTER (WHERE source_page IS NOT NULL), max(boq_quantity) FILTER (WHERE item_no='1.1') "
            "FROM boq_line_items WHERE project_id=:p"), {"p": pid})).one()
    assert got[0] == len(rows) and got[1] == len(rows) and got[2] == 0 and got[3] >= len(rows) - 1
    assert float(got[4]) == 999.0


async def test_scanned_pdf_uses_ai_and_rows_are_flagged_through_to_the_boq(authed_client, app_engine, monkeypatch):
    mock = _mock_gateway_factory(monkeypatch)
    register_mock_handler("boq_pdf_rows", lambda req: {
        "is_boq_table": True, "confidence": 0.9,
        "rows": [
            {"item_no": "1", "description": "SITE CLEARANCE"},
            {"item_no": "1.1", "description": "Clear and grub site", "unit": "m2", "quantity": 5400, "bbox": [0.1, 0.3, 0.9, 0.32]},
        ],
    })
    pid = await _project(authed_client)
    lead = await _lead(authed_client, app_engine, pid)
    eid = (await _upload(lead, pid, build_scanned_pdf(sample_items()[:3]))).json()["id"]
    await _run_worker(eid, lead)
    d = (await lead.get(f"/api/v1/boq-pdf-extractions/{eid}")).json()
    assert len(mock.calls) == 1 and d["ai_row_count"] == 2 and all(r["ai_read"] for r in d["rows"])
    assert d["pages"][0]["status"] == "ai" and "review" in d["pages"][0]["note"]
    assert (await lead.post(f"/api/v1/boq-pdf-extractions/{eid}/commit")).status_code == 201
    import app.db.session as dbs

    async with dbs.session_scope(RequestContext(tenant_id=TENANT, user_id=uuid.uuid4(), sub="x", roles=frozenset(), is_system=True)) as s:
        n = (await s.execute(text("SELECT count(*) FROM boq_line_items WHERE project_id=:p AND ai_read AND source_kind='pdf'"), {"p": pid})).scalar_one()
    assert n == 2


async def test_use_ai_false_leaves_scanned_pages_unread_with_a_warning(authed_client, app_engine, monkeypatch):
    mock = _mock_gateway_factory(monkeypatch)
    pid = await _project(authed_client)
    lead = await _lead(authed_client, app_engine, pid)
    eid = (await _upload(lead, pid, build_scanned_pdf([BoqItem("1", "x")]), use_ai="false")).json()["id"]
    await _run_worker(eid, lead)
    d = (await lead.get(f"/api/v1/boq-pdf-extractions/{eid}")).json()
    assert mock.calls == [] and d["rows"] == [] and d["warnings"] and "could not be read" in d["warnings"][0]


async def test_failed_worker_is_recorded_from_an_independent_session(authed_client, app_engine, _fakes):
    pid = await _project(authed_client)
    lead = await _lead(authed_client, app_engine, pid)
    eid = (await _upload(lead, pid, build_boq_pdf(sample_items()[:5]))).json()["id"]
    _fakes["store"].clear()  # the object vanished: the read fails inside the worker transaction
    await _run_worker(eid, lead)
    d = (await lead.get(f"/api/v1/boq-pdf-extractions/{eid}")).json()
    assert d["status"] == "failed" and d["error"]
    assert (await lead.post(f"/api/v1/boq-pdf-extractions/{eid}/commit")).status_code == 409


async def test_roles_and_input_validation(authed_client, app_engine):
    pid = await _project(authed_client)
    pdf = build_boq_pdf(sample_items()[:3])
    # denied roles first (each authed_client call switches the shared client's identity)
    assert (await _upload(authed_client(frozenset({Role.ESTIMATOR.value})), pid, pdf)).status_code == 403
    assert (await _upload(authed_client(frozenset({Role.BD_DIRECTOR.value})), pid, pdf)).status_code == 403
    # procurement_head (sees all projects) and MD are allowed as well as lead_estimator
    assert (await _upload(authed_client(frozenset({Role.PROCUREMENT_HEAD.value})), pid, pdf)).status_code == 202
    lead = await _lead(authed_client, app_engine, pid)  # lowest allowed role: lead_estimator (project member)
    assert (await _upload(lead, pid, b"not a pdf at all")).status_code == 422
    assert (await lead.post(f"/api/v1/projects/{pid}/boq-pdf-extractions")).status_code == 422  # neither file nor document_id
    eid = (await _upload(lead, pid, pdf)).json()["id"]
    assert (await lead.get(f"/api/v1/boq-pdf-extractions/{uuid.uuid4()}")).status_code == 404
    est = authed_client(frozenset({Role.ESTIMATOR.value}))
    assert (await est.put(f"/api/v1/boq-pdf-extractions/{eid}/rows", json={"rows": []})).status_code == 403
    assert (await est.post(f"/api/v1/boq-pdf-extractions/{eid}/commit")).status_code == 403
