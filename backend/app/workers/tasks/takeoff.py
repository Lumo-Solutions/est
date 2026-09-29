"""Module B ingestion pipeline: index_sheets -> chord(group(extract_sheet), embed_drawing) -> finalize_drawing.

Every task is idempotent, keyed on an `extraction_jobs(drawing_id, sheet_id,
job_type)` row: it upserts that row to `running` first and returns early if
a prior attempt already reached `succeeded`, so a chain replay (e.g. after a
worker crash) is safe. See docs/takeoff-pipeline.md.

Resilience: a chord's callback (finalize_drawing) is only ever invoked by
Celery once every member of its group has itself reported success -- if any
member (extract_sheet, embed_drawing, extract_geometry_measurements)
exhausts its retries and reports a genuine Celery-level failure, the
callback is simply never scheduled and the drawing is stuck in
`extracting`/`embedding` forever, with nothing surfacing an error. Each of
those three tasks' outer wrapper swallows a truly terminal failure (after
autoretry_for's own retries are exhausted) instead of letting it propagate
as a Celery task failure, which keeps the chord -- and therefore
finalize_drawing -- unconditional. aggregate_drawing_status() (used by both
finalize_drawing and maintenance.py's stale-drawing sweeper) turns that
ledger into ready/partial/failed.

For that ledger to actually reflect the failure, though, it has to survive
being written from inside a body that's about to re-raise: app/db/session.py
::worker_session_scope rolls back its ENTIRE transaction on any exception --
correctly, that's what makes every other task body's writes atomic -- which
means a plain `await session.flush()` on the caller's own session right
before `raise` does NOT survive (confirmed live: it doesn't, the row is
gone). So `_record_extraction_failure` below deliberately opens a SECOND,
fully independent worker session (its own connection, its own transaction)
just for that one write, committing it regardless of what happens to the
caller's own session afterward -- see that function's docstring for the
full reasoning, including why the caller's session can't just be committed
in place instead.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from uuid import UUID

from celery import chord, group
from celery.exceptions import Retry
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.enums import DrawingKind, DrawingStatus, ExtractionJobStatus, ExtractionJobType
from app.core.logging import get_logger
from app.integrations.embeddings import get_embedder
from app.integrations.s3 import get_object_bytes
from app.models.takeoff import Drawing, DrawingEntity, DrawingSheet, ExtractionJob, PdfLayerMappingRule, SheetChunk
from app.services import takeoff as takeoff_service
from app.takeoff import dxf as dxf_mod
from app.takeoff import pdf as pdf_mod
from app.takeoff.chunking import build_sheet_chunks
from app.takeoff.geometry.entities import GeometricEntity
from app.takeoff.pdf import PdfLayerRule
from app.takeoff.scale import (
    PositionedText,
    ScaleSignal,
    dimension_cross_check_signals,
    estimate_scale,
    parse_scale_text,
    scale_bar_signal,
)
from app.takeoff.titleblock import extract_title_block
from app.workers.base import build_worker_context, run_async, system_ctx, with_worker_session
from app.workers.celery_app import celery_app

logger = get_logger(__name__)


def _geometry_drawing_entity(
    *, tenant_id: UUID, sheet_id: UUID, project_id: UUID, source: str, g: GeometricEntity
) -> DrawingEntity:
    """Shared by the DXF and PDF branches of _index_sheets_body -- same
    GeometricEntity shape either way (see app.takeoff.geometry.entities'
    module docstring)."""
    bbox = _geometry_bbox(g)
    return DrawingEntity(
        tenant_id=tenant_id, sheet_id=sheet_id, project_id=project_id, source=source, entity_type=g.entity_type,
        layer=g.layer, block_name=g.block_name, handle=g.handle,
        bbox_min_x=bbox[0] if bbox else None, bbox_min_y=bbox[1] if bbox else None,
        bbox_max_x=bbox[2] if bbox else None, bbox_max_y=bbox[3] if bbox else None,
        geometry={
            "vertices": g.vertices, "closed": g.closed, "bulges": g.bulges or None,
            "center": g.center, "radius": g.radius,
            "start_angle_deg": g.start_angle_deg, "end_angle_deg": g.end_angle_deg,
        },
        attributes=g.attributes or None,
    )


def _geometry_bbox(g: GeometricEntity) -> tuple[float, float, float, float] | None:
    if g.vertices:
        xs = [v[0] for v in g.vertices]
        ys = [v[1] for v in g.vertices]
        return (min(xs), min(ys), max(xs), max(ys))
    if g.entity_type == "arc" and g.center and g.radius is not None:
        # Full-circle bbox, not the tighter bbox of just the swept arc --
        # a safe overestimate, fine for the coarse spatial filtering this
        # column is for.
        cx, cy = g.center
        return (cx - g.radius, cy - g.radius, cx + g.radius, cy + g.radius)
    return None


async def _upsert_job(
    session: AsyncSession, tenant_id: UUID, project_id: UUID, drawing_id: UUID, sheet_id: UUID | None,
    job_type: str, task_id: str, *, force: bool = False,
) -> ExtractionJob | None:
    """Returns the job row to run, or None if a prior attempt already
    succeeded (idempotent replay guard) -- unless `force`, which always
    returns the row to (re-)run regardless of a prior success. Every
    caller except finalize_drawing wants the default: extract_sheet/
    embed_drawing/etc. do real, possibly-expensive work that a successful
    prior attempt makes genuinely redundant to repeat. finalize_drawing is
    different in kind -- it doesn't DO anything itself, it just reads the
    CURRENT state of every other job and reflects it onto the drawing, so
    skipping it because it "already succeeded" once is wrong: on a retry
    (POST /drawings/{id}/ingest again) it would otherwise silently freeze
    drawing.status/error_message at whatever they were after the FIRST
    finalize forever, even though the other jobs it's meant to summarize
    just genuinely changed -- confirmed live: retrying a drawing whose
    embed_sheet had failed once already (reaching finalize -> `partial`)
    left it stuck showing `partial` with the OLD reason even after the
    retry's embed_sheet succeeded outright."""
    stmt = select(ExtractionJob).where(
        ExtractionJob.drawing_id == drawing_id, ExtractionJob.job_type == job_type
    )
    stmt = stmt.where(ExtractionJob.sheet_id == sheet_id) if sheet_id else stmt.where(ExtractionJob.sheet_id.is_(None))
    existing = (await session.execute(stmt)).scalars().first()
    if existing and existing.status == ExtractionJobStatus.SUCCEEDED.value and not force:
        return None
    if existing:
        existing.status = ExtractionJobStatus.RUNNING.value
        existing.attempt += 1
        existing.celery_task_id = task_id
        existing.started_at = datetime.now(timezone.utc)
        job = existing
    else:
        job = ExtractionJob(
            tenant_id=tenant_id, project_id=project_id, drawing_id=drawing_id, sheet_id=sheet_id,
            job_type=job_type, celery_task_id=task_id, status=ExtractionJobStatus.RUNNING.value,
            started_at=datetime.now(timezone.utc),
        )
        session.add(job)
    await session.flush()
    return job


