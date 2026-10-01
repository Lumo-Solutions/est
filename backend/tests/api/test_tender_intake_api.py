"""Tender intake at the HTTP boundary: who may upload (estimator+, project members),
who may confirm/reclassify/edit/exclude/re-run/bulk-confirm (lead_estimator+), who may
configure classes (managing_director), non-member visibility, size/count caps,
and the download redirect. Lowest allowed role and a denied role per permission."""

from __future__ import annotations

import hashlib
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import Role

pytestmark = pytest.mark.asyncio

TENANT = "8f14e45f-ceea-4e97-8d0c-3d3b3f3c1a00"
PDF = b"%PDF-1.4\n%fake\n"


@pytest.fixture(autouse=True)
def _fakes(monkeypatch):
    from app.services import tender_intake as svc
    from app.services import tender_intake_processing as processing
    from app.workers.tasks import tender_intake as worker

    store: dict[str, bytes] = {}

    async def put(object_key, data, content_type, *args, bucket=None, **kwargs):
        store[object_key] = data
        return hashlib.sha256(data).hexdigest()

    async def presign(object_key, *args, **kwargs):
        return f"https://s3.test/{object_key}"

    monkeypatch.setattr(svc, "put_object_streaming", put)
    monkeypatch.setattr(svc, "presign_get_url", presign)
    dispatched: list = []
    monkeypatch.setattr(worker.dispatch_intake, "apply_async", lambda args=None, countdown=0, **kw: dispatched.append(args))
    return {"store": store, "dispatched": dispatched, "processing": processing}


async def _seed_project(app_engine, *, member_sub: str | None) -> tuple[str, str]:
    """Committed project (+ optional membership) under the demo tenant, seeded as system."""
    async with AsyncSession(app_engine) as session, session.begin():
        await session.execute(text("SELECT set_config('app.tenant_id', :t, false), set_config('app.is_system', 'on', false)"), {"t": TENANT})
        project_id = (
            await session.execute(text("INSERT INTO projects (tenant_id, code, name) VALUES (:t, :c, 'TI') RETURNING id"), {"t": TENANT, "c": f"TI-{uuid.uuid4().hex[:8]}"})
        ).scalar_one()
        if member_sub:
            await session.execute(
                text("INSERT INTO project_members (project_id, user_id, tenant_id) VALUES (:p, :u, :t)"),
                {"p": str(project_id), "u": member_sub, "t": TENANT},
            )
        package_id = (
            await session.execute(text("INSERT INTO tender_packages (tenant_id, project_id) VALUES (:t, :p) RETURNING id"), {"t": TENANT, "p": str(project_id)})
        ).scalar_one()
    return str(project_id), str(package_id)


async def _seed_doc(app_engine, project_id: str, package_id: str, *, doc_class="specification", status="proposed", name=None, safety="accepted") -> str:
    name = name or f"{uuid.uuid4().hex[:6]}.pdf"
    async with AsyncSession(app_engine) as session, session.begin():
        await session.execute(text("SELECT set_config('app.tenant_id', :t, false), set_config('app.is_system', 'on', false)"), {"t": TENANT})
        doc_id = (
            await session.execute(
                text(
                    "INSERT INTO project_documents (tenant_id, project_id, package_id, original_filename, ext, sha256, bucket, object_key, "
                    "size_bytes, doc_class, confidence, status, safety_status) VALUES (:t, :p, :k, :n, 'pdf', :sha, 'b', :key, 10, :c, 0.9, :s, :safety) RETURNING id"
                ),
                {"t": TENANT, "p": project_id, "k": package_id, "n": name, "sha": uuid.uuid4().hex * 2, "key": f"tender/{TENANT}/{name}", "c": doc_class, "s": status, "safety": safety},
            )
        ).scalar_one()
    return str(doc_id)


async def _sub_of(client) -> str:
    return (await client.get("/api/v1/auth/me")).json()["sub"]


def _upload(names_and_data):
    return [("files", (n, d, "application/pdf")) for n, d in names_and_data]


