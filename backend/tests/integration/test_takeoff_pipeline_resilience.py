"""Drawing pipeline resilience (fix/drawing-pipeline-resilience): a failing
chord member must never leave a drawing stuck in `extracting` forever.

index_sheets builds chord(group(extract_sheet x N, embed_drawing,
extract_geometry_measurements), finalize_drawing). Before this fix, any one
of those group members permanently failing (retries exhausted) meant
finalize_drawing -- the only place that ever sets ready/partial/failed --
was simply never invoked by Celery, and nothing surfaced a reason either.
See the module docstring on app/workers/tasks/takeoff.py and
docs/takeoff-pipeline.md.

These tests exercise the two pieces directly, following
test_takeoff_scale_and_pdf_geometry.py's pattern (raw-seeded tenant/project,
set_rls_context, call the pipeline's own async `_*_body` functions with a
real session) rather than going through Celery/the broker:

1. aggregate_drawing_status() (shared by finalize_drawing and the sweeper)
   via _finalize_drawing_body, for the three status outcomes the brief asks
   for: one optional step (embed) fails -> partial; one of several
   per-sheet steps fails -> partial; every content step fails -> failed.
2. maintenance.py's reap_stuck_drawings sweeper actually rescuing a drawing
   whose pipeline stalled with no exception ever raised (e.g. a worker
   crash) -- the case aggregate_drawing_status alone can't cover, since
   finalize_drawing is never even scheduled in that scenario.
3. The outer Celery task wrapper (extract_sheet/embed_drawing/
   extract_geometry_measurements) swallowing a genuinely terminal failure
   so it never becomes a Celery-level task failure (which would silently
   drop finalize_drawing's chord callback), while still letting an
   in-progress celery.exceptions.Retry propagate untouched.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import RequestContext
from app.core.enums import DrawingStatus, ExtractionJobStatus, ExtractionJobType
from app.db.rls import set_rls_context
from app.models.takeoff import Drawing, DrawingSheet, ExtractionJob

# app.workers.tasks.* (not app.models.takeoff/app.services.takeoff, which are
# plain modules) import app.workers.celery_app, which calls get_settings()
# eagerly at module import time -- importing it here at collection time (as
# with the other tests/integration modules that reach into
# app.workers.tasks.*, e.g. test_procurement_dispatch.py) would run before
# tests/conftest.py's fixtures have set APP_DATABASE_URL etc. from the
# testcontainers it starts. Imported locally inside each test instead.

# No module-level `pytestmark = pytest.mark.asyncio` here (unlike most of
# this directory's other test modules) -- pyproject.toml's asyncio_mode =
# "auto" already picks up every `async def test_*` below without it, and
# this file also has two deliberately-sync tests (extract_sheet calls
# asyncio.run() itself, which can't nest inside a running event loop) that
# an explicit module-wide marker would otherwise warn on.


def _ctx(*, tenant_id: uuid.UUID, is_system: bool = True) -> RequestContext:
    user_id = uuid.uuid4()
    return RequestContext(
        tenant_id=tenant_id, user_id=user_id, sub=str(user_id), roles=frozenset(), is_system=is_system
    )


async def _seed_project(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    """Same shape as test_takeoff_scale_and_pdf_geometry.py's own helper."""
    tenant_id = uuid.uuid4()
    await session.execute(
        text("INSERT INTO tenants (id, slug, name) VALUES (:id, :slug, :name)"),
        {"id": str(tenant_id), "slug": f"pipe-{uuid.uuid4().hex[:8]}", "name": "Pipeline Co"},
    )
    await set_rls_context(session, _ctx(tenant_id=tenant_id, is_system=True))
    project_id = (
        await session.execute(
            text("INSERT INTO projects (tenant_id, code, name) VALUES (:t, :c, 'P') RETURNING id"),
            {"t": str(tenant_id), "c": f"PIPE-{uuid.uuid4().hex[:8]}"},
        )
    ).scalar_one()
    return tenant_id, project_id