async def _finish_job(session: AsyncSession, job: ExtractionJob, *, ok: bool, error: str | None, started_at: float) -> None:
    job.status = ExtractionJobStatus.SUCCEEDED.value if ok else ExtractionJobStatus.FAILED.value
    job.finished_at = datetime.now(timezone.utc)
    job.duration_ms = int((time.monotonic() - started_at) * 1000)
    job.error = error
    await session.flush()


async def _claim_job_body(
    session: AsyncSession, tenant_id: str, project_id: str, drawing_id: str, sheet_id: str | None,
    job_type: str, task_id: str,
) -> str | None:
    job = await _upsert_job(
        session, UUID(tenant_id), UUID(project_id), UUID(drawing_id),
        UUID(sheet_id) if sheet_id is not None else None, job_type, task_id,
    )
    return str(job.id) if job is not None else None


async def _claim_job(
    tenant_id: UUID, project_id: UUID, drawing_id: UUID, job_type: str, task_id: str, *, sheet_id: UUID | None = None,
) -> UUID | None:
    """Claims (upserts to `running`) one extraction_jobs row via its own,
    immediately-committed independent session -- BEFORE the caller's own
    main-body session (with_worker_session(ctx, _extract_sheet_body, ...),
    etc.) touches this row at all, and returns just its id. This is what
    makes the later success write (the main session, once its own work
    succeeds) and failure write (_record_extraction_failure's own
    independent session, see below) plain UPDATEs against an already-
    visible, already-committed row, never a fresh INSERT racing another
    session's still-open one.

    That race is real, not theoretical: extraction_jobs has a genuine
    unique index, uq_extraction_jobs_dedup(drawing_id,
    COALESCE(sheet_id,...), job_type, attempt) -- not visible on the
    ExtractionJob model itself, only in the migration -- so two sessions
    both calling plain _upsert_job() against the same session (the
    now-reverted first version of this fix) deadlock: the second session's
    INSERT blocks on a Postgres `transactionid` wait for the first
    session's own still-open transaction to resolve, which never happens,
    because the first session is itself still awaiting this very call to
    return. Confirmed live (docs/takeoff-pipeline.md) before this claim/
    finish split existed. index_sheets/finalize_drawing don't need this --
    they aren't the ones that swallow a terminal failure past their own
    session's rollback, so _upsert_job called directly, as before, is
    still correct and unchanged for them."""
    ctx = system_ctx(str(tenant_id))
    job_id = await with_worker_session(
        ctx, _claim_job_body, str(tenant_id), str(project_id), str(drawing_id),
        str(sheet_id) if sheet_id is not None else None, job_type, task_id,
    )
    return UUID(job_id) if job_id is not None else None