# ------------------------------------------------------------------ upload
async def test_estimator_member_uploads_and_a_task_is_dispatched(authed_client, app_engine, _fakes):
    estimator = authed_client(frozenset({Role.ESTIMATOR.value}))
    project_id, _ = await _seed_project(app_engine, member_sub=await _sub_of(estimator))

    resp = await estimator.post(
        f"/api/v1/projects/{project_id}/tender-packages",
        files=_upload([("ITT.pdf", PDF + b"1"), ("Spec.pdf", PDF + b"2")]),
        data={"label": "Transmittal 1", "transmittal_ref": "TX-1", "received_date": "2026-03-01"},
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["file_count"] == 2 and body["status"] == "processing"
    assert _fakes["dispatched"][0] == (TENANT, body["package_id"])  # the dispatcher is asked to run for the pack

    listing = await estimator.get(f"/api/v1/projects/{project_id}/tender-documents")
    assert listing.json()["total"] == 2
    assert {d["status"] for d in listing.json()["items"]} == {"received"}
    package = (await estimator.get(f"/api/v1/tender-packages/{body['package_id']}")).json()
    assert package["label"] == "Transmittal 1" and package["transmittal_ref"] == "TX-1" and package["received_date"] == "2026-03-01"

    more = await estimator.post(f"/api/v1/tender-packages/{body['package_id']}/files", files=_upload([("Extra.pdf", PDF + b"3")]))
    assert more.status_code == 202 and more.json()["file_count"] == 3


async def test_non_member_estimator_is_forbidden_and_sees_nothing(authed_client, app_engine, _fakes):
    member = authed_client(frozenset({Role.ESTIMATOR.value}))
    project_id, package_id = await _seed_project(app_engine, member_sub=await _sub_of(member))
    doc_id = await _seed_doc(app_engine, project_id, package_id)

    outsider = authed_client(frozenset({Role.ESTIMATOR.value}))
    resp = await outsider.post(f"/api/v1/projects/{project_id}/tender-packages", files=_upload([("a.pdf", PDF)]))
    assert resp.status_code == 403
    assert _fakes["store"] == {}  # nothing stored before the access check
    assert (await outsider.get(f"/api/v1/projects/{project_id}/tender-documents")).json()["total"] == 0
    assert (await outsider.get(f"/api/v1/tender-documents/{doc_id}")).status_code == 404


@pytest.mark.parametrize("role", [Role.PROCUREMENT_HEAD.value, Role.BD_DIRECTOR.value, Role.MANAGING_DIRECTOR.value, Role.LEAD_ESTIMATOR.value])
async def test_other_upload_roles_can_upload(authed_client, app_engine, role):
    client = authed_client(frozenset({role}))
    project_id, _ = await _seed_project(app_engine, member_sub=await _sub_of(client))  # member covers lead_estimator
    resp = await client.post(f"/api/v1/projects/{project_id}/tender-packages", files=_upload([("a.pdf", PDF + role.encode())]))
    assert resp.status_code == 202


async def test_platform_admin_and_unauthenticated_are_denied_upload(authed_client, app_engine, client):
    project_id, _ = await _seed_project(app_engine, member_sub=None)
    assert (await client.post(f"/api/v1/projects/{project_id}/tender-packages", files=_upload([("a.pdf", PDF)]))).status_code == 401
    admin = authed_client(frozenset({Role.PLATFORM_ADMIN.value}))
    assert (await admin.post(f"/api/v1/projects/{project_id}/tender-packages", files=_upload([("a.pdf", PDF)]))).status_code == 403


async def test_upload_caps_count_file_size_and_request_size(authed_client, app_engine, monkeypatch):
    from app.core.config import get_settings

    settings = get_settings()
    estimator = authed_client(frozenset({Role.ESTIMATOR.value}))
    project_id, _ = await _seed_project(app_engine, member_sub=await _sub_of(estimator))
    url = f"/api/v1/projects/{project_id}/tender-packages"

    monkeypatch.setattr(settings, "intake_max_files_per_request", 2)
    over = await estimator.post(url, files=_upload([("a.pdf", PDF), ("b.pdf", PDF), ("c.pdf", PDF)]))
    assert over.status_code == 422 and "At most 2 files" in over.text
    monkeypatch.setattr(settings, "intake_max_files_per_request", 300)

    monkeypatch.setattr(settings, "intake_max_file_size_bytes", 50)
    big = await estimator.post(url, files=_upload([("big.pdf", PDF + b"x" * 100)]))
    assert big.status_code == 422 and "larger than" in big.text and "streaming upload" in big.text
    monkeypatch.setattr(settings, "intake_max_file_size_bytes", 250 * 1024 * 1024)

    monkeypatch.setattr(settings, "intake_max_request_bytes", 40)
    batch = await estimator.post(url, files=_upload([("a.pdf", PDF + b"a" * 20), ("b.pdf", PDF + b"b" * 20)]))
    assert batch.status_code == 422 and "per-request limit" in batch.text
    assert (await estimator.post(url, files=[])).status_code == 422


# ------------------------------------------------------------------ review roles
async def test_estimator_denied_lead_estimator_allowed_for_every_review_action(authed_client, app_engine, _fakes):
    lead = authed_client(frozenset({Role.LEAD_ESTIMATOR.value}))
    lead_sub = await _sub_of(lead)
    project_id, package_id = await _seed_project(app_engine, member_sub=lead_sub)
    docs = {k: await _seed_doc(app_engine, project_id, package_id) for k in ("confirm", "reclassify", "edit", "exclude", "rerun")}

    estimator = authed_client(frozenset({Role.ESTIMATOR.value}))
    est_sub = await _sub_of(estimator)
    async with AsyncSession(app_engine) as session, session.begin():
        await session.execute(text("SELECT set_config('app.tenant_id', :t, false), set_config('app.is_system', 'on', false)"), {"t": TENANT})
        await session.execute(text("INSERT INTO project_members (project_id, user_id, tenant_id) VALUES (:p, :u, :t)"), {"p": project_id, "u": est_sub, "t": TENANT})

    calls = {
        "confirm": ("confirm", {}),
        "reclassify": ("reclassify", {"doc_class": "contract"}),
        "edit": ("edit", {"title": "New title"}),
        "exclude": ("exclude", {"reason": "not needed"}),
        "rerun": ("rerun", {}),
    }
    for key, (action, payload) in calls.items():
        denied = await estimator.post(f"/api/v1/tender-documents/{docs[key]}/{action}", json=payload)
        assert denied.status_code == 403, (action, denied.text)
    bulk_denied = await estimator.post(f"/api/v1/projects/{project_id}/tender-documents/bulk-confirm", json={"package_id": package_id})
    assert bulk_denied.status_code == 403

    # Nothing changed by the denied calls.
    listing = (await estimator.get(f"/api/v1/projects/{project_id}/tender-documents")).json()
    assert {d["status"] for d in listing["items"]} == {"proposed"}

    lead = authed_client(frozenset({Role.LEAD_ESTIMATOR.value}))
    async with AsyncSession(app_engine) as session, session.begin():  # re-seat the same member for the fresh principal
        await session.execute(text("SELECT set_config('app.tenant_id', :t, false), set_config('app.is_system', 'on', false)"), {"t": TENANT})
        await session.execute(text("INSERT INTO project_members (project_id, user_id, tenant_id) VALUES (:p, :u, :t)"), {"p": project_id, "u": await _sub_of(lead), "t": TENANT})
    for key, (action, payload) in calls.items():
        ok = await lead.post(f"/api/v1/tender-documents/{docs[key]}/{action}", json=payload)
        assert ok.status_code in (200, 202), (action, ok.text)
    assert (await lead.get(f"/api/v1/tender-documents/{docs['confirm']}")).json()["routed_kind"] == "register"
    assert (await lead.get(f"/api/v1/tender-documents/{docs['reclassify']}")).json()["doc_class"] == "contract"
    assert (await lead.get(f"/api/v1/tender-documents/{docs['exclude']}")).json()["status"] == "excluded"
    assert (await lead.get(f"/api/v1/tender-documents/{docs['edit']}")).json()["title"] == "New title"
    assert _fakes["dispatched"] and _fakes["dispatched"][-1][0] == TENANT  # re-run asks the dispatcher to claim the file again

    # The bulk endpoint too, for the lowest allowed role, over a fresh confident proposal.
    fresh = await _seed_doc(app_engine, project_id, package_id)
    bulk = await lead.post(f"/api/v1/projects/{project_id}/tender-documents/bulk-confirm", json={"package_id": package_id})
    assert bulk.status_code == 200 and bulk.json()["confirmed"] >= 1
    assert (await lead.get(f"/api/v1/tender-documents/{fresh}")).json()["status"] == "routed"


@pytest.mark.parametrize("role", [Role.PROCUREMENT_HEAD.value, Role.BD_DIRECTOR.value, Role.MANAGING_DIRECTOR.value])
async def test_senior_roles_can_confirm_without_membership(authed_client, app_engine, role):
    project_id, package_id = await _seed_project(app_engine, member_sub=None)
    doc = await _seed_doc(app_engine, project_id, package_id)
    client = authed_client(frozenset({role}))
    assert (await client.post(f"/api/v1/tender-documents/{doc}/confirm")).status_code == 200


async def test_class_administration_is_managing_director_only(authed_client, app_engine):
    reader = authed_client(frozenset({Role.ESTIMATOR.value}))
    classes = (await reader.get("/api/v1/tender-classes")).json()
    assert [c["code"] for c in classes][:3] == ["drawing", "boq", "addendum"] and all(c["enabled"] for c in classes)

    for role in (Role.LEAD_ESTIMATOR.value, Role.BD_DIRECTOR.value, Role.PROCUREMENT_HEAD.value):
        denied = authed_client(frozenset({role}))
        assert (await denied.patch("/api/v1/tender-classes/other", json={"label": "Misc"})).status_code == 403
    md = authed_client(frozenset({Role.MANAGING_DIRECTOR.value}))
    ok = await md.patch("/api/v1/tender-classes/other", json={"label": "Miscellaneous", "enabled": True})
    assert ok.status_code == 200 and ok.json()["label"] == "Miscellaneous" and ok.json()["default_label"] == "Other"
    assert (await md.patch("/api/v1/tender-classes/nonsense", json={"label": "x"})).status_code == 404
    # Restore so the shared demo tenant is unchanged for other tests.
    await md.patch("/api/v1/tender-classes/other", json={"label": "Other"})


# ------------------------------------------------------------------ download / prefill / lists
async def test_download_redirects_for_accepted_documents_only(authed_client, app_engine):
    lead = authed_client(frozenset({Role.MANAGING_DIRECTOR.value}))
    project_id, package_id = await _seed_project(app_engine, member_sub=None)
    good = await _seed_doc(app_engine, project_id, package_id, name="ok.pdf")
    bad = await _seed_doc(app_engine, project_id, package_id, name="bad.pdf", safety="rejected_macro", status="rejected")

    resp = await lead.get(f"/api/v1/tender-documents/{good}/download", follow_redirects=False)
    assert resp.status_code == 302 and resp.headers["location"].startswith("https://s3.test/tender/")
    refused = await lead.get(f"/api/v1/tender-documents/{bad}/download", follow_redirects=False)
    assert refused.status_code == 409


async def test_boq_prefill_needs_a_confirmed_boq(authed_client, app_engine):
    md = authed_client(frozenset({Role.MANAGING_DIRECTOR.value}))
    project_id, package_id = await _seed_project(app_engine, member_sub=None)
    boq = await _seed_doc(app_engine, project_id, package_id, doc_class="boq", name="b.xlsx")
    assert (await md.get(f"/api/v1/tender-documents/{boq}/boq-prefill")).status_code == 409  # not confirmed yet
    spec = await _seed_doc(app_engine, project_id, package_id, doc_class="specification")
    assert (await md.get(f"/api/v1/tender-documents/{spec}/boq-prefill")).status_code == 409  # not a BOQ


async def test_register_lists_only_routed_register_documents_and_filters_by_class_and_search(authed_client, app_engine):
    md = authed_client(frozenset({Role.MANAGING_DIRECTOR.value}))
    project_id, package_id = await _seed_project(app_engine, member_sub=None)
    spec = await _seed_doc(app_engine, project_id, package_id, doc_class="specification", name="Concrete_Spec.pdf")
    contract = await _seed_doc(app_engine, project_id, package_id, doc_class="contract", name="Conditions.pdf")
    for d in (spec, contract):
        assert (await md.post(f"/api/v1/tender-documents/{d}/confirm")).status_code == 200
    await _seed_doc(app_engine, project_id, package_id, doc_class="specification", name="Unconfirmed.pdf")

    reg = (await md.get(f"/api/v1/projects/{project_id}/document-register")).json()
    assert reg["total"] == 2
    only_contract = (await md.get(f"/api/v1/projects/{project_id}/document-register", params={"doc_class": "contract"})).json()
    assert [i["original_filename"] for i in only_contract["items"]] == ["Conditions.pdf"]
    found = (await md.get(f"/api/v1/projects/{project_id}/document-register", params={"q": "concrete"})).json()
    assert [i["original_filename"] for i in found["items"]] == ["Concrete_Spec.pdf"]
    assert (await md.get(f"/api/v1/projects/{project_id}/tender-documents", params={"limit": 1000})).status_code == 422


async def test_content_endpoint_streams_accepted_documents_same_origin(authed_client, app_engine, monkeypatch):
    from app.services import tender_intake as svc

    async def fake_get(object_key, *args, bucket=None, **kwargs):
        return b"workbook-bytes"

    monkeypatch.setattr(svc, "get_object_bytes", fake_get)
    md = authed_client(frozenset({Role.MANAGING_DIRECTOR.value}))
    project_id, package_id = await _seed_project(app_engine, member_sub=None)
    good = await _seed_doc(app_engine, project_id, package_id, name="b.xlsx")
    bad = await _seed_doc(app_engine, project_id, package_id, name="m.xlsm", safety="rejected_macro", status="rejected")

    resp = await md.get(f"/api/v1/tender-documents/{good}/content")
    assert resp.status_code == 200 and resp.content == b"workbook-bytes"
    assert 'filename="b.xlsx"' in resp.headers["content-disposition"]
    assert (await md.get(f"/api/v1/tender-documents/{bad}/content")).status_code == 409
    outsider = authed_client(frozenset({Role.ESTIMATOR.value}))
    assert (await outsider.get(f"/api/v1/tender-documents/{good}/content")).status_code == 404