async def _seed_drawing(
    session: AsyncSession, tenant_id: uuid.UUID, project_id: uuid.UUID, *, sheet_count: int = 1
) -> tuple[Drawing, list[DrawingSheet]]:
    drawing = Drawing(
        tenant_id=tenant_id, project_id=project_id, original_filename="tender.pdf", kind="vector_pdf",
        bucket="installtec-drawings", object_key="x", size_bytes=1, sha256=uuid.uuid4().hex.ljust(64, "0"),
        status=DrawingStatus.EXTRACTING.value, sheet_count=sheet_count,
    )
    session.add(drawing)
    await session.flush()
    sheets = []
    for i in range(sheet_count):
        sheet = DrawingSheet(
            tenant_id=tenant_id, drawing_id=drawing.id, project_id=project_id, sheet_index=i,
            source_name=f"page-{i + 1}", units="pt", is_raster=False,
        )
        session.add(sheet)
        sheets.append(sheet)
    await session.flush()
    return drawing, sheets


def _job(
    *, tenant_id: uuid.UUID, project_id: uuid.UUID, drawing_id: uuid.UUID, sheet_id: uuid.UUID | None,
    job_type: str, status: str, error: str | None = None,
) -> ExtractionJob:
    return ExtractionJob(
        tenant_id=tenant_id, project_id=project_id, drawing_id=drawing_id, sheet_id=sheet_id, job_type=job_type,
        status=status, error=error, started_at=datetime.now(timezone.utc), finished_at=datetime.now(timezone.utc),
    )


# --------------------------------------------------------------------------
# aggregate_drawing_status / finalize_drawing: the three outcomes
# --------------------------------------------------------------------------


async def test_embed_drawing_failure_makes_drawing_partial_not_stuck(rls_session):
    from app.workers.tasks import takeoff as takeoff_tasks

    tenant_id, project_id = await _seed_project(rls_session)
    drawing, sheets = await _seed_drawing(rls_session, tenant_id, project_id, sheet_count=1)
    rls_session.add_all(
        [
            _job(
                tenant_id=tenant_id, project_id=project_id, drawing_id=drawing.id, sheet_id=None,
                job_type=ExtractionJobType.INDEX_SHEETS.value, status=ExtractionJobStatus.SUCCEEDED.value,
            ),
            _job(
                tenant_id=tenant_id, project_id=project_id, drawing_id=drawing.id, sheet_id=sheets[0].id,
                job_type=ExtractionJobType.EXTRACT_TITLE_BLOCK.value, status=ExtractionJobStatus.SUCCEEDED.value,
            ),
            _job(
                tenant_id=tenant_id, project_id=project_id, drawing_id=drawing.id, sheet_id=None,
                job_type=ExtractionJobType.EMBED_SHEET.value, status=ExtractionJobStatus.FAILED.value,
                error="no ONNX embedding model provisioned",
            ),
        ]
    )
    await rls_session.flush()

    await takeoff_tasks._finalize_drawing_body(rls_session, str(drawing.id), "task-1")

    assert drawing.status == DrawingStatus.PARTIAL.value
    assert drawing.error_message is not None
    assert "embed_sheet" in drawing.error_message
    assert "no ONNX embedding model provisioned" in drawing.error_message


async def test_one_sheet_extraction_failure_makes_drawing_partial(rls_session):
    from app.workers.tasks import takeoff as takeoff_tasks

    tenant_id, project_id = await _seed_project(rls_session)
    drawing, sheets = await _seed_drawing(rls_session, tenant_id, project_id, sheet_count=2)
    rls_session.add_all(
        [
            _job(
                tenant_id=tenant_id, project_id=project_id, drawing_id=drawing.id, sheet_id=None,
                job_type=ExtractionJobType.INDEX_SHEETS.value, status=ExtractionJobStatus.SUCCEEDED.value,
            ),
            _job(
                tenant_id=tenant_id, project_id=project_id, drawing_id=drawing.id, sheet_id=sheets[0].id,
                job_type=ExtractionJobType.EXTRACT_TITLE_BLOCK.value, status=ExtractionJobStatus.SUCCEEDED.value,
            ),
            _job(
                tenant_id=tenant_id, project_id=project_id, drawing_id=drawing.id, sheet_id=sheets[1].id,
                job_type=ExtractionJobType.EXTRACT_TITLE_BLOCK.value, status=ExtractionJobStatus.FAILED.value,
                error="VLM timed out",
            ),
            _job(
                tenant_id=tenant_id, project_id=project_id, drawing_id=drawing.id, sheet_id=None,
                job_type=ExtractionJobType.EMBED_SHEET.value, status=ExtractionJobStatus.SUCCEEDED.value,
            ),
        ]
    )
    await rls_session.flush()

    await takeoff_tasks._finalize_drawing_body(rls_session, str(drawing.id), "task-1")

    assert drawing.status == DrawingStatus.PARTIAL.value
    assert drawing.error_message is not None
    assert str(sheets[1].id) in drawing.error_message
    assert "VLM timed out" in drawing.error_message