async def _record_extraction_failure_body(session: AsyncSession, job_id: str, error: str, duration_ms: int, sheet_id: str | None) -> None:
    job = (await session.execute(select(ExtractionJob).where(ExtractionJob.id == UUID(job_id)))).scalar_one()
    job.status = ExtractionJobStatus.FAILED.value
    job.error = error
    job.finished_at = datetime.now(timezone.utc)
    job.duration_ms = duration_ms
    if sheet_id is not None:
        sheet = (await session.execute(select(DrawingSheet).where(DrawingSheet.id == UUID(sheet_id)))).scalar_one()
        sheet.extraction_status = "failed"


async def _record_extraction_failure(
    job_id: UUID, tenant_id: UUID, error: str, started_at: float, *, sheet_id: UUID | None = None,
) -> None:
    """Persists one job's failure (and, for a per-sheet failure,
    DrawingSheet.extraction_status) durably, via its own fully independent
    worker session -- NOT the caller's own session/transaction, which is
    about to have its exception re-raised and therefore fully rolled back
    by worker_session_scope (correctly -- that's what keeps every OTHER
    write in that same transaction atomic). Writing through the caller's
    own session and committing it early would work for this one row, but
    Session.commit() always flushes and commits EVERYTHING still pending
    on that session, not just this write -- for extract_sheet/embed_drawing
    that can include rows added earlier in the same call for sheets/chunks
    that have nothing to do with THIS failure, which must stay tied to
    this attempt's own fate, not get durably committed by accident because
    a later, unrelated part of the same call happened to fail. `job_id`
    must come from _claim_job (already committed independently) -- an
    UPDATE by id here never conflicts with anything, unlike a fresh
    _upsert_job call would (see _claim_job's own docstring for the
    deadlock that shipped before this split existed)."""
    duration_ms = int((time.monotonic() - started_at) * 1000)
    ctx = system_ctx(str(tenant_id))
    await with_worker_session(
        ctx, _record_extraction_failure_body, str(job_id), error, duration_ms,
        str(sheet_id) if sheet_id is not None else None,
    )


# ---------------------------------------------------------------------------
# index_sheets
# ---------------------------------------------------------------------------

