"""The resumable upload, pack controls and paged tree at the HTTP boundary: who may register/upload (estimator+, project
members), who may pause/resume/cancel and bulk-confirm by filter (lead_estimator+), the streaming PUT (the body reaches S3
in the chunks it was sent in, never as one buffered blob), and the error messages the UI shows. Lowest allowed role and a
denied role per permission."""

from __future__ import annotations

import hashlib
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import Role
from app.integrations.s3 import StreamedObject, UploadAborted
from tests.api.test_tender_intake_api import PDF, TENANT, _seed_doc, _seed_project, _sub_of

pytestmark = pytest.mark.asyncio


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture(autouse=True)
def _fakes(monkeypatch):
    from app.services import tender_intake as svc
    from app.services import tender_intake_processing as processing
    from app.services import tender_intake_upload as up
    from app.workers.tasks import tender_intake as worker

    store: dict[str, bytes] = {}
    chunk_sizes: list[int] = []

    async def put_stream(object_key, chunks, *, bucket, expected_sha256=None, max_bytes=None, **kw):
        data = b""
        async for chunk in chunks:
            chunk_sizes.append(len(chunk))
            data += chunk
            if max_bytes is not None and len(data) > max_bytes:
                raise UploadAborted("too big")
        digest = sha(data)
        if expected_sha256 is not None and digest != expected_sha256:
            raise UploadAborted("the uploaded bytes do not match the registered sha256")
        store[object_key] = data
        return StreamedObject(sha256=digest, size=len(data))

    async def presign(object_key, *args, **kwargs):
        return f"https://s3.test/{object_key}"

    monkeypatch.setattr(up, "put_object_from_stream", put_stream)
    monkeypatch.setattr(svc, "presign_get_url", presign)
    dispatched: list = []
    monkeypatch.setattr(worker.dispatch_intake, "apply_async", lambda args=None, countdown=0, **kw: dispatched.append(args))
    return {"store": store, "chunks": chunk_sizes, "dispatched": dispatched, "processing": processing}


def reg_body(files: list[tuple[str, bytes]], **extra) -> dict:
    return {"files": [{"path": p, "size": len(d), "sha256": sha(d)} for p, d in files], **extra}


async def register(client, project_id, files, **extra):
    return await client.post(f"/api/v1/projects/{project_id}/tender-packages/register", json=reg_body(files, **extra))


async def put(client, package_id, doc_id, data: bytes):
    return await client.put(
        f"/api/v1/tender-packages/{package_id}/documents/{doc_id}/content", content=data, headers={"content-type": "application/octet-stream"}
    )


async def join(app_engine, project_id, client) -> None:
    async with AsyncSession(app_engine) as session, session.begin():
        await session.execute(text("SELECT set_config('app.tenant_id', :t, false), set_config('app.is_system', 'on', false)"), {"t": TENANT})
        await session.execute(text("INSERT INTO project_members (project_id, user_id, tenant_id) VALUES (:p, :u, :t)"), {"p": project_id, "u": await _sub_of(client), "t": TENANT})


async def member(authed_client, app_engine, role=Role.ESTIMATOR.value):
    client = authed_client(frozenset({role}))
    project_id, _ = await _seed_project(app_engine, member_sub=await _sub_of(client))
    return client, project_id


# ------------------------------------------------------------------ register + upload over HTTP
async def test_estimator_registers_uploads_and_the_tree_shows_counts_only(authed_client, app_engine, _fakes):
    est, project_id = await member(authed_client, app_engine)
    files = [("Docs/a.pdf", PDF + b"a"), ("Docs/b.pdf", PDF + b"b")]
    resp = await register(est, project_id, files, total_files=2, label="TX")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "uploading" and body["resumed"] is False and body["expected_count"] == 2
    assert [(f["state"], f["upload"]) for f in body["files"]] == [("pending", True), ("pending", True)]

    first = await put(est, body["package_id"], body["files"][0]["document_id"], files[0][1])
    assert first.status_code == 200 and first.json()["uploaded"] == 1 and first.json()["package_status"] == "uploading"
    last = await put(est, body["package_id"], body["files"][1]["document_id"], files[1][1])
    assert last.json()["package_status"] == "processing"
    assert _fakes["dispatched"] and _fakes["dispatched"][-1] == (TENANT, body["package_id"])  # the dispatcher is asked to run

    tree = (await est.get(f"/api/v1/projects/{project_id}/tender-documents/tree")).json()
    assert "items" not in tree and tree["summary"]["total"] == 2 and tree["summary"]["by_display_status"] == {"queued": 2}
    assert {f["folder"]: f["count"] for f in tree["folders"]} == {"Docs": 2}
    assert tree["packages"][0]["registered"] == 2 and tree["packages"][0]["uploaded"] == 2 and tree["packages"][0]["status"] == "processing"
    page = (await est.get(f"/api/v1/projects/{project_id}/tender-documents/items", params={"folder": "Docs", "limit": 1})).json()
    assert page["total"] == 2 and len(page["items"]) == 1 and page["items"][0]["display_status"] == "queued"


