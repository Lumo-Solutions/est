"""DWG conversion end to end against a real Postgres (RLS on), with the converter
container replaced by a fake spool loop that replays what the REAL converter
produced for our fixtures (see tests/fixtures/dwg_fake_converter.py).

Covers: upload sniffing, hand-off to the `convert` queue, the derived-DXF link
(sha256/version/target), the normal DXF pipeline running on the converted file
with the same measurements as the original DXF, and every failure going to
`needs_conversion` with a reason -- never stuck, never a 500.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import select, text

from app.core.context import RequestContext
from app.core.enums import DrawingStatus
from app.core.errors import ValidationAppError
from app.db.rls import set_rls_context
from app.integrations import dwg_converter as client
from app.models.takeoff import Drawing, DrawingMeasurement
from app.services import takeoff as takeoff_service
from tests.fixtures.dwg_fake_converter import FakeConverter, fixture_bytes, make_settings, require_fixtures
from tests.fixtures.dwg_sources import SOURCES

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _need_fixtures():
    require_fixtures()


def _ctx(tenant_id: uuid.UUID) -> RequestContext:
    return RequestContext(tenant_id=tenant_id, user_id=None, sub=None, roles=frozenset(), is_system=True)


async def _seed_project(session) -> tuple[uuid.UUID, uuid.UUID]:
    tenant_id = uuid.uuid4()
    await session.execute(
        text("INSERT INTO tenants (id, slug, name) VALUES (:id, :slug, 'DWG Co')"),
        {"id": str(tenant_id), "slug": f"dwg-{uuid.uuid4().hex[:8]}"},
    )
    await set_rls_context(session, _ctx(tenant_id))
    project_id = (
        await session.execute(
            text("INSERT INTO projects (tenant_id, code, name) VALUES (:t, :c, 'P') RETURNING id"),
            {"t": str(tenant_id), "c": f"DWG-{uuid.uuid4().hex[:8]}"},
        )
    ).scalar_one()
    return tenant_id, project_id


@pytest.fixture
def env(monkeypatch, tmp_path, postgres_container):
    """Fake S3 (drawings bucket) + settings pointing the client at tmp_path.

    app.workers.tasks.* call get_settings() at import (via celery_app), so they
    are imported here, after postgres_container has set the DB env vars, never
    at collection time."""
    from app.workers.tasks import dwg as dwg_tasks
    from app.workers.tasks import maintenance as maintenance_tasks
    from app.workers.tasks import takeoff as takeoff_tasks

    store: dict[str, bytes] = {}
    state = SimpleNamespace(
        store=store, settings=make_settings(tmp_path, TAKEOFF_PERSIST_GEOMETRY="true"), spool=tmp_path,
        dwg_tasks=dwg_tasks, takeoff_tasks=takeoff_tasks, maintenance_tasks=maintenance_tasks,
    )

    async def put(object_key, data, content_type, *a, **kw):
        store[object_key] = data
        return hashlib.sha256(data).hexdigest()

    async def get(object_key, *a, **kw):
        return store[object_key]

    async def presign(object_key, *a, **kw):
        return f"https://s3.test/{object_key}"

    monkeypatch.setattr(takeoff_service, "put_object_streaming", put)
    monkeypatch.setattr(takeoff_service, "presign_get_url", presign)
    monkeypatch.setattr(dwg_tasks, "put_object_streaming", put)
    monkeypatch.setattr(dwg_tasks, "get_object_bytes", get)
    monkeypatch.setattr(takeoff_tasks, "get_object_bytes", get)
    for module in (client, takeoff_service, takeoff_tasks, maintenance_tasks):
        monkeypatch.setattr(module, "get_settings", lambda: state.settings)
    return state


async def _upload(session, tenant_id, project_id, filename, data, content_type=None) -> Drawing:
    return await takeoff_service.upload_drawing(session, _ctx(tenant_id), project_id, filename, content_type, data)


async def _convert(env, session, tenant_id, drawing) -> bool:
    return await env.dwg_tasks._convert_body(session, _ctx(tenant_id), str(drawing.id))


# ------------------------------------------------------------------ upload / hand-off
async def test_a_dwg_upload_is_kept_as_the_original_and_ingest_goes_to_the_convert_queue(rls_session, env):
    tenant_id, project_id = await _seed_project(rls_session)
    data = fixture_bytes("civil_site.dwg")
    drawing = await _upload(rls_session, tenant_id, project_id, "Site.dwg", data, "application/octet-stream")

    assert (drawing.kind, drawing.content_type, drawing.status) == ("dwg", "application/acad", "uploaded")
    assert env.store[drawing.object_key] == data and drawing.sha256 == hashlib.sha256(data).hexdigest()
    assert drawing.derived_object_key is None and drawing.converted_from_dwg is False

    with patch("app.workers.tasks.dwg.convert_dwg.delay") as convert, patch("app.workers.tasks.takeoff.index_sheets.delay") as index:
        await takeoff_service.trigger_ingest(rls_session, _ctx(tenant_id), drawing.id)
    convert.assert_called_once()
    index.assert_not_called()
    assert convert.call_args.args[0] == str(drawing.id)
    assert drawing.status == DrawingStatus.QUEUED.value


async def test_a_dot_dwg_that_is_really_a_pdf_is_stored_and_ingested_as_a_pdf(rls_session, env):
    from app.intake.sample_pack import _vector_pdf

    tenant_id, project_id = await _seed_project(rls_session)
    drawing = await _upload(rls_session, tenant_id, project_id, "Mislabelled.dwg", _vector_pdf("C-1", "A", "T", "A1"), "application/acad")
    assert (drawing.kind, drawing.content_type) == ("vector_pdf", "application/pdf")
    with patch("app.workers.tasks.dwg.convert_dwg.delay") as convert, patch("app.workers.tasks.takeoff.index_sheets.delay") as index:
        await takeoff_service.trigger_ingest(rls_session, _ctx(tenant_id), drawing.id)
    convert.assert_not_called()
    index.assert_called_once()


async def test_a_dot_dwg_with_no_dwg_content_is_a_422_and_nothing_is_stored(rls_session, env):
    tenant_id, project_id = await _seed_project(rls_session)
    with pytest.raises(ValidationAppError, match="not a valid DWG"):
        await _upload(rls_session, tenant_id, project_id, "notes.dwg", b"just some text", "application/acad")
    assert env.store == {}
    assert (await rls_session.execute(select(Drawing))).scalars().all() == []


# ------------------------------------------------------------------ conversion
async def test_conversion_stores_the_derived_dxf_linked_to_the_original_with_version_and_sha(rls_session, env):
    tenant_id, project_id = await _seed_project(rls_session)
    dxf = fixture_bytes("civil_site.roundtrip.dxf")
    drawing = await _upload(rls_session, tenant_id, project_id, "Site.dwg", fixture_bytes("civil_site.dwg"))
    original_key = drawing.object_key

    with FakeConverter(env.spool, "ok", dxf) as conv:
        assert await _convert(env, rls_session, tenant_id, drawing) is True

    assert drawing.object_key == original_key and env.store[original_key] == fixture_bytes("civil_site.dwg")  # original kept
    assert drawing.derived_object_key == f"projects/{project_id}/drawings/derived/{drawing.sha256}.dxf"
    assert env.store[drawing.derived_object_key] == dxf
    assert drawing.derived_sha256 == hashlib.sha256(dxf).hexdigest() and drawing.derived_size_bytes == len(dxf)
    assert (drawing.converter_version, drawing.conversion_target) == ("27.9.0.0", "ACAD2018")
    assert drawing.converted_at is not None and drawing.conversion_ms is not None
    assert drawing.converted_from_dwg and drawing.error_message is None and drawing.conversion_reason is None
    assert conv.seen[0]["request"]["output_format"] == "DXF"

    events = (await rls_session.execute(text("SELECT payload FROM audit_events WHERE entity_type = 'drawing' AND payload->>'event' = 'dwg_converted'"))).all()
    assert len(events) == 1 and events[0][0]["derived_sha256"] == drawing.derived_sha256

    # both files downloadable
    original_url = await takeoff_service.presigned_download_url(rls_session, _ctx(tenant_id), drawing.id)
    derived_url = await takeoff_service.presigned_download_url(rls_session, _ctx(tenant_id), drawing.id, variant="derived")
    assert original_url.endswith(original_key) and derived_url.endswith(drawing.derived_object_key)


async def test_a_converted_dwg_is_measured_exactly_like_the_dxf_it_came_from(rls_session, env):
    """The whole point: DXF pipeline on the derived file == DXF pipeline on the original DXF."""
    tenant_id, project_id = await _seed_project(rls_session)
    original_dxf = SOURCES["civil_site"]()
    plain = await _upload(rls_session, tenant_id, project_id, "civil.dxf", original_dxf, "application/dxf")
    dwg = await _upload(rls_session, tenant_id, project_id, "civil.dwg", fixture_bytes("civil_site.dwg"))
    with FakeConverter(env.spool, "ok", fixture_bytes("civil_site.roundtrip.dxf")):
        assert await _convert(env, rls_session, tenant_id, dwg)

    async def measure(drawing: Drawing) -> list[tuple]:
        sheet_ids = await env.takeoff_tasks._index_sheets_body(rls_session, str(drawing.id), f"t-{drawing.id}")
        assert drawing.status == DrawingStatus.EXTRACTING.value and drawing.sheet_count == len(sheet_ids) >= 1
        for sheet in await takeoff_service.list_sheets(rls_session, drawing.id):
            await takeoff_service.recompute_sheet_measurements(rls_session, sheet)
        rows = (await rls_session.execute(select(DrawingMeasurement).where(DrawingMeasurement.drawing_id == drawing.id))).scalars().all()
        return sorted((m.capability, m.kind, round(float(m.value), 6)) for m in rows)

    from_dxf = await measure(plain)
    from_dwg = await measure(dwg)
    assert from_dxf, "the fixture must yield measurements or this proves nothing"
    assert {c for c, *_ in from_dxf} >= {"alignment", "corridor_area", "pipe_network_topology", "trench_prismoidal_volume"}
    assert len(from_dwg) == len(from_dxf)
    for (cap_a, kind_a, val_a), (cap_b, kind_b, val_b) in zip(from_dwg, from_dxf, strict=True):
        assert (cap_a, kind_a) == (cap_b, kind_b) and val_a == pytest.approx(val_b, rel=1e-6, abs=1e-6)


async def test_reingesting_an_already_converted_dwg_reuses_the_derived_dxf(rls_session, env):
    tenant_id, project_id = await _seed_project(rls_session)
    drawing = await _upload(rls_session, tenant_id, project_id, "Site.dwg", fixture_bytes("civil_site.dwg"))
    with FakeConverter(env.spool, "ok", fixture_bytes("civil_site.roundtrip.dxf")) as conv:
        assert await _convert(env, rls_session, tenant_id, drawing)
        assert await _convert(env, rls_session, tenant_id, drawing)
    assert len(conv.seen) == 1


# ------------------------------------------------------------------ failures -> needs_conversion
def _assert_parked(drawing: Drawing, reason: str) -> None:
    assert drawing.status == DrawingStatus.NEEDS_CONVERSION.value
    assert drawing.conversion_reason == reason
    assert drawing.error_message and client.MANUAL_WORKAROUND in drawing.error_message
    assert drawing.derived_object_key is None


async def test_a_corrupt_dwg_goes_to_needs_conversion_with_a_reason_and_the_workaround(rls_session, env):
    tenant_id, project_id = await _seed_project(rls_session)
    drawing = await _upload(rls_session, tenant_id, project_id, "Bad.dwg", fixture_bytes("corrupt.dwg"))
    with FakeConverter(env.spool, "fail"):
        assert await _convert(env, rls_session, tenant_id, drawing) is False
    _assert_parked(drawing, client.R_FAILED)
    assert "corrupt" in drawing.error_message

    # ...and the retry path is open (not a dead end): ingest queues it again.
    with patch("app.workers.tasks.dwg.convert_dwg.delay"):
        await takeoff_service.trigger_ingest(rls_session, _ctx(tenant_id), drawing.id)
    assert drawing.status == DrawingStatus.QUEUED.value and drawing.error_message is None


async def test_a_conversion_timeout_goes_to_needs_conversion(rls_session, env, monkeypatch):
    monkeypatch.setattr(client, "_GRACE_S", 0.3)
    env.settings = make_settings(env.spool, DWG_CONVERT_TIMEOUT_S=1)
    tenant_id, project_id = await _seed_project(rls_session)
    drawing = await _upload(rls_session, tenant_id, project_id, "Huge.dwg", fixture_bytes("civil_site.dwg"))
    with FakeConverter(env.spool, "hang"):
        assert await _convert(env, rls_session, tenant_id, drawing) is False
    _assert_parked(drawing, client.R_TIMEOUT)


async def test_the_converters_own_recorded_timeout_verdict_also_goes_to_needs_conversion(rls_session, env):
    tenant_id, project_id = await _seed_project(rls_session)
    drawing = await _upload(rls_session, tenant_id, project_id, "Huge.dwg", fixture_bytes("civil_site.dwg"))
    with FakeConverter(env.spool, "timeout"):
        assert await _convert(env, rls_session, tenant_id, drawing) is False
    _assert_parked(drawing, client.R_TIMEOUT)


async def test_a_missing_converter_goes_to_needs_conversion_not_a_crash(rls_session, env):
    tenant_id, project_id = await _seed_project(rls_session)
    drawing = await _upload(rls_session, tenant_id, project_id, "Site.dwg", fixture_bytes("civil_site.dwg"))
    assert await _convert(env, rls_session, tenant_id, drawing) is False  # no FakeConverter running: no heartbeat
    _assert_parked(drawing, client.R_UNAVAILABLE)
    assert "not installed or not running" in drawing.error_message


async def test_converter_without_oda_goes_to_needs_conversion_as_not_installed(rls_session, env):
    tenant_id, project_id = await _seed_project(rls_session)
    drawing = await _upload(rls_session, tenant_id, project_id, "Site.dwg", fixture_bytes("civil_site.dwg"))
    with FakeConverter(env.spool, "not_installed"):
        assert await _convert(env, rls_session, tenant_id, drawing) is False
    _assert_parked(drawing, client.R_NOT_INSTALLED)


async def test_an_unexpected_crash_mid_conversion_still_parks_the_drawing(rls_session, env, monkeypatch):
    tenant_id, project_id = await _seed_project(rls_session)
    drawing = await _upload(rls_session, tenant_id, project_id, "Site.dwg", fixture_bytes("civil_site.dwg"))

    async def boom(*a, **kw):
        raise RuntimeError("S3 is down")

    monkeypatch.setattr(env.dwg_tasks, "get_object_bytes", boom)
    with FakeConverter(env.spool, "ok", b"  0\nSECTION\n"):
        assert await _convert(env, rls_session, tenant_id, drawing) is False
    _assert_parked(drawing, client.R_FAILED)


async def test_the_feature_flag_off_parks_the_drawing_immediately_without_queueing(rls_session, env):
    env.settings = make_settings(env.spool, DWG_CONVERSION_ENABLED="false")
    tenant_id, project_id = await _seed_project(rls_session)
    drawing = await _upload(rls_session, tenant_id, project_id, "Site.dwg", fixture_bytes("civil_site.dwg"))
    with patch("app.workers.tasks.dwg.convert_dwg.delay") as convert, patch("app.workers.tasks.takeoff.index_sheets.delay") as index:
        job_ids = await takeoff_service.trigger_ingest(rls_session, _ctx(tenant_id), drawing.id)
    assert job_ids == [] and not convert.called and not index.called
    _assert_parked(drawing, client.R_DISABLED)
    assert "DWG_CONVERSION_ENABLED" in drawing.error_message


async def test_a_drawing_stuck_in_converting_or_queued_is_reaped_to_needs_conversion(rls_session, env):
    tenant_id, project_id = await _seed_project(rls_session)
    stuck = await _upload(rls_session, tenant_id, project_id, "Stuck.dwg", fixture_bytes("civil_site.dwg"))
    stuck.status = DrawingStatus.CONVERTING.value
    fresh = await _upload(rls_session, tenant_id, project_id, "Fresh.dwg", fixture_bytes("intake_sheet.dwg"))
    fresh.status = DrawingStatus.CONVERTING.value
    await rls_session.flush()
    stuck.updated_at = datetime.now(timezone.utc) - timedelta(hours=3)
    await rls_session.flush()

    reaped = await env.maintenance_tasks._reap_stuck_drawings_body(rls_session, str(tenant_id))
    assert reaped == 1
    assert stuck.status == DrawingStatus.NEEDS_CONVERSION.value and "stalled" in stuck.error_message
    assert fresh.status == DrawingStatus.CONVERTING.value