async def test_every_content_job_failing_makes_drawing_failed_not_partial(rls_session):
    """index_sheets itself succeeded (it must have, for this chord to exist
    at all), but every real extraction step failed -- must read as `failed`,
    not `partial` just because the prerequisite indexing step nominally
    succeeded (see aggregate_drawing_status's docstring)."""
    from app.workers.tasks import takeoff as takeoff_tasks

    tenant_id, project_id = await _seed_project(rls_session)
    drawing, sheets = await _seed_drawing(rls_session, tenant_id, project_id, sheet_count=1)
    rls_session.add_all(
        [
            _job(
                tenant_id=tenant_id, project_id=project_id, drawing_id=drawing.id, sheet_id=None,
                job_type=ExtractionJobType.INDEX_SHEETS.value, status=ExtractionJobStatus.SUCCEEDED.value,
            ),
            _job(
                tenant_id=tenant_id, project_id=project_id, drawing_id=drawing.id, sheet_id=sheets[0].id,
                job_type=ExtractionJobType.EXTRACT_TITLE_BLOCK.value, status=ExtractionJobStatus.FAILED.value,
                error="VLM unreachable",
            ),
            _job(
                tenant_id=tenant_id, project_id=project_id, drawing_id=drawing.id, sheet_id=None,
                job_type=ExtractionJobType.EMBED_SHEET.value, status=ExtractionJobStatus.FAILED.value,
                error="no embedding model",
            ),
        ]
    )
    await rls_session.flush()

    await takeoff_tasks._finalize_drawing_body(rls_session, str(drawing.id), "task-1")

    assert drawing.status == DrawingStatus.FAILED.value
    assert drawing.error_message is not None
    assert "VLM unreachable" in drawing.error_message
    assert "no embedding model" in drawing.error_message


async def test_finalize_reruns_and_updates_status_on_a_retry_not_frozen_at_first_result(rls_session):
    """Found live: 'Retry extraction' (POST /drawings/{id}/ingest again)
    always re-dispatches a fresh finalize_drawing as part of its new
    chord, same as every other task -- but _upsert_job's own idempotent-
    replay guard ("a prior attempt already succeeded -> skip") meant that
    once finalize_drawing succeeded ONCE, every later invocation silently
    no-opped forever, freezing drawing.status/error_message at whatever
    they were after the FIRST finalize -- even though the jobs it's
    supposed to summarize had genuinely changed on the retry (e.g. a
    previously-failed embed_sheet now succeeding). Unlike extract_sheet/
    embed_drawing/etc., finalize_drawing doesn't DO idempotent work of its
    own -- it only reads and reflects the CURRENT state of every other
    job -- so it must always re-run, never skip. Fixed via _upsert_job's
    new `force` param, used only by finalize_drawing."""
    from app.workers.tasks import takeoff as takeoff_tasks

    tenant_id, project_id = await _seed_project(rls_session)
    drawing, sheets = await _seed_drawing(rls_session, tenant_id, project_id, sheet_count=1)
    embed_job = _job(
        tenant_id=tenant_id, project_id=project_id, drawing_id=drawing.id, sheet_id=None,
        job_type=ExtractionJobType.EMBED_SHEET.value, status=ExtractionJobStatus.FAILED.value, error="no embedding model",
    )
    rls_session.add_all(
        [
            _job(
                tenant_id=tenant_id, project_id=project_id, drawing_id=drawing.id, sheet_id=None,
                job_type=ExtractionJobType.INDEX_SHEETS.value, status=ExtractionJobStatus.SUCCEEDED.value,
            ),
            _job(
                tenant_id=tenant_id, project_id=project_id, drawing_id=drawing.id, sheet_id=sheets[0].id,
                job_type=ExtractionJobType.EXTRACT_TITLE_BLOCK.value, status=ExtractionJobStatus.SUCCEEDED.value,
            ),
            embed_job,
        ]
    )
    await rls_session.flush()

    await takeoff_tasks._finalize_drawing_body(rls_session, str(drawing.id), "task-1")
    assert drawing.status == DrawingStatus.PARTIAL.value
    assert drawing.error_message is not None and "no embedding model" in drawing.error_message

    # The retry: embed_sheet now genuinely succeeds (its own job row
    # updated in place, exactly as _record_extraction_failure/_finish_job
    # would for a real retry).
    embed_job.status = ExtractionJobStatus.SUCCEEDED.value
    embed_job.error = None
    await rls_session.flush()

    await takeoff_tasks._finalize_drawing_body(rls_session, str(drawing.id), "task-2")

    assert drawing.status == DrawingStatus.READY.value  # not still frozen at `partial`
    assert drawing.error_message is None