async def _index_sheets_body(session: AsyncSession, drawing_id: str, task_id: str) -> list[str]:
    t0 = time.monotonic()
    drawing = (await session.execute(select(Drawing).where(Drawing.id == UUID(drawing_id)))).scalar_one()
    job = await _upsert_job(session, drawing.tenant_id, drawing.project_id, drawing.id, None, ExtractionJobType.INDEX_SHEETS.value, task_id)
    if job is None:
        existing_sheets = (await session.execute(select(DrawingSheet).where(DrawingSheet.drawing_id == drawing.id))).scalars().all()
        return [str(s.id) for s in existing_sheets]

    drawing.status = DrawingStatus.INDEXING.value
    await session.flush()

    try:
        data = await get_object_bytes(drawing.object_key)
        sheet_ids: list[str] = []

        if drawing.kind == DrawingKind.DXF.value:
            layouts = dxf_mod.index_dxf(data)
            settings = get_settings()
            geometry_by_layout = dxf_mod.index_dxf_geometry(data) if settings.takeoff_persist_geometry else {}
            for i, layout in enumerate(layouts):
                raw_text = "\n".join(e.text_value for e in layout.text_entities if e.text_value)
                sheet = DrawingSheet(
                    tenant_id=drawing.tenant_id, drawing_id=drawing.id, project_id=drawing.project_id,
                    sheet_index=i, source_name=layout.layout_name, units=layout.units, is_raster=False,
                    raw_text=raw_text, text_char_count=len(raw_text),
                )
                session.add(sheet)
                await session.flush()
                sheet_ids.append(str(sheet.id))
                for e in layout.text_entities:
                    session.add(
                        DrawingEntity(
                            tenant_id=drawing.tenant_id, sheet_id=sheet.id, project_id=drawing.project_id,
                            source="dxf", entity_type=e.entity_type, layer=e.layer, block_name=e.block_name,
                            text_value=e.text_value, handle=e.handle,
                            bbox_min_x=e.bbox[0] if e.bbox else None, bbox_min_y=e.bbox[1] if e.bbox else None,
                            bbox_max_x=e.bbox[2] if e.bbox else None, bbox_max_y=e.bbox[3] if e.bbox else None,
                        )
                    )
                for g in geometry_by_layout.get(layout.layout_name, []):
                    session.add(
                        _geometry_drawing_entity(
                            tenant_id=drawing.tenant_id, sheet_id=sheet.id, project_id=drawing.project_id,
                            source="dxf", g=g,
                        )
                    )
            drawing.sheet_count = len(layouts)
        else:
            pages = pdf_mod.index_pdf(data)
            settings = get_settings()
            geometry_by_page: dict[str, list[GeometricEntity]] = {}
            if settings.takeoff_persist_geometry:
                rules_rows = (
                    await session.execute(
                        select(PdfLayerMappingRule)
                        .where(PdfLayerMappingRule.project_id == drawing.project_id)
                        .order_by(PdfLayerMappingRule.priority)
                    )
                ).scalars().all()
                rules = [
                    PdfLayerRule(
                        target_layer=r.target_layer, stroke_color=r.stroke_color,
                        min_line_width=r.min_line_width, max_line_width=r.max_line_width,
                        dash_pattern=r.dash_pattern, ocg_name_contains=r.ocg_name_contains, priority=r.priority,
                    )
                    for r in rules_rows
                ]
                geometry_by_page = pdf_mod.index_pdf_geometry(data, rules)

            for page in pages:
                page_label = f"page-{page.index + 1}"
                sheet = DrawingSheet(
                    tenant_id=drawing.tenant_id, drawing_id=drawing.id, project_id=drawing.project_id,
                    sheet_index=page.index, source_name=page_label,
                    width_pt=page.width_pt, height_pt=page.height_pt,
                    # PDF geometry (app.takeoff.pdf::index_pdf_geometry) is
                    # in page points -- "pt" is the unit units.py/
                    # sheet_scale_factor() know to also fold the sheet's
                    # scale_ratio into (Module B Phase 4a).
                    units="pt", is_raster=page.is_raster,
                    raw_text=page.raw_text, text_char_count=len(page.raw_text),
                    title_block=None,
                )
                session.add(sheet)
                await session.flush()
                sheet_ids.append(str(sheet.id))
                for g in geometry_by_page.get(page_label, []):
                    session.add(
                        _geometry_drawing_entity(
                            tenant_id=drawing.tenant_id, sheet_id=sheet.id, project_id=drawing.project_id,
                            source="pdf", g=g,
                        )
                    )
            drawing.sheet_count = len(pages)
            if any(p.is_raster for p in pages):
                drawing.kind = DrawingKind.SCANNED_PDF.value if all(p.is_raster for p in pages) else drawing.kind

        drawing.status = DrawingStatus.EXTRACTING.value
        await session.flush()
        await _finish_job(session, job, ok=True, error=None, started_at=t0)
        return sheet_ids
    except Exception as exc:  # noqa: BLE001 -- persisted below, then re-raised for Celery retry bookkeeping
        drawing.status = DrawingStatus.FAILED.value
        drawing.error_message = str(exc)
        await session.flush()
        await _finish_job(session, job, ok=False, error=str(exc), started_at=t0)
        raise


