"""Tender intake end to end on the synthetic pack, service level with a fake S3,
the mock model and recorded Celery dispatch: upload -> classify -> review ->
confirm/route, with audit events, duplicates, revisions, the addenda register and
settlement flags. Roles at the HTTP boundary are in tests/api/test_tender_intake_api.py."""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.context import RequestContext
from app.core.errors import ConflictError, ForbiddenError, ValidationAppError
from app.db.rls import set_rls_context
from app.intake.classifier import parse_model_output
from app.models.takeoff import Drawing
from app.models.tender_intake import Addendum, AddendumLink, DocumentClassification, ProjectDocument
from app.schemas.tender_intake import TenderClassUpdate
from app.services import tender_intake as svc
from app.services import tender_intake_processing as processing
from tests.fixtures.tender_pack import GROUND_TRUTH, build_pack

pytestmark = pytest.mark.asyncio

MEMBER = uuid.UUID("00000000-0000-0000-0000-0000000000e1")


def _ctx(roles: frozenset[str], *, tenant_id: uuid.UUID, user_id: uuid.UUID | None = MEMBER) -> RequestContext:
    user_id = user_id or uuid.uuid4()
    return RequestContext(tenant_id=tenant_id, user_id=user_id, sub=str(user_id), roles=roles, is_system=False)


@pytest.fixture
def fake_s3(monkeypatch, postgres_container):
    store: dict[tuple[str, str], bytes] = {}
    puts: list[str] = []

    async def put(object_key, data, content_type, *args, bucket=None, **kwargs):
        puts.append(object_key)
        store[(bucket or "default", object_key)] = data
        return hashlib.sha256(data).hexdigest()

    async def get(object_key, *args, bucket=None, **kwargs):
        return store[(bucket or "default", object_key)]

    async def presign(object_key, *args, **kwargs):
        return f"https://s3.test/{object_key}"

    for module in (svc, processing):
        monkeypatch.setattr(module, "put_object_streaming", put, raising=False)
    monkeypatch.setattr(processing, "get_object_bytes", get)
    monkeypatch.setattr(svc, "presign_get_url", presign)
    return {"store": store, "puts": puts}


def _install_gateway(provider):
    """Every AI call of the pipeline goes through `default_gateway`; tests swap in an in-memory gateway around a provider."""
    from app.ai.factory import set_gateway_override
    from app.ai.gateway import AIGateway
    from app.ai.store import MemoryStore
    from app.core.context import try_current_context

    fallback = RequestContext(tenant_id=uuid.uuid4(), user_id=None, sub=None, roles=frozenset(), is_system=True)
    store = MemoryStore()
    set_gateway_override(lambda s: AIGateway(settings=s, store=store, provider=provider, ctx=try_current_context() or fallback))
    return store


@pytest.fixture
def mock_model(postgres_container):
    """The deterministic mock provider behind the gateway; yields the list of AI requests it received."""
    from app.ai.factory import set_gateway_override
    from app.ai.providers.mock import MockProvider

    provider = MockProvider()
    _install_gateway(provider)
    yield provider.calls
    set_gateway_override(None)


async def drive_worker(session, monkeypatch, ctx: RequestContext, tenant_id: uuid.UUID, *, rounds: int = 400) -> dict:
    """The real worker, one file per task, on the test session: the dispatcher claims files (bounded, honouring paused
    packs) and `process_one` reads each, round after round, until nothing is left to claim (zip members and retries
    included). Every `with_worker_session` sets the RLS context of the ctx it is given, like a worker session does."""
    from app.workers.tasks import tender_intake as worker

    async def fake_with_worker_session(c, body, *args):
        await set_rls_context(session, c)
        try:
            return await body(session, *args)
        finally:
            await set_rls_context(session, ctx)

    queued: list[uuid.UUID] = []
    batch: list[uuid.UUID] = []
    stats = {"rounds": 0, "peak_in_flight": 0, "processed": 0}

    def enqueue(ids, tenant):
        queued.extend(ids)
        # Claimed (queued_at set) and not yet read: what the dispatcher keeps bounded.
        stats["peak_in_flight"] = max(stats["peak_in_flight"], len(queued) + len(batch))
        return []

    monkeypatch.setattr(worker, "with_worker_session", fake_with_worker_session)
    monkeypatch.setattr(worker, "enqueue_documents", enqueue)
    for _ in range(rounds):
        await worker.dispatch_for_tenant(tenant_id)
        batch[:] = list(queued)
        queued[:] = []
        if not batch:
            break
        stats["rounds"] += 1
        while batch:
            await worker.process_one(tenant_id, batch.pop(0))
            stats["processed"] += 1
    await set_rls_context(session, ctx)
    return stats