# --------------------------------------------------------------------------
# the stale-drawing sweeper: rescues a drawing the chord never resolved
# --------------------------------------------------------------------------


async def test_reap_stuck_drawings_rescues_a_stalled_drawing(rls_session, monkeypatch):
    """Simulates a worker crash mid-pipeline: no exception was ever raised
    (so finalize_drawing was never even scheduled), the drawing is just
    sitting in `extracting` with a `running` job row and a stale
    updated_at. reap_stuck_drawings must resolve it anyway."""
    from types import SimpleNamespace

    from app.workers.tasks import maintenance as maintenance_tasks

    monkeypatch.setattr(
        maintenance_tasks, "get_settings", lambda: SimpleNamespace(drawing_stuck_timeout_s=3600)
    )
    tenant_id, project_id = await _seed_project(rls_session)
    drawing, sheets = await _seed_drawing(rls_session, tenant_id, project_id, sheet_count=1)
    running_job = _job(
        tenant_id=tenant_id, project_id=project_id, drawing_id=drawing.id, sheet_id=sheets[0].id,
        job_type=ExtractionJobType.EXTRACT_TITLE_BLOCK.value, status=ExtractionJobStatus.RUNNING.value,
    )
    rls_session.add_all(
        [
            _job(
                tenant_id=tenant_id, project_id=project_id, drawing_id=drawing.id, sheet_id=None,
                job_type=ExtractionJobType.INDEX_SHEETS.value, status=ExtractionJobStatus.SUCCEEDED.value,
            ),
            running_job,
        ]
    )
    await rls_session.flush()
    # Backdate past the (mocked) 1h timeout -- onupdate=func.now() only
    # fires when a flush doesn't already carry an explicit value for the
    # column, so this explicit assignment sticks.
    drawing.updated_at = datetime.now(timezone.utc) - timedelta(hours=2)
    await rls_session.flush()

    # A second, genuinely-still-running drawing (not past the timeout) must
    # be left alone -- only the stale one should be touched.
    fresh_drawing, _ = await _seed_drawing(rls_session, tenant_id, project_id, sheet_count=1)

    # _reap_stuck_drawings_body updates extraction_jobs via a raw UPDATE
    # (Core SQL, not the ORM), then re-SELECTs via the ORM to aggregate the
    # result. In production nothing else in that fresh worker session would
    # have already loaded those rows, so the re-SELECT reads them fresh; in
    # this test `running_job` above is already identity-mapped in
    # rls_session from seeding it, so without this the re-SELECT would
    # return that same (now stale, pre-update) cached instance instead of
    # reading the row the raw UPDATE just changed. expire_all() forces the
    # next read of every object to go back to the DB, matching what a truly
    # fresh session -- as production always is here -- would see anyway.
    rls_session.expire_all()

    rescued = await maintenance_tasks._reap_stuck_drawings_body(rls_session, str(tenant_id))

    assert rescued == 1
    assert drawing.status == DrawingStatus.FAILED.value  # nothing but indexing ever succeeded
    assert drawing.error_message is not None
    assert "stale-drawing sweeper" in drawing.error_message
    await rls_session.refresh(running_job)
    assert running_job.status == ExtractionJobStatus.FAILED.value
    assert running_job.error == "stale: exceeded timeout"
    # fresh_drawing didn't match the sweeper's stuck-drawing query at all, so
    # (unlike `drawing` above) nothing re-populated it after expire_all() --
    # an explicit refresh is needed before reading it, same as running_job.
    await rls_session.refresh(fresh_drawing)
    assert fresh_drawing.status == DrawingStatus.EXTRACTING.value  # untouched