@celery_app.task(
    bind=True, name="app.workers.tasks.takeoff.index_sheets",
    autoretry_for=(ConnectionError,), retry_backoff=True, retry_jitter=True, max_retries=5,
)
def index_sheets(self, drawing_id: str, tenant_id: str, actor_user_id: str | None, actor_roles: list[str] | None = None) -> None:
    # actor_roles matters: build_worker_context() only sets is_system=True
    # (bypassing every RLS write policy) when actor_user_id is None. With a
    # real actor_user_id but no roles, the extraction_jobs INSERT's
    # `app_has_role(...)` WITH CHECK can never pass -- this task would fail
    # RLS on its very first write for any real (non-system) caller.
    ctx = build_worker_context(tenant_id, actor_user_id, actor_roles)

    async def _run() -> None:
        sheet_ids = await with_worker_session(ctx, _index_sheets_body, drawing_id, self.request.id)
        header = [extract_sheet.si(sid, tenant_id) for sid in sheet_ids]
        header.append(embed_drawing.si(drawing_id, tenant_id))
        header.append(extract_geometry_measurements.si(drawing_id, tenant_id))
        chord(group(header), finalize_drawing.si(drawing_id, tenant_id)).apply_async()

    run_async(_run)()


# ---------------------------------------------------------------------------
# extract_sheet
# ---------------------------------------------------------------------------

async def _extract_sheet_body(session: AsyncSession, sheet_id: str, task_id: str) -> None:
    t0 = time.monotonic()
    sheet = (await session.execute(select(DrawingSheet).where(DrawingSheet.id == UUID(sheet_id)))).scalar_one()
    job_id = await _claim_job(
        sheet.tenant_id, sheet.project_id, sheet.drawing_id, ExtractionJobType.EXTRACT_TITLE_BLOCK.value,
        task_id, sheet_id=sheet.id,
    )
    if job_id is None:
        return

    try:
        image_png = None
        candidate_text = sheet.raw_text or ""
        drawing = (await session.execute(select(Drawing).where(Drawing.id == sheet.drawing_id))).scalar_one()
        # Only a PDF-kind drawing has a page this codebase can rasterize
        # (pdf_mod.render_page_png) -- there is no DXF-to-PNG path at all.
        # A DXF sheet with no extractable text (sheet.is_raster is always
        # False for DXF; this means a genuinely bare layout, e.g. a
        # title-block-only paperspace tab with no real annotation text)
        # must fall through to a text-only, no-image extract_title_block
        # call instead of attempting to render non-PDF bytes as one. Found
        # live: "Failed to load document (PDFium: Data format error)" on a
        # real DXF test fixture's sparse layout.
        if drawing.kind != DrawingKind.DXF.value and (sheet.is_raster or not candidate_text.strip()):
            data = await get_object_bytes(drawing.object_key)
            page_png = pdf_mod.render_page_png(data, sheet.sheet_index)
            image_png = pdf_mod.crop_title_block_png(page_png)

        result = await extract_title_block(candidate_text=candidate_text[-2000:], image_png=image_png)

        sheet.title_block = result.raw
        sheet.drawing_number = result.drawing_number
        sheet.sheet_title = result.sheet_title
        sheet.revision = result.revision
        sheet.issue_date = result.issue_date
        sheet.discipline = result.discipline
        sheet.scale_text = result.scale_text
        sheet.vlm_model = "vllm"
        sheet.extraction_status = "succeeded"

        scale_result = parse_scale_text(result.scale_text)
        if scale_result.confidence == 0.0 and result.scale_text:
            from app.takeoff.scale import disambiguate_via_vlm

            scale_result = await disambiguate_via_vlm(result.scale_text, result.discipline)

        # Module B Phase 4a: fuse the annotation-text signal above with
        # whatever else is available from this sheet's persisted geometry
        # (dimension cross-check, scale-bar detection) and a units-based
        # fallback -- see app/takeoff/scale.py::estimate_scale. Only
        # possible when TAKEOFF_PERSIST_GEOMETRY actually persisted
        # entities for this sheet; degrades gracefully to the annotation
        # signal alone otherwise (exactly today's pre-4a behaviour).
        signals = [ScaleSignal(scale_result.ratio, scale_result.source, scale_result.confidence)]
        entity_rows = (
            await session.execute(
                select(DrawingEntity).where(
                    DrawingEntity.sheet_id == sheet.id, DrawingEntity.entity_type.in_(("line", "dimension"))
                )
            )
        ).scalars().all()
        if entity_rows:
            entities = [takeoff_service.row_to_geometric_entity(r) for r in entity_rows]
            signals.extend(dimension_cross_check_signals(entities))
            text_rows = (
                await session.execute(
                    select(DrawingEntity).where(
                        DrawingEntity.sheet_id == sheet.id, DrawingEntity.text_value.is_not(None),
                        DrawingEntity.bbox_min_x.is_not(None),
                    )
                )
            ).scalars().all()
            texts = [PositionedText(r.text_value, float(r.bbox_min_x), float(r.bbox_min_y)) for r in text_rows]
            bar_signal = scale_bar_signal(entities, texts)
            if bar_signal is not None:
                signals.append(bar_signal)
        if sheet.units and sheet.units != "pt":
            units_ratio, units_confidence = dxf_mod.derive_scale_from_units(sheet.units)
            signals.append(ScaleSignal(units_ratio, "units_fallback", units_confidence))

        estimate = estimate_scale(signals)
        sheet.scale_disagreement = estimate.disagreement
        await takeoff_service.record_scale_calibration(
            session, sheet, ratio=estimate.ratio, source=estimate.source, confidence=estimate.confidence,
            set_by=None, note="auto-detected (multi-signal fusion)",
        )

        await session.flush()
        # Re-fetched by id, not the ExtractionJob object _claim_job would
        # have returned had it not gone through its own independent
        # session -- see _claim_job's docstring. A plain UPDATE against an
        # already-committed row, same as this session commits everything
        # else it did in this call.
        job = (await session.execute(select(ExtractionJob).where(ExtractionJob.id == job_id))).scalar_one()
        await _finish_job(session, job, ok=True, error=None, started_at=t0)
    except Exception as exc:  # noqa: BLE001
        # Recorded via an independent session (_record_extraction_failure),
        # not this one -- see that function's docstring: this session's own
        # transaction is about to be rolled back in full by the `raise`
        # below (correctly), so a plain write here would never survive.
        await _record_extraction_failure(job_id, sheet.tenant_id, str(exc), t0, sheet_id=sheet.id)
        raise