async def test_the_body_reaches_storage_in_the_chunks_it_was_sent_not_as_one_blob(authed_client, app_engine, _fakes):
    est, project_id = await member(authed_client, app_engine)
    data = PDF + b"z" * (3 * 1024 * 1024)
    out = (await register(est, project_id, [("big.pdf", data)])).json()

    async def pieces():
        for i in range(0, len(data), 64 * 1024):
            yield data[i : i + 64 * 1024]

    resp = await est.put(
        f"/api/v1/tender-packages/{out['package_id']}/documents/{out['files'][0]['document_id']}/content", content=pieces()
    )
    assert resp.status_code == 200, resp.text
    assert len(_fakes["chunks"]) >= 30 and max(_fakes["chunks"]) <= 128 * 1024  # streamed, never one 3 MB buffer
    assert sum(_fakes["chunks"]) == len(data)


async def test_a_wrong_digest_is_a_422_with_a_message_and_the_file_stays_pending(authed_client, app_engine, _fakes):
    est, project_id = await member(authed_client, app_engine)
    out = (await register(est, project_id, [("a.pdf", PDF + b"a")])).json()
    bad = await put(est, out["package_id"], out["files"][0]["document_id"], PDF + b"tampered")
    assert bad.status_code == 422 and "do not match" in bad.json()["detail"]
    assert _fakes["store"] == {}
    ok = await put(est, out["package_id"], out["files"][0]["document_id"], PDF + b"a")
    assert ok.status_code == 200  # the same document can be sent again


async def test_re_registering_the_same_folder_resumes(authed_client, app_engine):
    est, project_id = await member(authed_client, app_engine)
    files = [(f"P/f{i}.pdf", PDF + str(i).encode()) for i in range(4)]
    first = (await register(est, project_id, files, total_files=4)).json()
    for f in first["files"][:3]:
        assert (await put(est, first["package_id"], f["document_id"], dict(files)[f["path"]])).status_code == 200
    again = (await register(est, project_id, files, total_files=4)).json()
    assert again["resumed"] is True and again["package_id"] == first["package_id"]
    assert [(f["state"], f["upload"]) for f in again["files"]] == [("uploaded", False)] * 3 + [("pending", True)]


async def test_a_pack_over_the_cap_is_a_422_with_a_message_to_show(authed_client, app_engine):
    est, project_id = await member(authed_client, app_engine)
    resp = await register(est, project_id, [("a.pdf", PDF)], total_files=3001)
    assert resp.status_code == 422 and "3,001 files" in resp.json()["detail"] and "at most 3,000" in resp.json()["detail"]


# ------------------------------------------------------------------ permissions
async def test_non_member_estimator_cannot_register_or_upload(authed_client, app_engine, _fakes):
    owner, project_id = await member(authed_client, app_engine)
    out = (await register(owner, project_id, [("a.pdf", PDF + b"a")])).json()
    outsider = authed_client(frozenset({Role.ESTIMATOR.value}))
    assert (await register(outsider, project_id, [("b.pdf", PDF + b"b")])).status_code == 403
    assert (await put(outsider, out["package_id"], out["files"][0]["document_id"], PDF + b"a")).status_code in (403, 404)
    assert _fakes["store"] == {}


@pytest.mark.parametrize("role", [Role.PROCUREMENT_HEAD.value, Role.BD_DIRECTOR.value, Role.MANAGING_DIRECTOR.value, Role.LEAD_ESTIMATOR.value])
async def test_other_upload_roles_can_register_and_upload(authed_client, app_engine, role):
    client, project_id = await member(authed_client, app_engine, role)
    out = (await register(client, project_id, [("a.pdf", PDF + role.encode())])).json()
    assert (await put(client, out["package_id"], out["files"][0]["document_id"], PDF + role.encode())).status_code == 200


async def test_platform_admin_and_unauthenticated_are_denied(authed_client, app_engine, client):
    project_id, _ = await _seed_project(app_engine, member_sub=None)
    body = reg_body([("a.pdf", PDF)])
    # (before any authed_client call: that fixture sets the Authorization header on the shared client)
    assert (await client.post(f"/api/v1/projects/{project_id}/tender-packages/register", json=body)).status_code == 401
    admin = authed_client(frozenset({Role.PLATFORM_ADMIN.value}))
    assert (await admin.post(f"/api/v1/projects/{project_id}/tender-packages/register", json=body)).status_code == 403