async def test_reap_stuck_drawings_rescued_to_ready_gets_no_stale_error_message(rls_session, monkeypatch):
    """Found live against real, long-stuck drawings (GEO-TEST/WALK-1, see
    docs/ui-qa-report.md): their embed_sheet task had never even reached its
    own _upsert_job call (no extraction_jobs row for it at all -- a lost
    broker message, not a recorded failure), so every job that DOES have a
    row succeeded and aggregate_drawing_status correctly resolves them to
    `ready`. The sweeper must not then stamp a "stalled" error_message onto
    an otherwise-ready drawing -- a real bug, fixed here: it unconditionally
    built a stall note before this fix, regardless of the aggregated
    status."""
    from types import SimpleNamespace

    from app.workers.tasks import maintenance as maintenance_tasks

    monkeypatch.setattr(
        maintenance_tasks, "get_settings", lambda: SimpleNamespace(drawing_stuck_timeout_s=3600)
    )
    tenant_id, project_id = await _seed_project(rls_session)
    drawing, sheets = await _seed_drawing(rls_session, tenant_id, project_id, sheet_count=1)
    rls_session.add_all(
        [
            _job(
                tenant_id=tenant_id, project_id=project_id, drawing_id=drawing.id, sheet_id=None,
                job_type=ExtractionJobType.INDEX_SHEETS.value, status=ExtractionJobStatus.SUCCEEDED.value,
            ),
            _job(
                tenant_id=tenant_id, project_id=project_id, drawing_id=drawing.id, sheet_id=sheets[0].id,
                job_type=ExtractionJobType.EXTRACT_TITLE_BLOCK.value, status=ExtractionJobStatus.SUCCEEDED.value,
            ),
            # No embed_sheet row at all -- that task's message was lost
            # before it ever ran, not before it recorded a failure.
        ]
    )
    await rls_session.flush()
    drawing.updated_at = datetime.now(timezone.utc) - timedelta(hours=2)
    await rls_session.flush()
    rls_session.expire_all()

    rescued = await maintenance_tasks._reap_stuck_drawings_body(rls_session, str(tenant_id))

    assert rescued == 1
    assert drawing.status == DrawingStatus.READY.value
    assert drawing.error_message is None


# --------------------------------------------------------------------------
# the outer task wrapper: terminal failure swallowed, in-progress retry not
# --------------------------------------------------------------------------


def test_extract_sheet_task_swallows_a_terminal_failure(monkeypatch, postgres_container):
    """A terminal (post-retry) failure inside the task body must not
    surface as a Celery-level task failure, or index_sheets' chord callback
    (finalize_drawing) is silently never invoked at all (the bug this whole
    fix addresses). Deliberately a plain (non-async) test: extract_sheet
    calls asyncio.run() internally (run_async), which raises if called from
    inside an already-running event loop -- this must run outside one, same
    as a real Celery worker invoking it. Takes the (unused) postgres_container
    fixture only to guarantee APP_DATABASE_URL/etc. are set in os.environ
    before the local `app.workers.tasks.takeoff` import below triggers
    app.workers.celery_app's module-level get_settings() -- no DB is
    actually touched by this test."""
    from app.workers.tasks import takeoff as takeoff_tasks

    async def _boom(*_args: object, **_kwargs: object) -> None:
        raise ValueError("permanently failed after retries")

    monkeypatch.setattr(takeoff_tasks, "with_worker_session", lambda *a, **k: _boom())

    # Must not raise -- the outer wrapper swallows it.
    takeoff_tasks.extract_sheet(str(uuid.uuid4()), str(uuid.uuid4()))


def test_extract_sheet_task_still_lets_an_in_progress_retry_through(monkeypatch, postgres_container):
    """A genuine Celery retry-in-progress (autoretry_for's own Retry signal)
    must keep propagating -- swallowing THAT would break retry scheduling.
    See the previous test for why postgres_container is taken but unused."""
    from celery.exceptions import Retry

    from app.workers.tasks import takeoff as takeoff_tasks

    async def _retrying(*_args: object, **_kwargs: object) -> None:
        raise Retry("still retrying")

    monkeypatch.setattr(takeoff_tasks, "with_worker_session", lambda *a, **k: _retrying())

    with pytest.raises(Retry):
        takeoff_tasks.extract_sheet(str(uuid.uuid4()), str(uuid.uuid4()))


# --------------------------------------------------------------------------
# _record_extraction_failure: the failure record must survive its own
# session's rollback (the bug that motivated it, found live -- see
# app/workers/tasks/takeoff.py's module docstring)
# --------------------------------------------------------------------------