@celery_app.task(
    bind=True, name="app.workers.tasks.takeoff.extract_sheet",
    autoretry_for=(ConnectionError, TimeoutError), retry_backoff=True, retry_jitter=True, max_retries=3,
    soft_time_limit=90,
)
def extract_sheet(self, sheet_id: str, tenant_id: str) -> None:
    ctx = build_worker_context(tenant_id)
    try:
        run_async(lambda: with_worker_session(ctx, _extract_sheet_body, sheet_id, self.request.id))()
    except Retry:
        raise
    except Exception:  # noqa: BLE001 -- see module docstring: a terminal per-sheet
        # failure must not become a Celery-level task failure, or index_sheets'
        # chord callback (finalize_drawing) never runs and the drawing is stuck.
        # _extract_sheet_body already recorded this in extraction_jobs/
        # DrawingSheet.extraction_status above (when it got far enough to --
        # see that function's own except block); logged here too (with the
        # real traceback) since swallowing it silently would otherwise hide
        # a genuine infrastructure bug (e.g. the DB/session layer itself
        # failing before any ledger write could happen at all) from
        # anything but a log search.
        logger.error("extract_sheet_terminal_failure_swallowed", sheet_id=sheet_id, tenant_id=tenant_id, exc_info=True)


# ---------------------------------------------------------------------------
# embed_drawing
# ---------------------------------------------------------------------------

