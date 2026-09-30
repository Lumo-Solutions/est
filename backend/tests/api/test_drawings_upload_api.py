"""POST /projects/{id}/drawings with DWG in the mix: accepted types, content
sniffing over file names, clean 4xx (never 500) for unusable files, and the
original/derived download variants."""

from __future__ import annotations

import hashlib

import pytest

from app.core.enums import Role
from tests.fixtures.dwg_fake_converter import fixture_bytes, require_fixtures

pytestmark = pytest.mark.asyncio


@pytest.fixture
def fake_s3(monkeypatch):
    from app.services import takeoff as takeoff_service

    store: dict[str, bytes] = {}

    async def put(object_key, data, content_type, *a, **kw):
        store[object_key] = data
        return hashlib.sha256(data).hexdigest()

    async def presign(object_key, *a, **kw):
        return f"https://s3.test/{object_key}"

    monkeypatch.setattr(takeoff_service, "put_object_streaming", put)
    monkeypatch.setattr(takeoff_service, "presign_get_url", presign)
    return store


async def _project(authed_client, code: str) -> tuple:
    md = authed_client(frozenset({Role.MANAGING_DIRECTOR.value}))
    project_id = (await md.post("/api/v1/projects", json={"code": code, "name": code})).json()["id"]
    return md, project_id


def _upload(md, project_id, name, data, content_type):
    return md.post(f"/api/v1/projects/{project_id}/drawings", files={"file": (name, data, content_type)})


async def test_dwg_upload_is_accepted_and_stored_as_the_original(authed_client, fake_s3):
    require_fixtures()
    md, project_id = await _project(authed_client, "DWGAPI-1")
    data = fixture_bytes("civil_site.dwg")
    resp = await _upload(md, project_id, "Site.dwg", data, "application/octet-stream")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert (body["kind"], body["status"], body["converted_from_dwg"]) == ("dwg", "uploaded", False)
    assert body["derived_size_bytes"] is None and body["conversion_reason"] is None
    assert fake_s3[f"projects/{project_id}/drawings/Site.dwg"] == data


async def test_a_dwg_named_file_that_is_really_a_pdf_is_a_pdf(authed_client, fake_s3):
    from app.intake.sample_pack import _vector_pdf

    md, project_id = await _project(authed_client, "DWGAPI-2")
    resp = await _upload(md, project_id, "Site.dwg", _vector_pdf("C-1", "A", "T", "A1"), "application/acad")
    assert resp.status_code == 201
    assert (resp.json()["kind"], resp.json()["content_type"]) == ("vector_pdf", "application/pdf")


async def test_a_dot_dwg_with_no_dwg_content_is_a_422_with_a_clear_reason(authed_client, fake_s3):
    md, project_id = await _project(authed_client, "DWGAPI-3")
    resp = await _upload(md, project_id, "notes.dwg", b"not a drawing at all", "application/octet-stream")
    assert resp.status_code == 422
    assert "not a valid DWG" in resp.json()["detail"]
    assert fake_s3 == {}


async def test_an_unsupported_type_says_what_is_accepted(authed_client, fake_s3):
    md, project_id = await _project(authed_client, "DWGAPI-4")
    resp = await _upload(md, project_id, "sheet.xlsx", b"PK\x03\x04", "application/vnd.ms-excel")
    assert resp.status_code == 422
    assert "PDF (vector), DXF or DWG" in resp.json()["detail"]


async def test_download_variants_original_redirects_derived_404s_until_converted(authed_client, fake_s3):
    require_fixtures()
    md, project_id = await _project(authed_client, "DWGAPI-5")
    drawing_id = (await _upload(md, project_id, "Site.dwg", fixture_bytes("civil_site.dwg"), "application/acad")).json()["id"]

    original = await md.get(f"/api/v1/drawings/{drawing_id}/download", follow_redirects=False)
    assert original.status_code == 307 and original.headers["location"].endswith("/Site.dwg")
    derived = await md.get(f"/api/v1/drawings/{drawing_id}/download?variant=derived", follow_redirects=False)
    assert derived.status_code == 404
    bad = await md.get(f"/api/v1/drawings/{drawing_id}/download?variant=zip", follow_redirects=False)
    assert bad.status_code == 422