async def test_pause_resume_cancel_need_a_lead_estimator_and_are_audited(authed_client, app_engine, _fakes):
    est, project_id = await member(authed_client, app_engine)
    out = (await register(est, project_id, [("a.pdf", PDF + b"a"), ("b.pdf", PDF + b"b")])).json()
    pk = out["package_id"]
    for action in ("pause", "resume", "cancel"):  # an estimator may upload but not steer the pack
        assert (await est.post(f"/api/v1/tender-packages/{pk}/{action}")).status_code == 403, action

    lead = authed_client(frozenset({Role.LEAD_ESTIMATOR.value}))
    async with AsyncSession(app_engine) as session, session.begin():  # the lead is a member of the project too
        await session.execute(text("SELECT set_config('app.tenant_id', :t, false), set_config('app.is_system', 'on', false)"), {"t": TENANT})
        await session.execute(text("INSERT INTO project_members (project_id, user_id, tenant_id) VALUES (:p, :u, :t)"), {"p": project_id, "u": await _sub_of(lead), "t": TENANT})
    paused = await lead.post(f"/api/v1/tender-packages/{pk}/pause")
    assert paused.status_code == 200 and paused.json()["status"] == "paused"
    blocked = await put(est, pk, out["files"][0]["document_id"], PDF + b"a")
    assert blocked.status_code == 409 and "paused" in blocked.json()["detail"]  # the uploader is told to stop
    assert (await lead.post(f"/api/v1/tender-packages/{pk}/pause")).status_code == 409  # already paused
    resumed = await lead.post(f"/api/v1/tender-packages/{pk}/resume")
    assert resumed.status_code == 200 and resumed.json()["status"] == "uploading"
    assert (await put(est, pk, out["files"][0]["document_id"], PDF + b"a")).status_code == 200
    cancelled = await lead.post(f"/api/v1/tender-packages/{pk}/cancel")
    # Both files are unread (one arrived, one never did): both are left out, with the reason on them.
    assert cancelled.status_code == 200 and cancelled.json() == {"package_id": pk, "status": "cancelled", "cancelled_documents": 2}
    assert (await put(est, pk, out["files"][1]["document_id"], PDF + b"b")).status_code == 409
    listing = (await lead.get(f"/api/v1/projects/{project_id}/tender-documents/items", params={"display_status": "excluded"})).json()
    assert listing["total"] == 2 and all("pack cancelled" in i["status_reason"] for i in listing["items"])
    async with AsyncSession(app_engine) as session, session.begin():
        await session.execute(text("SELECT set_config('app.tenant_id', :t, false), set_config('app.is_system', 'on', false)"), {"t": TENANT})
        seen = (await session.execute(text("SELECT payload->>'event' FROM audit_events WHERE entity_type = 'tender_package' AND entity_id = :e"), {"e": pk})).scalars().all()
    assert {"register", "pause", "resume", "cancel"} <= set(seen)


async def test_bulk_confirm_by_filter_is_lead_only_and_covers_every_match(authed_client, app_engine, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "intake_bulk_chunk", 4)
    lead = authed_client(frozenset({Role.LEAD_ESTIMATOR.value}))
    project_id, package_id = await _seed_project(app_engine, member_sub=await _sub_of(lead))
    for i in range(10):  # needs a person: below the auto-accept threshold
        doc_id = await _seed_doc(app_engine, project_id, package_id, doc_class="specification", status="proposed", name=f"s{i}.pdf")
        async with AsyncSession(app_engine) as session, session.begin():
            await session.execute(text("SELECT set_config('app.tenant_id', :t, false), set_config('app.is_system', 'on', false)"), {"t": TENANT})
            await session.execute(text("UPDATE project_documents SET confidence = 0.5, classified_by = 'ai' WHERE id = :i"), {"i": doc_id})
    flt = {"display_status": "needs_check", "has_class": True, "exclude_flags": ["conflict", "injection_suspected"]}
    # (authed_client re-points the one shared client at a fresh principal each call, so each principal joins the project)
    est = authed_client(frozenset({Role.ESTIMATOR.value}))
    await join(app_engine, project_id, est)
    assert (await est.post(f"/api/v1/projects/{project_id}/tender-documents/bulk-confirm", json={"filter": flt})).status_code == 403
    lead = authed_client(frozenset({Role.LEAD_ESTIMATOR.value}))
    await join(app_engine, project_id, lead)

    count = (await lead.get(f"/api/v1/projects/{project_id}/tender-documents/items", params={"display_status": "needs_check", "has_class": "true", "exclude_flags": ["conflict", "injection_suspected"], "limit": 1})).json()
    assert count["total"] == 10
    cursor, confirmed, calls = None, 0, 0
    while True:
        resp = await lead.post(f"/api/v1/projects/{project_id}/tender-documents/bulk-confirm", json={"filter": flt, "cursor": cursor})
        assert resp.status_code == 200, resp.text
        r = resp.json()
        confirmed, calls, cursor = confirmed + r["confirmed"], calls + 1, r["next_cursor"]
        assert r["matched"] is not None
        if cursor is None:
            break
    assert (confirmed, calls) == (10, 3)
    assert (await lead.get(f"/api/v1/projects/{project_id}/tender-documents/items", params={"display_status": "needs_check"})).json()["total"] == 0