async def _embed_drawing_body(session: AsyncSession, drawing_id: str, task_id: str) -> None:
    t0 = time.monotonic()
    drawing = (await session.execute(select(Drawing).where(Drawing.id == UUID(drawing_id)))).scalar_one()
    job_id = await _claim_job(drawing.tenant_id, drawing.project_id, drawing.id, ExtractionJobType.EMBED_SHEET.value, task_id)
    if job_id is None:
        return

    try:
        embedder = get_embedder()
        sheets = (await session.execute(select(DrawingSheet).where(DrawingSheet.drawing_id == drawing.id))).scalars().all()

        for sheet in sheets:
            entities = (
                await session.execute(select(DrawingEntity).where(DrawingEntity.sheet_id == sheet.id))
            ).scalars().all()
            by_layer: dict[str, list[str]] = {}
            for e in entities:
                if e.text_value:
                    by_layer.setdefault(e.layer or "unknown", []).append(e.text_value)

            chunks = build_sheet_chunks(
                sheet_id=str(sheet.id), title_block=sheet.title_block, raw_text=sheet.raw_text,
                entities_by_layer=by_layer,
            )
            if not chunks:
                continue
            vectors = embedder.embed([c.content for c in chunks])
            for i, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True)):
                session.add(
                    SheetChunk(
                        tenant_id=drawing.tenant_id, sheet_id=sheet.id, drawing_id=drawing.id,
                        project_id=drawing.project_id, chunk_index=i, chunk_type=chunk.chunk_type,
                        content=chunk.content, token_count=len(chunk.content) // 4,
                        embedding=vector, embedding_model=embedder.model_name, source_ref=chunk.source_ref,
                    )
                )
        await session.flush()
        job = (await session.execute(select(ExtractionJob).where(ExtractionJob.id == job_id))).scalar_one()
        await _finish_job(session, job, ok=True, error=None, started_at=t0)
    except Exception as exc:  # noqa: BLE001
        # See _record_extraction_failure's docstring: this session's own
        # transaction is about to be rolled back in full by the `raise`
        # below, so a plain write here would never survive.
        await _record_extraction_failure(job_id, drawing.tenant_id, str(exc), t0)
        raise


@celery_app.task(
    bind=True, name="app.workers.tasks.takeoff.embed_drawing",
    autoretry_for=(ConnectionError,), retry_backoff=True, retry_jitter=True, max_retries=3,
)
def embed_drawing(self, drawing_id: str, tenant_id: str) -> None:
    ctx = build_worker_context(tenant_id)
    try:
        run_async(lambda: with_worker_session(ctx, _embed_drawing_body, drawing_id, self.request.id))()
    except Retry:
        raise
    except Exception:  # noqa: BLE001 -- see module docstring. Embeddings are
        # optional by design (semantic search degrades gracefully without
        # them); a terminal failure here (e.g. no embedding model
        # provisioned) must make the drawing `partial`, not leave it stuck
        # in `extracting` forever -- so this must not become a Celery-level
        # task failure either. _embed_drawing_body already recorded it (when
        # it got far enough to -- see that function's own except block);
        # logged here too so a genuine infrastructure failure before any
        # ledger write is still visible somewhere, not fully silent.
        logger.error("embed_drawing_terminal_failure_swallowed", drawing_id=drawing_id, tenant_id=tenant_id, exc_info=True)


# ---------------------------------------------------------------------------
# extract_geometry_measurements (Phase 2b)
# ---------------------------------------------------------------------------

async def _extract_geometry_measurements_body(session: AsyncSession, drawing_id: str, task_id: str) -> None:
    t0 = time.monotonic()
    drawing = (await session.execute(select(Drawing).where(Drawing.id == UUID(drawing_id)))).scalar_one()
    job_id = await _claim_job(drawing.tenant_id, drawing.project_id, drawing.id, ExtractionJobType.EXTRACT_GEOMETRY.value, task_id)
    if job_id is None:
        return

    try:
        if get_settings().takeoff_persist_geometry:
            sheets = (await session.execute(select(DrawingSheet).where(DrawingSheet.drawing_id == drawing.id))).scalars().all()
            for sheet in sheets:
                # recompute_sheet_measurements() gates on the same
                # TAKEOFF_PERSIST_GEOMETRY flag itself and is a no-op for a
                # sheet with no persisted geometry entities -- shared with
                # takeoff_service.set_manual_scale's post-calibration
                # recompute (Module B Phase 4a), see its docstring.
                await takeoff_service.recompute_sheet_measurements(session, sheet)
        await session.flush()
        job = (await session.execute(select(ExtractionJob).where(ExtractionJob.id == job_id))).scalar_one()
        await _finish_job(session, job, ok=True, error=None, started_at=t0)
    except Exception as exc:  # noqa: BLE001
        # See _record_extraction_failure's docstring: this session's own
        # transaction is about to be rolled back in full by the `raise`
        # below, so a plain write here would never survive.
        await _record_extraction_failure(job_id, drawing.tenant_id, str(exc), t0)
        raise