async def test_extract_sheet_failure_is_durably_recorded_across_the_rollback(app_engine, monkeypatch):
    """rls_session's single, test-scoped, never-committed transaction can't
    exercise this: _record_extraction_failure's whole point is to commit
    through a SECOND, genuinely independent connection/transaction, which
    can only be observed once the first transaction's own writes are
    actually committed and visible to it. So this test uses real committed
    sessions (worker_session_scope, exactly as production does) instead of
    the rls_session fixture, and cleans up its own rows explicitly at the
    end rather than relying on a rollback."""
    from app.core.context import system_context
    from app.db.session import worker_session_scope
    from app.workers.tasks import takeoff as takeoff_tasks

    tenant_id = uuid.uuid4()
    ctx = system_context(tenant_id)

    async with worker_session_scope(ctx) as session:
        await session.execute(
            text("INSERT INTO tenants (id, slug, name) VALUES (:id, :slug, :name)"),
            {"id": str(tenant_id), "slug": f"resfail-{uuid.uuid4().hex[:8]}", "name": "Resilience Failure Test"},
        )
        project_id = (
            await session.execute(
                text("INSERT INTO projects (tenant_id, code, name) VALUES (:t, :c, 'P') RETURNING id"),
                {"t": str(tenant_id), "c": f"RESFAIL-{uuid.uuid4().hex[:8]}"},
            )
        ).scalar_one()
        drawing = Drawing(
            tenant_id=tenant_id, project_id=project_id, original_filename="x.pdf", kind="vector_pdf",
            bucket="installtec-drawings", object_key="x", size_bytes=1, sha256=uuid.uuid4().hex.ljust(64, "0"),
            status=DrawingStatus.EXTRACTING.value,
        )
        session.add(drawing)
        await session.flush()
        sheet = DrawingSheet(
            tenant_id=tenant_id, drawing_id=drawing.id, project_id=project_id, sheet_index=0,
            source_name="page-1", units="pt", is_raster=False,
            # Non-empty raw_text -- _extract_sheet_body only reaches for the
            # object in S3 (get_object_bytes) when is_raster or raw_text is
            # blank; this test wants the failure to come from the
            # monkeypatched extract_title_block, not an unrelated S3/
            # credentials error from a step this test never intends to
            # reach at all (confirmed live: without this, it fails on
            # botocore.exceptions.NoCredentialsError instead).
            raw_text="some extracted text",
        )
        session.add(sheet)
        await session.flush()
        drawing_id, sheet_id = drawing.id, sheet.id

    async def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("simulated title-block extraction failure")

    monkeypatch.setattr(takeoff_tasks, "extract_title_block", _boom)

    try:
        with pytest.raises(RuntimeError, match="simulated title-block extraction failure"):
            await takeoff_tasks.with_worker_session(ctx, takeoff_tasks._extract_sheet_body, str(sheet_id), "task-durability-test")

        # A FRESH session/connection (worker_session_scope again, not the
        # one above, which is long since closed) -- this is exactly what
        # finalize_drawing/the sweeper/the frontend all read afterward.
        async with worker_session_scope(ctx) as verify_session:
            job = (
                await verify_session.execute(
                    select(ExtractionJob).where(
                        ExtractionJob.drawing_id == drawing_id, ExtractionJob.job_type == ExtractionJobType.EXTRACT_TITLE_BLOCK.value
                    )
                )
            ).scalar_one()
            assert job.status == ExtractionJobStatus.FAILED.value
            assert job.error is not None and "simulated title-block extraction failure" in job.error
            refreshed_sheet = (
                await verify_session.execute(select(DrawingSheet).where(DrawingSheet.id == sheet_id))
            ).scalar_one()
            assert refreshed_sheet.extraction_status == "failed"
    finally:
        async with worker_session_scope(ctx) as cleanup_session:
            await cleanup_session.execute(text("DELETE FROM extraction_jobs WHERE drawing_id = :d"), {"d": str(drawing_id)})
            await cleanup_session.execute(text("DELETE FROM drawing_sheets WHERE drawing_id = :d"), {"d": str(drawing_id)})
            await cleanup_session.execute(text("DELETE FROM drawings WHERE id = :d"), {"d": str(drawing_id)})
            await cleanup_session.execute(text("DELETE FROM projects WHERE tenant_id = :t"), {"t": str(tenant_id)})
            await cleanup_session.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": str(tenant_id)})
