"""Tender intake at scale (docs/intake-scale/report.md), real Postgres with RLS, fake S3, the mock model:
the resumable register/upload flow, per-file dispatch bounded and honouring pause/cancel, the sweeper for files a dead
worker left behind, size/page parking ("needs check: too large"), the SQL twin of the display status, paged
items/filters/counts, and the server-side filter bulk actions."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, text

from app.core.config import get_settings
from app.core.context import RequestContext, system_context
from app.core.errors import ConflictError, ValidationAppError
from app.db.rls import set_rls_context
from app.integrations.s3 import StreamedObject, UploadAborted
from app.models.takeoff import Drawing
from app.models.tender_intake import ProjectDocument, TenderPackage
from app.schemas.tender_intake import DocFilter, RegisterFileIn, RegisterPackageIn
from app.services import tender_intake as svc
from app.services import tender_intake_processing as processing
from app.services import tender_intake_tree as tree
from app.services import tender_intake_upload as up
from tests.fixtures.tender_pack import build_pack
from tests.integration.test_tender_intake_flow import (  # noqa: F401 -- fixtures and helpers shared with the flow tests
    _by_name,
    _ctx,
    _seed,
    celery_calls,
    drive_worker,
    fake_s3,
    mock_model,
)

pytestmark = pytest.mark.asyncio

PDF = b"%PDF-1.4\n%fake\n"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def reg(*files: tuple[str, bytes], **kw) -> RegisterPackageIn:
    return RegisterPackageIn(files=[RegisterFileIn(path=p, size=len(d), sha256=sha(d)) for p, d in files], **kw)


async def body_of(data: bytes, step: int = 5):
    for i in range(0, len(data), step):
        yield data[i : i + step]


@pytest.fixture
def s3(fake_s3, monkeypatch):
    """`fake_s3` plus the streaming upload: the same verification (digest, size cap) as the real one, kept in memory."""

    async def put_stream(object_key, chunks, *, bucket, expected_sha256=None, max_bytes=None, **kw):
        data = b""
        async for chunk in chunks:
            data += chunk
            if max_bytes is not None and len(data) > max_bytes:
                raise UploadAborted("too big")
        digest = sha(data)
        if expected_sha256 is not None and digest != expected_sha256:
            raise UploadAborted("the uploaded bytes do not match the registered sha256")
        fake_s3["store"][(bucket, object_key)] = data
        fake_s3["puts"].append(object_key)
        return StreamedObject(sha256=digest, size=len(data))

    monkeypatch.setattr(up, "put_object_from_stream", put_stream)
    return fake_s3


@pytest.fixture
async def ctxs(rls_session):
    tenant_id, project_id = await _seed(rls_session)
    est = _ctx(frozenset({"estimator"}), tenant_id=tenant_id)
    lead = _ctx(frozenset({"lead_estimator"}), tenant_id=tenant_id)
    await set_rls_context(rls_session, est)
    return {"tenant": tenant_id, "project": project_id, "est": est, "lead": lead, "s": rls_session}


async def send(c, doc_id: uuid.UUID, package_id: uuid.UUID, data: bytes):
    await set_rls_context(c["s"], c["est"])
    return await up.receive_upload(c["s"], c["est"], package_id, doc_id, body_of(data), declared_size=len(data))


# ------------------------------------------------------------------ register + upload
async def test_register_creates_pending_rows_and_upload_makes_them_received(ctxs, s3):
    c = ctxs
    out = await up.register_files(c["s"], c["est"], c["project"], reg(("Docs/a.pdf", PDF + b"a"), ("Docs/b.pdf", PDF + b"b"), total_files=2, label="TX"))
    assert out.status == "uploading" and not out.resumed and out.expected_count == 2
    assert [(f.state, f.upload) for f in out.files] == [("pending", True), ("pending", True)]
    rows = (await c["s"].execute(select(ProjectDocument))).scalars().all()
    assert {r.status for r in rows} == {"pending_upload"} and {r.archive_path for r in rows} == {"Docs/a.pdf", "Docs/b.pdf"}
    assert s3["puts"] == []  # registering moves no bytes

    first = await send(c, out.files[0].document_id, out.package_id, PDF + b"a")
    assert (first.state, first.registered, first.uploaded, first.package_status) == ("uploaded", 2, 1, "uploading")
    last = await send(c, out.files[1].document_id, out.package_id, PDF + b"b")
    assert (last.uploaded, last.package_status) == (2, "processing")  # everything is here: the pack is being read
    doc = (await c["s"].execute(select(ProjectDocument).where(ProjectDocument.id == out.files[0].document_id))).scalar_one()
    assert doc.status == "received" and doc.uploaded_at is not None and doc.size_bytes == len(PDF) + 1
    assert s3["store"][(doc.bucket, doc.object_key)] == PDF + b"a"
    await set_rls_context(c["s"], c["lead"])  # the audit trail is readable by lead_estimator and above
    events = (await c["s"].execute(text("SELECT payload->>'event' FROM audit_events WHERE entity_type = 'tender_package'"))).scalars().all()
    assert "register" in events and "upload_complete" in events


async def test_a_wrong_digest_is_refused_and_the_file_stays_pending(ctxs, s3):
    c = ctxs
    out = await up.register_files(c["s"], c["est"], c["project"], reg(("a.pdf", PDF + b"a")))
    with pytest.raises(ValidationAppError, match="do not match"):
        await send(c, out.files[0].document_id, out.package_id, PDF + b"tampered")
    doc = (await c["s"].execute(select(ProjectDocument))).scalar_one()
    assert doc.status == "pending_upload" and s3["store"] == {}


async def test_re_dropping_the_folder_resumes_without_duplicates(ctxs, s3):
    c = ctxs
    files = [(f"Pack/f{i}.pdf", PDF + str(i).encode()) for i in range(6)]
    first = await up.register_files(c["s"], c["est"], c["project"], reg(*files, total_files=6))
    for f in first.files[:4]:  # the tab was closed after four files
        await send(c, f.document_id, first.package_id, dict(files)[f.path])
    # ... the same folder is dropped again, in a new request, with no package id
    again = await up.register_files(c["s"], c["est"], c["project"], reg(*files, total_files=6))
    assert again.resumed and again.package_id == first.package_id
    states = {f.path: (f.state, f.upload) for f in again.files}
    assert [states[p] for p, _ in files[:4]] == [("uploaded", False)] * 4
    assert [states[p] for p, _ in files[4:]] == [("pending", True)] * 2
    assert (await c["s"].execute(select(func.count()).select_from(ProjectDocument))).scalar_one() == 6  # no duplicate rows
    puts_before = len(s3["puts"])
    for f in again.files:
        if f.upload:
            await send(c, f.document_id, again.package_id, dict(files)[f.path])
    assert len(s3["puts"]) == puts_before + 2  # only the missing files were sent


async def test_identical_bytes_are_sent_once_and_arrive_together(ctxs, s3):
    c = ctxs
    out = await up.register_files(c["s"], c["est"], c["project"], reg(("A/x.pdf", PDF + b"x"), ("B/x copy.pdf", PDF + b"x"), ("C/y.pdf", PDF + b"y")))
    assert [(f.state, f.upload) for f in out.files] == [("pending", True), ("pending", False), ("pending", True)]
    with pytest.raises(ConflictError):  # the copy has nothing to send
        await send(c, out.files[1].document_id, out.package_id, PDF + b"x")
    await send(c, out.files[0].document_id, out.package_id, PDF + b"x")
    rows = {r.original_filename: r for r in (await c["s"].execute(select(ProjectDocument))).scalars()}
    assert rows["x copy.pdf"].status == "received" and rows["x copy.pdf"].duplicate_of_id == rows["x.pdf"].id and "duplicate" in rows["x copy.pdf"].flags
    assert rows["y.pdf"].status == "pending_upload"
    assert len([k for k in s3["puts"]]) == 1


async def test_bytes_already_in_the_project_need_no_upload(ctxs, s3):
    c = ctxs
    first = await up.register_files(c["s"], c["est"], c["project"], reg(("a.pdf", PDF + b"a")))
    await send(c, first.files[0].document_id, first.package_id, PDF + b"a")
    second = await up.register_files(c["s"], c["est"], c["project"], reg(("again.pdf", PDF + b"a"), new_package=True))
    assert second.package_id != first.package_id and (second.files[0].state, second.files[0].upload) == ("uploaded", False)
    dup = (await c["s"].execute(select(ProjectDocument).where(ProjectDocument.original_filename == "again.pdf"))).scalar_one()
    assert dup.status == "received" and dup.duplicate_of_id is not None and len(s3["puts"]) == 1


async def test_unusable_files_are_rejected_at_registration_with_a_reason(ctxs, s3):
    c = ctxs
    out = await up.register_files(
        c["s"], c["est"], c["project"],
        RegisterPackageIn(files=[
            RegisterFileIn(path="ok.pdf", size=10, sha256="a" * 64),
            RegisterFileIn(path="macro.xlsm", size=10, sha256="b" * 64),
            RegisterFileIn(path="empty.pdf", size=0, sha256="c" * 64),
            RegisterFileIn(path="notes.exe", size=10, sha256="d" * 64),
            RegisterFileIn(path="folder/.DS_Store", size=10, sha256="e" * 64),
            RegisterFileIn(path="huge.pdf", size=get_settings().intake_max_file_size_bytes + 1, sha256="f" * 64),
        ]),
    )
    by = {f.path: f for f in out.files}
    assert by["ok.pdf"].state == "pending"
    assert all(by[p].state == "rejected" and by[p].document_id is None and by[p].reason for p in ("macro.xlsm", "empty.pdf", "notes.exe", "folder/.DS_Store", "huge.pdf"))
    assert (await c["s"].execute(select(func.count()).select_from(ProjectDocument))).scalar_one() == 1


async def test_a_pack_over_the_cap_is_refused_with_a_clear_message(ctxs, s3, monkeypatch):
    c = ctxs
    small = get_settings().model_copy(update={"intake_max_files_per_pack": 3})
    monkeypatch.setattr(up, "get_settings", lambda: small)
    with pytest.raises(ValidationAppError, match=r"4 files; one pack can hold at most 3"):
        await up.register_files(c["s"], c["est"], c["project"], reg(("a.pdf", PDF + b"1"), total_files=4))
    await up.register_files(c["s"], c["est"], c["project"], reg(("a.pdf", PDF + b"1"), ("b.pdf", PDF + b"2"), ("c.pdf", PDF + b"3"), total_files=3))
    with pytest.raises(ValidationAppError, match="at most 3"):  # a fourth file in total, even if the drop said 3
        await up.register_files(c["s"], c["est"], c["project"], reg(("d.pdf", PDF + b"4")))


async def test_a_pack_whose_expected_files_have_not_all_been_announced_stays_uploading(ctxs, s3):
    c = ctxs
    out = await up.register_files(c["s"], c["est"], c["project"], reg(("a.pdf", PDF + b"a"), total_files=3))
    r = await send(c, out.files[0].document_id, out.package_id, PDF + b"a")
    assert r.package_status == "uploading" and (r.uploaded, r.expected_count) == (1, 3)  # 2 more files are still to come


# ------------------------------------------------------------------ pause / resume / cancel
async def test_pause_blocks_uploads_and_dispatch_resume_continues(ctxs, s3):
    c = ctxs
    out = await up.register_files(c["s"], c["est"], c["project"], reg(("a.pdf", PDF + b"a"), ("b.pdf", PDF + b"b")))
    await send(c, out.files[0].document_id, out.package_id, PDF + b"a")
    await set_rls_context(c["s"], c["lead"])
    paused = await up.pause_package(c["s"], c["lead"], out.package_id)
    assert paused.status == "paused"
    with pytest.raises(ConflictError, match="paused"):
        await send(c, out.files[1].document_id, out.package_id, PDF + b"b")
    assert await up.claim_for_dispatch(c["s"], c["tenant"]) == []  # a paused pack's files are not handed out
    with pytest.raises(ConflictError):
        await up.pause_package(c["s"], c["lead"], out.package_id)  # already paused
    resumed = await up.resume_package(c["s"], c["lead"], out.package_id)
    assert resumed.status == "uploading"  # one file is still to come
    await send(c, out.files[1].document_id, out.package_id, PDF + b"b")
    assert len(await up.claim_for_dispatch(c["s"], c["tenant"])) == 2
    await set_rls_context(c["s"], c["lead"])
    events = (await c["s"].execute(text("SELECT payload->>'event' FROM audit_events WHERE entity_type = 'tender_package'"))).scalars().all()
    assert {"pause", "resume"} <= set(events)


async def test_cancel_excludes_unread_files_and_keeps_what_was_sorted(ctxs, s3, mock_model, monkeypatch, celery_calls):
    c = ctxs
    pack = [f for f in build_pack() if f.name in ("ITT.pdf", "Conditions_of_Contract.pdf", "Notes.csv")]
    out = await up.register_files(c["s"], c["est"], c["project"], reg(*[(f.name, f.data) for f in pack]))
    sent = {f.path: f for f in out.files}
    for f in pack[:2]:
        await send(c, sent[f.name].document_id, out.package_id, f.data)
    await drive_worker(c["s"], monkeypatch, c["est"], c["tenant"])  # the two uploaded files are read
    await set_rls_context(c["s"], c["lead"])
    done = await up.cancel_package(c["s"], c["lead"], out.package_id)
    assert done.status == "cancelled" and done.cancelled_documents == 1  # the third never arrived
    docs = await _by_name(c["s"])
    assert docs[pack[2].name].status == "excluded" and "pack cancelled" in docs[pack[2].name].error_message
    assert all(docs[f.name].status in ("routed", "proposed") for f in pack[:2])  # classified work is left alone
    with pytest.raises(ConflictError):
        await up.cancel_package(c["s"], c["lead"], out.package_id)
    with pytest.raises(ConflictError):  # a cancelled pack cannot be resumed
        await up.resume_package(c["s"], c["lead"], out.package_id)


# ------------------------------------------------------------------ dispatch
async def _received(c, n: int, *, package: TenderPackage | None = None, prefix: str = "f"):
    """n `received` documents, as the upload leaves them."""
    s = c["s"]
    await set_rls_context(s, c["lead"])
    if package is None:
        package = TenderPackage(tenant_id=c["tenant"], project_id=c["project"], status="processing", file_count=n)
        s.add(package)
        await s.flush()
    docs = []
    for i in range(n):
        d = ProjectDocument(
            tenant_id=c["tenant"], project_id=c["project"], package_id=package.id, original_filename=f"{prefix}{i}.pdf", ext="pdf",
            sha256=sha(f"{prefix}{i}".encode()), bucket="b", object_key=f"k/{prefix}{i}", size_bytes=10, status="received",
        )
        s.add(d)
        docs.append(d)
    await s.flush()
    return package, docs


async def test_the_dispatcher_hands_out_at_most_the_limit_and_never_the_same_file_twice(ctxs, monkeypatch):
    c = ctxs
    small = get_settings().model_copy(update={"intake_dispatch_limit": 5})
    monkeypatch.setattr(up, "get_settings", lambda: small)
    _, docs = await _received(c, 12)
    first = await up.claim_for_dispatch(c["s"], c["tenant"])
    assert len(first) == 5 and len(set(first)) == 5
    assert await up.claim_for_dispatch(c["s"], c["tenant"]) == []  # five are in flight: the limit is reached
    for d in docs:
        await c["s"].refresh(d)
    assert sum(1 for d in docs if d.queued_at is not None) == 5
    # Those five get read; room opens up and the next five come, in upload order.
    for d in docs:
        if d.id in first:
            d.status = "proposed"
    await c["s"].flush()
    second = await up.claim_for_dispatch(c["s"], c["tenant"])
    assert len(second) == 5 and not set(first) & set(second)


async def test_a_message_the_broker_lost_expires_and_the_file_is_dispatched_again(ctxs, monkeypatch):
    c = ctxs
    _, docs = await _received(c, 2)
    assert len(await up.claim_for_dispatch(c["s"], c["tenant"])) == 2
    assert await up.claim_for_dispatch(c["s"], c["tenant"]) == []
    for d in docs:  # ten minutes pass and nothing started: the broker lost the messages (a restart empties Redis)
        d.queued_at = datetime.now(timezone.utc) - timedelta(seconds=get_settings().intake_requeue_after_s + 5)
    await c["s"].flush()
    assert len(await up.claim_for_dispatch(c["s"], c["tenant"])) == 2


async def test_released_claims_are_dispatched_again(ctxs):
    c = ctxs
    await _received(c, 3)
    ids = await up.claim_for_dispatch(c["s"], c["tenant"])
    await up.release_claims(c["s"], ids[:2])
    assert len(await up.claim_for_dispatch(c["s"], c["tenant"])) == 2


async def test_a_duplicate_waits_until_its_original_has_been_read(ctxs):
    c = ctxs
    _, (orig, copy) = await _received(c, 2)
    copy.duplicate_of_id = orig.id
    await c["s"].flush()
    assert await up.claim_for_dispatch(c["s"], c["tenant"]) == [orig.id]  # the copy waits: it will copy the original's answer
    orig.status = "proposed"
    orig.queued_at = None
    await c["s"].flush()
    assert await up.claim_for_dispatch(c["s"], c["tenant"]) == [copy.id]


async def test_files_that_keep_failing_stop_being_dispatched(ctxs):
    c = ctxs
    _, (d,) = await _received(c, 1)
    d.attempts = get_settings().intake_max_attempts
    await c["s"].flush()
    assert await up.claim_for_dispatch(c["s"], c["tenant"]) == []


# ------------------------------------------------------------------ the sweeper
async def test_files_abandoned_by_a_dead_worker_are_requeued_then_parked(ctxs):
    c = ctxs
    package, docs = await _received(c, 3)
    stale = datetime.now(timezone.utc) - timedelta(seconds=get_settings().intake_stuck_after_s + 60)
    for d, attempts in zip(docs, (1, get_settings().intake_max_attempts, 0), strict=True):
        d.status, d.attempts = "processing", attempts
    await c["s"].flush()
    await c["s"].execute(text("UPDATE project_documents SET updated_at = :t WHERE id IN (:a, :b)"), {"t": stale, "a": docs[0].id, "b": docs[1].id})
    stats = await up.reap_stuck_documents(c["s"], c["tenant"])
    assert (stats["requeued"], stats["failed"]) == (1, 1)
    for d in docs:
        await c["s"].refresh(d)
    assert (docs[0].status, docs[0].queued_at) == ("received", None)
    assert docs[1].status == "failed" and "stopped repeatedly" in docs[1].error_message
    assert docs[2].status == "processing"  # a worker that is alive (recent updated_at) is left alone


async def test_a_worker_takes_over_a_stale_processing_file_but_not_a_live_one(ctxs, s3, mock_model, monkeypatch, celery_calls):
    from app.workers.tasks import tender_intake as worker

    c = ctxs
    out = await up.register_files(c["s"], c["est"], c["project"], reg(*[(f.name, f.data) for f in build_pack() if f.name == "ITT.pdf"]))
    await send(c, out.files[0].document_id, out.package_id, [f for f in build_pack() if f.name == "ITT.pdf"][0].data)
    doc = (await c["s"].execute(select(ProjectDocument))).scalar_one()
    doc.status, doc.attempts = "processing", 1
    await c["s"].flush()

    async def fake(ctx, body, *args):
        await set_rls_context(c["s"], ctx)
        return await body(c["s"], *args)

    monkeypatch.setattr(worker, "with_worker_session", fake)
    monkeypatch.setattr(worker, "enqueue_documents", lambda ids, tenant: [])
    assert await worker._claim(c["s"], doc.id) is None  # fresh heartbeat: someone is working on it
    await c["s"].execute(text("UPDATE project_documents SET updated_at = :t"), {"t": datetime.now(timezone.utc) - timedelta(seconds=get_settings().intake_stuck_after_s + 5)})
    await c["s"].refresh(doc)
    snap = await worker._claim(c["s"], doc.id)
    assert snap is not None and doc.attempts == 2  # the redelivered message is taken over, and counted


# ------------------------------------------------------------------ too large / too slow: parked for a person
async def test_a_file_over_the_processing_limit_is_stored_but_parked_not_read(ctxs, s3, mock_model, monkeypatch, celery_calls):
    c = ctxs
    big = PDF + b"B" * 2048
    out = await up.register_files(c["s"], c["est"], c["project"], reg(("Big/Huge set.pdf", big), ("small.pdf", PDF + b"s")))
    for f, data in zip(out.files, (big, PDF + b"s"), strict=True):
        await send(c, f.document_id, out.package_id, data)
    tiny_limit = get_settings().model_copy(update={"intake_max_process_bytes": 1024})
    monkeypatch.setattr(processing, "get_settings", lambda: tiny_limit)
    monkeypatch.setattr("app.workers.tasks.tender_intake.get_settings", lambda: tiny_limit)
    await drive_worker(c["s"], monkeypatch, c["est"], c["tenant"])
    docs = await _by_name(c["s"])
    huge = docs["Big/Huge set.pdf"]
    assert huge.status == "proposed" and huge.doc_class is None and "too_large" in huge.flags
    assert "Too large to read automatically" in huge.error_message
    assert not any("Huge set" in r.user for r in mock_model)  # it never reached the AI (and was never downloaded)
    # It shows under "needs check" with the reason, and cannot be confirmed (no class), only classified by a person.
    items, total = await tree.list_tree_items(c["s"], c["project"], DocFilter(display_status="needs_check"), limit=10, offset=0)
    assert [i.name for i in items if "too_large" in i.flags] == ["Huge set.pdf"] and "Too large" in items[0].status_reason
    await set_rls_context(c["s"], c["lead"])
    with pytest.raises(ConflictError, match="no class"):
        await svc.confirm_document(c["s"], c["lead"], huge.id)
    done = await svc.reclassify(c["s"], c["lead"], huge.id, "specification", None, "it is the spec", confirm=True)
    assert (done.status, done.routed_kind, done.classified_by) == ("routed", "register", "user")


async def test_a_soft_time_limit_parks_the_file(ctxs, s3, mock_model, monkeypatch, celery_calls):
    from celery.exceptions import SoftTimeLimitExceeded

    c = ctxs
    data = PDF + b"slow"
    out = await up.register_files(c["s"], c["est"], c["project"], reg(("slow.pdf", data)))
    await send(c, out.files[0].document_id, out.package_id, data)

    async def too_slow(*a, **k):
        raise SoftTimeLimitExceeded()

    monkeypatch.setattr(processing, "prepare_document", too_slow)
    await drive_worker(c["s"], monkeypatch, c["est"], c["tenant"])
    doc = (await c["s"].execute(select(ProjectDocument))).scalar_one()
    assert doc.status == "proposed" and "too_large" in doc.flags and "took longer than" in doc.error_message
    pkg = (await c["s"].execute(select(TenderPackage))).scalar_one()
    assert pkg.status == "ready"


async def test_an_oversize_pdf_is_not_routed_into_the_takeoff(ctxs, s3, mock_model, monkeypatch):
    c = ctxs
    _, (doc,) = await _received(c, 1)
    await set_rls_context(c["s"], c["lead"])
    doc.status, doc.doc_class, doc.confidence, doc.classified_by = "proposed", "drawing", 0.95, "ai"
    doc.size_bytes = get_settings().max_upload_size_bytes + 1
    await c["s"].flush()
    with pytest.raises(ConflictError, match="Split it"):
        await svc.confirm_document(c["s"], c["lead"], doc.id)


# ------------------------------------------------------------------ the display status in SQL equals the one in Python
async def _doc(c, name, **kw) -> ProjectDocument:
    s = c["s"]
    package = kw.pop("package", None)
    if package is None:
        package = (await s.execute(select(TenderPackage))).scalars().first()
        if package is None:
            package = TenderPackage(tenant_id=c["tenant"], project_id=c["project"], status="ready", file_count=0)
            s.add(package)
            await s.flush()
    d = ProjectDocument(
        tenant_id=c["tenant"], project_id=c["project"], package_id=package.id, original_filename=name, ext=kw.pop("ext", "pdf"),
        sha256=sha(name.encode()), bucket="b", object_key=f"k/{name}", size_bytes=10, safety_status=kw.pop("safety_status", "accepted"), **kw,
    )
    s.add(d)
    await s.flush()
    return d


async def test_display_status_in_sql_matches_python_for_every_kind_of_document(ctxs):
    c = ctxs
    await set_rls_context(c["s"], c["lead"])
    ai = dict(classified_by="ai", doc_class="specification", confidence=0.95, status="proposed")
    cases = [
        ("pending.pdf", dict(status="pending_upload")),
        ("queued.pdf", dict(status="received")),
        ("reading.pdf", dict(status="processing")),
        ("excluded.pdf", dict(status="excluded", error_message="excluded: no")),
        ("rejected.pdf", dict(status="rejected", rejection_reason="macro")),
        ("failed.pdf", dict(status="failed")),
        ("classified.pdf", dict(ai)),
        ("lowconf.pdf", dict(ai, confidence=0.5)),
        ("conflict.pdf", dict(ai, flags=["conflict"])),
        ("injection.pdf", dict(ai, flags=["injection_suspected"])),
        ("unavailable.pdf", dict(ai, flags=["model_unavailable"])),
        ("rules.pdf", dict(ai, classified_by="rules", flags=["rules_fallback"])),
        ("unsafe.pdf", dict(ai, safety_status="pending")),
        ("badext.xlsx", dict(ai, doc_class="drawing", ext="xlsx", sub_type="roads_civil")),
        ("drawing.dxf", dict(ai, doc_class="drawing", ext="dxf", sub_type="roads_civil")),
        ("boq.csv", dict(ai, doc_class="boq", ext="csv")),
        ("noclass.pdf", dict(status="proposed", flags=["too_large"], error_message="Too large")),
        ("routed.pdf", dict(status="routed", routed_kind="register", doc_class="specification")),
        ("dupe.pdf", dict(status="routed", routed_kind="duplicate")),
        ("notmeasurable.png", dict(status="routed", routed_kind="not_measurable", routed_ref={"note": "raster"}, ext="png")),
    ]
    docs = {n: await _doc(c, n, **kw) for n, kw in cases}
    for status in ("uploaded", "queued", "converting", "indexing", "extracting", "embedding", "failed", "needs_conversion", "partial", "ready"):
        drawing = Drawing(
            tenant_id=c["tenant"], project_id=c["project"], original_filename=f"{status}.pdf", kind="vector_pdf", bucket="b", object_key=f"d/{status}",
            size_bytes=1, sha256=sha(status.encode()), status=status,
        )
        c["s"].add(drawing)
        await c["s"].flush()
        docs[f"drawing-{status}"] = await _doc(c, f"drawing-{status}.pdf", status="routed", routed_kind="drawing", routed_ref={"drawing_id": str(drawing.id)}, doc_class="drawing")
    docs["drawing-orphan"] = await _doc(c, "drawing-orphan.pdf", status="routed", routed_kind="drawing", routed_ref={"drawing_id": str(uuid.uuid4())}, doc_class="drawing")

    threshold = await svc.get_auto_accept_min(c["s"])
    drawings = {d.id: d for d in (await c["s"].execute(select(Drawing))).scalars()}
    python = {n: tree._display(d, threshold, drawings)[0] for n, d in docs.items()}
    assert set(python.values()) >= {"uploading", "queued", "reading", "classified", "needs_check", "failed", "excluded", "ready", "extracting"}
    for display in set(python.values()):
        got, _ = await tree.list_tree_items(c["s"], c["project"], DocFilter(display_status=display), limit=500, offset=0)
        listed = {i.name for i in got}
        expected = {d.original_filename for n, d in docs.items() if python[n] == display and d.status != "pending_upload"}
        assert listed == expected, (display, listed ^ expected)
    summary = (await tree.build_summary(c["s"], c["project"], ai_available=True, ai_message=None)).summary
    want: dict[str, int] = {}
    for n, v in python.items():
        want[v] = want.get(v, 0) + 1
    assert summary.pending_upload == 1 == want.pop("uploading")
    assert summary.by_display_status == want and summary.total == sum(want.values())


# ------------------------------------------------------------------ filters, paging, counts
async def _library(c):
    await set_rls_context(c["s"], c["lead"])
    ai = dict(classified_by="ai", confidence=0.95, status="routed")
    spec = [
        ("Drawings/Roads/R-1.pdf", dict(ai, doc_class="drawing", sub_type="roads_civil", doc_metadata={"drawing_type": "plan_profile"}, archive_path="Drawings/Roads/R-1.pdf")),
        ("Drawings/Roads/R-2.pdf", dict(ai, doc_class="drawing", sub_type="roads_civil", doc_metadata={"drawing_type": "cross_sections"}, archive_path="Drawings/Roads/R-2.pdf")),
        ("Drawings/Sewer/S-1.pdf", dict(ai, doc_class="drawing", sub_type="sewer", archive_path="Drawings/Sewer/S-1.pdf")),
        ("Specs/Part_1.pdf", dict(ai, doc_class="specification", archive_path="Specs/Part_1.pdf")),
        ("Specs/50% done_(draft).pdf", dict(ai, doc_class="specification", archive_path="Specs/50% done_(draft).pdf")),
        ("top.pdf", dict(ai, doc_class="contract")),
        ("mystery.pdf", dict(status="proposed", classified_by="ai", confidence=0.4, doc_class="other", flags=["low_confidence"], archive_path="Misc/mystery.pdf")),
        ("scan.pdf", dict(status="proposed", flags=["too_large"], error_message="Too large")),
        ("by-user.pdf", dict(status="routed", classified_by="user", doc_class="contract", confirmed_by=uuid.uuid4(), archive_path="Misc/by-user.pdf")),
    ]
    for name, kw in spec:
        await _doc(c, name.rsplit("/", 1)[-1], **kw)


async def names(c, **f):
    items, total = await tree.list_tree_items(c["s"], c["project"], DocFilter(**f), limit=500, offset=0)
    return sorted(i.name for i in items), total


async def test_filters_select_exactly_the_group_they_describe(ctxs):
    c = ctxs
    await _library(c)
    assert (await names(c, doc_class="drawing"))[0] == ["R-1.pdf", "R-2.pdf", "S-1.pdf"]
    assert (await names(c, doc_class="drawing", discipline="roads_civil"))[0] == ["R-1.pdf", "R-2.pdf"]
    assert (await names(c, doc_class="drawing", discipline="roads_civil", drawing_type="plan_profile"))[0] == ["R-1.pdf"]
    assert (await names(c, doc_class="drawing", discipline="sewer", drawing_type="none"))[0] == ["S-1.pdf"]
    assert (await names(c, doc_class="none"))[0] == ["scan.pdf"]
    assert (await names(c, has_class=True))[1] == 8 and (await names(c, has_class=False))[0] == ["scan.pdf"]
    assert (await names(c, folder="Drawings/Roads"))[0] == ["R-1.pdf", "R-2.pdf"]
    assert (await names(c, folder="Drawings"))[0] == [] and (await names(c, folder="Drawings", include_subfolders=True))[1] == 3
    assert (await names(c, folder=""))[0] == ["scan.pdf", "top.pdf"]  # top-level files only
    assert (await names(c, folder="Drawings/Roads/", include_subfolders=False))[0] == []  # exact match: no trailing slash
    assert (await names(c, q="50%"))[0] == ["50% done_(draft).pdf"]  # % and _ are literal characters, not wildcards
    assert (await names(c, q="_"))[0] == ["50% done_(draft).pdf", "Part_1.pdf"]
    assert (await names(c, q="Pa_t"))[0] == [] and (await names(c, q="part_1"))[0] == ["Part_1.pdf"]  # case-insensitive
    assert (await names(c, display_status="needs_check"))[0] == ["mystery.pdf", "scan.pdf"]
    assert (await names(c, display_status="needs_check", exclude_flags=["too_large"]))[0] == ["mystery.pdf"]
    assert (await names(c, decided_by="user"))[0] == ["by-user.pdf"]
    assert (await names(c, decided_by="ai"))[1] == 7  # classified by the AI (auto-accepted or still waiting) and not changed by a person
    assert (await names(c, flag="low_confidence"))[0] == ["mystery.pdf"]


async def test_items_are_paged_in_a_stable_order_with_the_full_total(ctxs):
    c = ctxs
    await set_rls_context(c["s"], c["lead"])
    for i in range(37):
        await _doc(c, f"p{i:02d}.pdf", status="routed", routed_kind="register", doc_class="specification")
    seen: list[str] = []
    for offset in range(0, 37, 10):
        page, total = await tree.list_tree_items(c["s"], c["project"], DocFilter(doc_class="specification"), limit=10, offset=offset)
        assert total == 37
        seen += [i.name for i in page]
    assert len(seen) == 37 == len(set(seen))
    again = [i.name for i in (await tree.list_tree_items(c["s"], c["project"], DocFilter(doc_class="specification"), limit=500, offset=0))[0]]
    assert again == seen  # the same order every time, so paging never skips or repeats


async def test_the_summary_counts_groups_folders_and_packs_without_listing_files(ctxs):
    c = ctxs
    await _library(c)
    out = await tree.build_summary(c["s"], c["project"], ai_available=True, ai_message=None)
    assert not hasattr(out, "items")
    assert out.summary.total == 9 and out.summary.needs_check == 2
    g = {(x.doc_class, x.discipline, x.drawing_type): x.count for x in out.groups}
    assert g[("drawing", "roads_civil", "plan_profile")] == 1 and g[("drawing", "sewer", None)] == 1 and g[("specification", None, None)] == 2
    assert sum(g.values()) == 9
    f = {x.folder: x.count for x in out.folders}
    assert f["Drawings/Roads"] == 2 and f["Drawings/Sewer"] == 1 and f["Specs"] == 2 and f[""] == 2 and sum(f.values()) == 9
    assert out.summary.by_class["drawing"] == 3 and out.summary.drawings_total == 0
    assert out.packages and out.packages[0].registered == 9


# ------------------------------------------------------------------ server-side bulk actions
async def test_confirm_all_by_filter_covers_every_match_in_chunks_and_never_loops(ctxs, monkeypatch, celery_calls):
    c = ctxs
    await set_rls_context(c["s"], c["lead"])
    ai = dict(status="proposed", classified_by="ai", doc_class="specification", confidence=0.6)  # needs a person: below the 0.85 threshold
    for i in range(23):
        await _doc(c, f"s{i:02d}.pdf", **ai)
    await _doc(c, "conflict.pdf", **ai, flags=["conflict"])
    await _doc(c, "classless.pdf", status="proposed", flags=["too_large"])
    await _doc(c, "broken.pdf", **dict(ai, doc_class="not_a_class"))  # confirming it fails: reported, not retried forever
    small = get_settings().model_copy(update={"intake_bulk_chunk": 10})
    monkeypatch.setattr(svc, "get_settings", lambda: small)
    flt = DocFilter(display_status="needs_check", has_class=True, exclude_flags=["conflict", "injection_suspected"])
    cursor, confirmed, failed, calls, matched = None, 0, 0, 0, None
    while True:
        r = await svc.bulk_confirm(c["s"], c["lead"], c["project"], doc_filter=flt, cursor=cursor)
        calls += 1
        confirmed, failed, matched = confirmed + r.confirmed, failed + r.failed, matched or r.matched
        cursor = r.next_cursor
        if cursor is None:
            break
        assert calls < 10
    assert (confirmed, failed, matched, calls) == (23, 1, 24, 3)
    docs = await _by_name(c["s"])
    assert all(docs[f"s{i:02d}.pdf"].status == "routed" and docs[f"s{i:02d}.pdf"].confirmed_by == c["lead"].user_id for i in range(23))
    assert docs["conflict.pdf"].status == "proposed" and docs["classless.pdf"].status == "proposed"  # held back for a one-by-one check
    events = (await c["s"].execute(text("SELECT payload FROM audit_events WHERE payload->>'event' = 'bulk_confirm'"))).scalars().all()
    assert len(events) == 3 and events[0]["by_filter"]["display_status"] == "needs_check"


async def test_reclassify_by_filter_changes_every_match(ctxs, monkeypatch, celery_calls):
    c = ctxs
    await set_rls_context(c["s"], c["lead"])
    for i in range(7):
        await _doc(c, f"x{i}.pdf", status="proposed", classified_by="ai", doc_class="other", confidence=0.9, archive_path=f"Misc/x{i}.pdf")
    await _doc(c, "elsewhere.pdf", status="proposed", classified_by="ai", doc_class="other", confidence=0.9, archive_path="Other/elsewhere.pdf")
    small = get_settings().model_copy(update={"intake_bulk_chunk": 3})
    monkeypatch.setattr(svc, "get_settings", lambda: small)
    cursor, changed = None, 0
    while True:
        r = await svc.bulk_reclassify(c["s"], c["lead"], c["project"], None, "correspondence", None, None, "filed by folder", True, doc_filter=DocFilter(folder="Misc"), cursor=cursor)
        changed += r.confirmed
        cursor = r.next_cursor
        if cursor is None:
            break
    assert changed == 7
    docs = await _by_name(c["s"])
    assert {docs[f"Misc/x{i}.pdf"].doc_class for i in range(7)} == {"correspondence"} and docs["Other/elsewhere.pdf"].doc_class == "other"
    with pytest.raises(ValidationAppError):
        await svc.bulk_reclassify(c["s"], c["lead"], c["project"], None, "other", None, None, None, True)


# ------------------------------------------------------------------ package status
async def test_package_status_follows_the_documents_and_respects_operator_decisions(ctxs):
    c = ctxs
    package, docs = await _received(c, 2)
    assert await svc.refresh_package_status(c["s"], package.id) == "processing"
    for d in docs:
        d.status = "failed"
    await c["s"].flush()
    assert await svc.refresh_package_status(c["s"], package.id) == "failed"
    docs[0].status = "proposed"
    await c["s"].flush()
    assert await svc.refresh_package_status(c["s"], package.id) == "ready"
    package.status = "paused"
    docs[1].status = "received"
    await c["s"].flush()
    assert await svc.refresh_package_status(c["s"], package.id) == "paused"  # an operator's decision is not overwritten


async def test_the_worker_context_is_the_system_not_a_person():
    ctx = system_context(uuid.uuid4())
    assert ctx.is_system and ctx.user_id is None and isinstance(ctx, RequestContext)