@celery_app.task(
    bind=True, name="app.workers.tasks.takeoff.extract_geometry_measurements",
    autoretry_for=(ConnectionError,), retry_backoff=True, retry_jitter=True, max_retries=3,
)
def extract_geometry_measurements(self, drawing_id: str, tenant_id: str) -> None:
    ctx = build_worker_context(tenant_id)
    try:
        run_async(lambda: with_worker_session(ctx, _extract_geometry_measurements_body, drawing_id, self.request.id))()
    except Retry:
        raise
    except Exception:  # noqa: BLE001 -- see module docstring: same reasoning
        # as extract_sheet/embed_drawing above -- must not block finalize_drawing.
        logger.error(
            "extract_geometry_measurements_terminal_failure_swallowed",
            drawing_id=drawing_id, tenant_id=tenant_id, exc_info=True,
        )


# ---------------------------------------------------------------------------
# finalize_drawing
# ---------------------------------------------------------------------------

def _summarize_failed_jobs(failed_jobs: list[ExtractionJob]) -> str:
    """Short, user-visible reason for a partial/failed drawing -- one clause
    per failed extraction_jobs row (job type, sheet if per-sheet, and its
    recorded error), capped so it stays readable in the UI."""
    parts = []
    for j in failed_jobs:
        label = j.job_type if j.sheet_id is None else f"{j.job_type} (sheet {j.sheet_id})"
        reason = (j.error or "unknown error").strip()[:200]
        parts.append(f"{label}: {reason}")
    return "; ".join(parts)[:2000]


def aggregate_drawing_status(
    jobs: list[ExtractionJob], *, exclude_job_id: UUID | None = None
) -> tuple[str, str | None]:
    """Shared by finalize_drawing (the chord callback) and
    maintenance.py's reap_stuck_drawings (the stale-drawing sweeper): derive
    a drawing's final status from its own extraction_jobs ledger, never from
    Celery's own per-task success/failure -- see this module's docstring for
    why a permanently-failing chord member deliberately never reports a
    Celery-level failure. `ready` if nothing failed; `partial` if some
    content job failed but at least one succeeded; `failed` if none did.
    "Content" jobs exclude FINALIZE (the in-flight caller's own job row,
    via exclude_job_id -- never itself 'failed' at this point but would
    otherwise dilute the aggregation) and INDEX_SHEETS: indexing having
    succeeded is only a prerequisite for the chord to exist at all, not
    itself extracted content, so a drawing where every real extraction step
    failed must read as `failed`, not `partial` just because indexing
    nominally succeeded first."""
    _non_content = {ExtractionJobType.FINALIZE.value, ExtractionJobType.INDEX_SHEETS.value}
    content_jobs = [
        j for j in jobs
        if j.job_type not in _non_content and (exclude_job_id is None or j.id != exclude_job_id)
    ]
    failed = [j for j in content_jobs if j.status == ExtractionJobStatus.FAILED.value]
    if not failed:
        return DrawingStatus.READY.value, None
    succeeded = [j for j in content_jobs if j.status == ExtractionJobStatus.SUCCEEDED.value]
    status = DrawingStatus.PARTIAL.value if succeeded else DrawingStatus.FAILED.value
    return status, _summarize_failed_jobs(failed)


async def _finalize_drawing_body(session: AsyncSession, drawing_id: str, task_id: str) -> None:
    t0 = time.monotonic()
    drawing = (await session.execute(select(Drawing).where(Drawing.id == UUID(drawing_id)))).scalar_one()
    job = await _upsert_job(
        session, drawing.tenant_id, drawing.project_id, drawing.id, None, ExtractionJobType.FINALIZE.value, task_id,
        force=True,
    )
    assert job is not None  # force=True never returns None

    jobs = (await session.execute(select(ExtractionJob).where(ExtractionJob.drawing_id == drawing.id))).scalars().all()
    drawing.status, drawing.error_message = aggregate_drawing_status(jobs, exclude_job_id=job.id)
    await session.flush()
    await _finish_job(session, job, ok=True, error=None, started_at=t0)


@celery_app.task(bind=True, name="app.workers.tasks.takeoff.finalize_drawing")
def finalize_drawing(self, drawing_id: str, tenant_id: str) -> None:
    ctx = build_worker_context(tenant_id)
    run_async(lambda: with_worker_session(ctx, _finalize_drawing_body, drawing_id, self.request.id))()