@pytest.fixture
def celery_calls(monkeypatch, postgres_container):
    from app.workers.tasks.dwg import convert_dwg
    from app.workers.tasks.takeoff import index_sheets
    from app.workers.tasks.tender_intake import dispatch_intake

    calls: dict[str, list] = {"ingest": [], "rerun": [], "convert": []}
    monkeypatch.setattr(convert_dwg, "apply_async", lambda args=None, countdown=0, **kw: calls["convert"].append((args, countdown)) or type("T", (), {"id": "t"})())
    monkeypatch.setattr(index_sheets, "apply_async", lambda args=None, countdown=0, **kw: calls["ingest"].append((args, countdown)) or type("T", (), {"id": "t"})())
    monkeypatch.setattr(dispatch_intake, "apply_async", lambda args=None, countdown=0, **kw: calls["rerun"].append((args, countdown)))
    return calls


async def _seed(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    tenant_id = uuid.uuid4()
    await set_rls_context(session, RequestContext(tenant_id=tenant_id, user_id=None, sub=None, roles=frozenset(), is_system=True))
    await session.execute(text("INSERT INTO tenants (id, slug, name) VALUES (:id, :s, 'T')"), {"id": str(tenant_id), "s": f"t-{uuid.uuid4().hex[:8]}"})
    project_id = (
        await session.execute(text("INSERT INTO projects (tenant_id, code, name) VALUES (:t, :c, 'P') RETURNING id"), {"t": str(tenant_id), "c": f"TI-{uuid.uuid4().hex[:6]}"})
    ).scalar_one()
    await session.execute(
        text("INSERT INTO project_members (project_id, user_id, tenant_id) VALUES (:p, :u, :t)"),
        {"p": str(project_id), "u": str(MEMBER), "t": str(tenant_id)},
    )
    return tenant_id, project_id


async def _process_all(session: AsyncSession, ctx: RequestContext) -> None:
    await set_rls_context(session, ctx)
    ids = list(
        (await session.execute(select(ProjectDocument.id).where(ProjectDocument.status == "received").order_by(ProjectDocument.created_at))).scalars()
    )
    while ids:
        ids.extend(await processing.process_document(session, ctx, ids.pop(0)))


async def _by_name(session: AsyncSession) -> dict[str, ProjectDocument]:
    rows = (await session.execute(select(ProjectDocument))).scalars().all()
    return {(d.archive_path or d.original_filename): d for d in rows}


@pytest.fixture
async def ingested(rls_session, fake_s3, mock_model, celery_calls):
    tenant_id, project_id = await _seed(rls_session)
    est = _ctx(frozenset({"estimator"}), tenant_id=tenant_id)
    await set_rls_context(rls_session, est)
    package, ids = await svc.create_package(
        rls_session, est, project_id, [(f.name, f.data) for f in build_pack()], label="Transmittal 1", transmittal_ref="TX-001"
    )
    await _process_all(rls_session, est)
    await svc.refresh_package_status(rls_session, package.id)
    return {"tenant": tenant_id, "project": project_id, "package": package, "est": est, "ids": ids, "session": rls_session}


# ------------------------------------------------------------------ upload / classify
async def test_upload_stores_each_content_once_links_duplicates_and_audits(ingested, fake_s3):
    s = ingested["session"]
    docs = await _by_name(s)
    original, copy = docs["C-101 Rev A.dxf"], docs["C-101 Rev A (copy).dxf"]
    assert copy.duplicate_of_id == original.id and copy.object_key == original.object_key
    assert "duplicate" in copy.flags and copy.sha256 == original.sha256
    assert fake_s3["puts"].count(original.object_key) == 1  # stored once, not twice
    assert original.object_key == f"tender/{ingested['tenant']}/{original.sha256}"
    assert ingested["package"].file_count == len(build_pack())

    await set_rls_context(s, _ctx(frozenset({"lead_estimator"}), tenant_id=ingested["tenant"]))
    events = (await s.execute(text("SELECT action, payload FROM audit_events WHERE entity_type = 'tender_package'"))).all()
    assert any(action == "import" for action, _ in events)


async def test_safety_rejections_archive_expansion_and_classification_match_ground_truth(ingested):
    s = ingested["session"]
    docs = await _by_name(s)

    macro, bomb = docs["BOQ_macro.xlsm"], docs["bomb.zip"]
    assert (macro.status, macro.safety_status) == ("rejected", "rejected_macro")
    assert (bomb.status, bomb.safety_status) == ("rejected", "rejected_zip_bomb")
    assert macro.rejection_reason and bomb.rejection_reason

    zipdoc = docs["Transmittal_2.zip"]
    assert zipdoc.status == "archive"
    members = {d.archive_path: d for d in docs.values() if d.parent_document_id == zipdoc.id}
    assert set(members) == {"Drawings/S-201 Rev A.pdf", "Forms/Form_of_Tender.pdf", "Correspondence/Letter_from_Client.pdf", "Geotech/Geotechnical_Report.pdf"}
    assert all(d.original_filename == d.archive_path.rsplit("/", 1)[-1] for d in members.values())

    wrong = {name: (docs[name].doc_class, want) for name, want in GROUND_TRUTH.items() if docs[name].doc_class != want}
    assert not wrong, wrong
    assert all(docs[name].status == "proposed" for name in GROUND_TRUTH)
    assert docs["C-101 Rev A.dxf"].sub_type == "roads_civil" and docs["S-201 Rev B.pdf"].sub_type == "structural"
    assert docs["S-201 Rev B.pdf"].doc_metadata["drawing_type"] == "general_arrangement"
    assert {d.classified_by for d in docs.values() if d.doc_class} == {"ai"}


async def test_scanned_pdf_goes_to_the_model_with_an_image_and_is_flagged_not_measurable(ingested, mock_model):
    s = ingested["session"]
    scan = (await _by_name(s))["Scan_0042.pdf"]
    assert scan.doc_class == "drawing" and "not_measurable" in scan.flags and "low_confidence" in scan.flags
    assert any(req.images and req.kind == "vision_extract" for req in mock_model)  # no text layer: the vision model, with a page image
    history = (await s.execute(select(DocumentClassification).where(DocumentClassification.document_id == scan.id))).scalars().all()
    assert {h.source for h in history} == {"rules", "model"}
    assert [h.source for h in history if h.is_current] == ["model"]


async def test_every_readable_file_goes_to_the_ai_once_and_only_scans_get_images(ingested, mock_model):
    s = ingested["session"]
    docs = await _by_name(s)
    asked = {re.search(r"^Filename: (.*)$", r.user, re.M).group(1) for r in mock_model}
    readable = {d.original_filename for d in docs.values() if d.safety_status == "accepted" and d.status != "archive" and d.duplicate_of_id is None}
    assert asked == readable
    assert len(mock_model) == len(readable)  # one call per distinct readable file: the duplicate copy reuses its original's class
    with_images = {re.search(r"^Filename: (.*)$", r.user, re.M).group(1) for r in mock_model if r.images}
    assert "Scan_0042.pdf" in with_images and "ITT.pdf" not in with_images and "BOQ_Rev0.xlsx" not in with_images
    assert all(r.kind == "classify" for r in mock_model if not r.images)  # text goes to the classify model
    copy = docs["C-101 Rev A (copy).dxf"]
    assert copy.doc_class == "drawing" and copy.doc_metadata["same_file_as"] == str(docs["C-101 Rev A.dxf"].id)


async def test_revision_of_flag_and_paging_search(ingested):
    s = ingested["session"]
    docs = await _by_name(s)
    assert "revision_of" in docs["C-101 Rev B.dxf"].flags
    assert docs["C-101 Rev B.dxf"].doc_metadata["revision_of_document_id"] == str(docs["C-101 Rev A.dxf"].id)
    rows, total = await svc.list_documents(s, ingested["project"], q="C-101")
    # The addendum's metadata (what it supersedes) is searchable too.
    assert total == 4 and {d.original_filename for d in rows} == {"C-101 Rev A.dxf", "C-101 Rev B.dxf", "C-101 Rev A (copy).dxf", "ADD-01.pdf"}
    page, total_all = await svc.list_documents(s, ingested["project"], limit=5, offset=5)
    assert len(page) == 5 and total_all > 10
    rows, _ = await svc.list_documents(s, ingested["project"], doc_class="drawing", flag="not_measurable")
    assert [d.original_filename for d in rows] == ["Scan_0042.pdf"]


async def test_non_member_estimator_cannot_upload(rls_session, fake_s3):
    tenant_id, project_id = await _seed(rls_session)
    outsider = _ctx(frozenset({"estimator"}), tenant_id=tenant_id, user_id=uuid.uuid4())
    await set_rls_context(rls_session, outsider)
    with pytest.raises(ForbiddenError):
        await svc.create_package(rls_session, outsider, project_id, [("a.pdf", b"%PDF-1.4")])
    assert fake_s3["puts"] == []  # nothing stored before the access check


# ------------------------------------------------------------------ review + routing
async def _lead(ingested) -> RequestContext:
    lead = _ctx(frozenset({"lead_estimator"}), tenant_id=ingested["tenant"])
    await set_rls_context(ingested["session"], lead)
    return lead


async def test_bulk_confirm_routes_each_class_builds_lineage_and_flags_the_settlement(ingested, celery_calls):
    s = ingested["session"]
    docs = await _by_name(s)
    lead = await _lead(ingested)
    settlement_id = (
        await s.execute(text("INSERT INTO bid_settlements (tenant_id, project_id) VALUES (:t, :p) RETURNING id"), {"t": str(ingested["tenant"]), "p": str(ingested["project"])})
    ).scalar_one()

    result = await svc.bulk_confirm(s, lead, ingested["project"], package_id=ingested["package"].id)
    assert result.failed == 0 and result.confirmed >= 13
    docs = await _by_name(s)
    assert docs["Scan_0042.pdf"].status == "proposed" and docs["Notes.csv"].status == "proposed"
    assert docs["C-101 Rev A (copy).dxf"].status == "proposed"

    # Drawings: real Drawing rows in the existing pipeline, ingest triggered with a countdown.
    a, b = docs["C-101 Rev A.dxf"], docs["C-101 Rev B.dxf"]
    assert a.routed_kind == b.routed_kind == "drawing"
    drawings = {d.id: d for d in (await s.execute(select(Drawing))).scalars()}
    da, db = drawings[uuid.UUID(a.routed_ref["drawing_id"])], drawings[uuid.UUID(b.routed_ref["drawing_id"])]
    assert (da.revision_label, db.revision_label, da.discipline_hint) == ("A", "B", "roads_civil")
    assert da.object_key == a.object_key and da.bucket == a.bucket  # content-addressed, no copy
    assert db.supersedes_id == da.id and b.supersedes_id == a.id and a.routed_ref["superseded_by"] == str(b.id)
    assert da.status == "queued" and len(celery_calls["ingest"]) == len([d for d in docs.values() if d.routed_kind == "drawing"])
    assert all(countdown > 0 for _, countdown in celery_calls["ingest"])
    s201a, s201b = docs["Drawings/S-201 Rev A.pdf"], docs["S-201 Rev B.pdf"]
    assert s201b.supersedes_id == s201a.id

    # BOQ: retained, wizard pre-filled with the detected sheet + header row + mapping.
    boq = docs["BOQ_Rev0.xlsx"]
    assert boq.routed_kind == "boq_wizard" and boq.status == "routed"
    prefill = await svc.boq_prefill(s, boq.id)
    assert (prefill.sheet_name, prefill.header_row) == ("BOQ", 3)
    assert prefill.suggested_mapping["item_no_column"] == "Item No" and prefill.suggested_mapping["description_column"] == "Description"
    assert prefill.suggested_mapping["quantity_column"] == "Qty" and prefill.suggested_mapping["uom_column"] == "Unit"
    assert (prefill.suggested_mapping["rate_column"], prefill.suggested_mapping["amount_column"]) == ("E", "F")
    assert prefill.sheet_names == ["Summary", "BOQ"]

    # Addendum: register row, links resolved (drawing + BOQ), draft settlement flagged.
    addendum_doc = docs["ADD-01.pdf"]
    assert addendum_doc.routed_kind == "addendum"
    addendum = (await s.execute(select(Addendum).where(Addendum.document_id == addendum_doc.id))).scalar_one()
    assert addendum.addendum_no == "1" and addendum.issue_date == "12 March 2026"
    links = {(l.reference_text, l.action): l for l in (await s.execute(select(AddendumLink).where(AddendumLink.addendum_id == addendum.id))).scalars()}
    assert links[("C-101 Rev A", "supersedes")].resolved and links[("C-101 Rev A", "supersedes")].target_document_id == a.id
    assert links[("BOQ", "amends")].resolved and links[("BOQ", "amends")].target_document_id == boq.id
    assert addendum.flagged_settlement_ids == [str(settlement_id)]
    listed = (await svc.list_addenda(s, ingested["project"]))[0]
    assert listed.open_settlement_ids == [settlement_id] and {l.action for l in listed.links} == {"supersedes", "amends"}
    # A refresh after the addendum clears the prompt; submitted ones stay flagged until decided.
    await s.execute(text("UPDATE bid_settlements SET quantities_refreshed_at = :t WHERE id = :i"), {"t": datetime.now(timezone.utc) + timedelta(minutes=1), "i": str(settlement_id)})
    assert (await svc.list_addenda(s, ingested["project"]))[0].open_settlement_ids == []
    await s.execute(text("UPDATE bid_settlements SET status = 'submitted' WHERE id = :i"), {"i": str(settlement_id)})
    assert (await svc.list_addenda(s, ingested["project"]))[0].open_settlement_ids == [settlement_id]

    # Everything else goes to the register, searchable and downloadable.
    for name in ("SPEC_Section_03300_Concrete.pdf", "Conditions_of_Contract.pdf", "ITT.pdf", "Programme.xlsx", "RFI_Response_07.pdf", "Forms/Form_of_Tender.pdf", "Correspondence/Letter_from_Client.pdf", "Geotech/Geotechnical_Report.pdf"):
        assert (docs[name].status, docs[name].routed_kind) == ("routed", "register"), name
    reg, total = await svc.list_documents(s, ingested["project"], status="routed", routed_kind="register", q="concrete")
    assert total == 1 and reg[0].original_filename == "SPEC_Section_03300_Concrete.pdf"
    assert (await svc.download_url(s, lead, docs["ITT.pdf"].id)).endswith(docs["ITT.pdf"].sha256)

    # Audit: confirm and route events for a routed document.
    events = (await s.execute(text("SELECT payload->>'event' FROM audit_events WHERE entity_type = 'project_document' AND entity_id = :e"), {"e": str(a.id)})).scalars().all()
    assert {"classify", "confirm", "route"} <= set(events)
    decided = (
        await s.execute(
            text("SELECT payload->>'decided_by' FROM audit_events WHERE entity_type = 'project_document' AND entity_id = :e AND payload->>'event' IN ('classify', 'confirm')"),
            {"e": str(a.id)},
        )
    ).scalars().all()
    assert sorted(decided) == ["ai", "user"]  # the AI proposed, a person confirmed


async def test_explicit_confirm_of_the_ones_bulk_skips_and_double_confirm_is_refused(ingested, celery_calls):
    s = ingested["session"]
    lead = await _lead(ingested)
    docs = await _by_name(s)
    scan = await svc.confirm_document(s, lead, docs["Scan_0042.pdf"].id)
    assert scan.status == "routed" and scan.routed_kind == "drawing" and scan.routed_ref["not_measurable"] is True
    assert scan.routed_ref["kind"] == "scanned_pdf"
    dup = await svc.confirm_document(s, lead, docs["C-101 Rev A (copy).dxf"].id)
    assert (dup.status, dup.routed_kind) == ("routed", "duplicate")
    with pytest.raises(ConflictError):
        await svc.confirm_document(s, lead, docs["Scan_0042.pdf"].id)
    for name in ("BOQ_macro.xlsm", "bomb.zip", "Transmittal_2.zip"):
        with pytest.raises(ConflictError):
            await svc.confirm_document(s, lead, docs[name].id)


async def test_dwg_is_routed_to_a_drawing_and_sent_to_the_converter_not_the_dxf_pipeline(rls_session, fake_s3, mock_model, celery_calls):
    tenant_id, project_id = await _seed(rls_session)
    est = _ctx(frozenset({"estimator"}), tenant_id=tenant_id)
    await set_rls_context(rls_session, est)
    await svc.create_package(rls_session, est, project_id, [("Site_Plan.dwg", b"AC1027" + b"\x00" * 64)])
    await _process_all(rls_session, est)
    doc = (await _by_name(rls_session))["Site_Plan.dwg"]
    # Convertible, so no manual-conversion flags (they only appear when DWG_CONVERSION_ENABLED=false).
    assert doc.doc_class == "drawing" and not {"convert_to_dxf", "not_measurable"} & set(doc.flags)
    lead = _ctx(frozenset({"lead_estimator"}), tenant_id=tenant_id)
    await set_rls_context(rls_session, lead)
    routed = await svc.confirm_document(rls_session, lead, doc.id)
    assert (routed.status, routed.routed_kind) == ("routed", "drawing")
    assert routed.routed_ref["kind"] == "dwg" and routed.routed_ref["ingest_started"] is True
    drawing = (await rls_session.execute(select(Drawing))).scalar_one()
    assert (drawing.kind, drawing.original_filename, drawing.status) == ("dwg", "Site_Plan.dwg", "queued")
    assert len(celery_calls["convert"]) == 1 and celery_calls["ingest"] == []
    assert celery_calls["convert"][0][0][0] == str(drawing.id)


async def test_dwg_with_conversion_switched_off_is_flagged_and_parked_needs_conversion(rls_session, fake_s3, mock_model, celery_calls, monkeypatch):
    from app.core.config import get_settings

    tenant_id, project_id = await _seed(rls_session)
    real = get_settings()
    off = real.model_copy(update={"dwg_conversion_enabled": False})
    monkeypatch.setattr(processing, "get_settings", lambda: off)
    monkeypatch.setattr("app.services.takeoff.get_settings", lambda: off)
    est = _ctx(frozenset({"estimator"}), tenant_id=tenant_id)
    await set_rls_context(rls_session, est)
    await svc.create_package(rls_session, est, project_id, [("Site_Plan.dwg", b"AC1027" + b"\x00" * 64)])
    await _process_all(rls_session, est)
    doc = (await _by_name(rls_session))["Site_Plan.dwg"]
    assert {"convert_to_dxf", "not_measurable"} <= set(doc.flags)
    lead = _ctx(frozenset({"lead_estimator"}), tenant_id=tenant_id)
    await set_rls_context(rls_session, lead)
    await svc.confirm_document(rls_session, lead, doc.id)
    drawing = (await rls_session.execute(select(Drawing))).scalar_one()
    assert drawing.status == "needs_conversion" and drawing.conversion_reason == "disabled"
    assert celery_calls["convert"] == [] and celery_calls["ingest"] == []


async def test_reclassify_edit_exclude_rerun_and_disabled_class(ingested, celery_calls):
    s = ingested["session"]
    lead = await _lead(ingested)
    docs = await _by_name(s)
    notes = docs["Notes.csv"]

    changed = await svc.reclassify(s, lead, notes.id, "correspondence", None, "it is a note to the client")
    assert (changed.doc_class, float(changed.confidence)) == ("correspondence", 1.0)
    current = (await s.execute(select(DocumentClassification).where(DocumentClassification.document_id == notes.id, DocumentClassification.is_current))).scalars().all()
    assert [c.source for c in current] == ["user"]
    with pytest.raises(ValidationAppError):
        await svc.reclassify(s, lead, notes.id, "boq", "civil_infra", None)
    with pytest.raises(ValidationAppError):
        await svc.reclassify(s, lead, notes.id, "not_a_class", None, None)

    edited = await svc.edit_metadata(s, lead, notes.id, metadata={"note": "x"}, title="Site notes", document_number="n-1", revision_label="b")
    assert (edited.title, edited.document_number, edited.revision_label) == ("Site notes", "N-1", "B")
    assert edited.doc_metadata["note"] == "x" and edited.doc_metadata["document_number"] == "N-1"

    md = _ctx(frozenset({"managing_director"}), tenant_id=ingested["tenant"])
    await set_rls_context(s, md)
    updated = await svc.update_class(s, md, "correspondence", TenderClassUpdate(enabled=False, label="Letters"))
    assert (updated.enabled, updated.label) == (False, "Letters")
    await set_rls_context(s, lead)
    with pytest.raises(ConflictError):
        await svc.confirm_document(s, lead, notes.id)
    with pytest.raises(ConflictError):
        await svc.reclassify(s, lead, docs["ITT.pdf"].id, "correspondence", None, None)

    excluded = await svc.exclude(s, lead, docs["ITT.pdf"].id, "not part of this tender")
    assert excluded.status == "excluded" and "not part of this tender" in excluded.error_message
    with pytest.raises(ConflictError):
        await svc.confirm_document(s, lead, docs["ITT.pdf"].id)

    scan = docs["Scan_0042.pdf"]
    rerun = await svc.request_rerun(s, lead, scan.id)
    assert rerun.status == "received" and rerun.queued_at is None and rerun.attempts == 0
    assert len(celery_calls["rerun"]) == 1  # the dispatcher is asked to run; it claims the file from the database
    assert celery_calls["rerun"][0][0] == (str(ingested["tenant"]), str(scan.package_id))
    with pytest.raises(ConflictError):
        await svc.request_rerun(s, lead, docs["bomb.zip"].id)  # rejected by safety: cannot be re-run

    events = (await s.execute(text("SELECT payload->>'event' FROM audit_events WHERE entity_type = 'project_document' AND entity_id = :e"), {"e": str(notes.id)})).scalars().all()
    assert {"reclassify", "edit_metadata"} <= set(events)


async def test_worker_glue_isolates_a_failing_document_and_finalises_the_package(rls_session, fake_s3, mock_model, celery_calls, monkeypatch):
    from app.workers.tasks import tender_intake as worker

    tenant_id, project_id = await _seed(rls_session)
    est = _ctx(frozenset({"estimator"}), tenant_id=tenant_id)
    await set_rls_context(rls_session, est)
    files = [f for f in build_pack() if f.name in ("ITT.pdf", "Conditions_of_Contract.pdf", "Notes.csv")]
    package, ids = await svc.create_package(rls_session, est, project_id, [(f.name, f.data) for f in files])

    real = processing.process_document

    async def flaky(session, ctx, document_id, prepared=None, run=None):
        doc = await processing.get_document(session, document_id)
        if doc.original_filename == "ITT.pdf":
            raise RuntimeError("boom")
        return await real(session, ctx, document_id, prepared, run)

    monkeypatch.setattr(worker.processing, "process_document", flaky)
    await drive_worker(rls_session, monkeypatch, est, tenant_id)

    docs = await _by_name(rls_session)
    # A failure is retried (the dispatcher picks the file up again) and, after INTAKE_MAX_ATTEMPTS, parked as failed.
    assert docs["ITT.pdf"].status == "failed" and "boom" in docs["ITT.pdf"].error_message
    assert docs["ITT.pdf"].attempts == get_settings().intake_max_attempts
    # The contract is a confident AI classification: accepted and routed to the register without a person.
    assert (docs["Conditions_of_Contract.pdf"].status, docs["Conditions_of_Contract.pdf"].auto_accepted) == ("routed", True)
    assert docs["Notes.csv"].status == "proposed"  # nothing in it says what it is: waits for a person
    await rls_session.refresh(package)
    assert package.status == "ready"


async def test_parse_model_output_is_the_only_thing_read_from_the_model(ingested):
    # The persisted evidence never carries model-supplied keys beyond the schema fields.
    s = ingested["session"]
    scan = (await _by_name(s))["Scan_0042.pdf"]
    assert set(scan.evidence[0]) == {"rule", "class", "weight", "matched", "page"}
    assert parse_model_output({"doc_class": "other", "confidence": 0.1}).doc_class == "other"
