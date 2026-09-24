"""Module B ingestion pipeline: index_sheets -> chord(group(extract_sheet), embed_drawing) -> finalize_drawing.

Every task is idempotent, keyed on an `extraction_jobs(drawing_id, sheet_id,
job_type)` row: it upserts that row to `running` first and returns early if
a prior attempt already reached `succeeded`, so a chain replay (e.g. after a
worker crash) is safe. See docs/takeoff-pipeline.md.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from uuid import UUID

from celery import chord, group
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.enums import DrawingKind, DrawingStatus, ExtractionJobStatus, ExtractionJobType
from app.integrations.embeddings import get_embedder
from app.integrations.s3 import get_object_bytes
from app.models.takeoff import Drawing, DrawingEntity, DrawingMeasurement, DrawingSheet, ExtractionJob, SheetChunk
from app.takeoff import dxf as dxf_mod
from app.takeoff import pdf as pdf_mod
from app.takeoff.chunking import build_sheet_chunks
from app.takeoff.geometry.entities import GeometricEntity
from app.takeoff.scale import parse_scale_text
from app.takeoff.titleblock import extract_title_block
from app.workers.base import build_worker_context, run_async, with_worker_session
from app.workers.celery_app import celery_app


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
    job_type: str, task_id: str,
) -> ExtractionJob | None:
    """Returns the job row to run, or None if a prior attempt already
    succeeded (idempotent replay guard)."""
    stmt = select(ExtractionJob).where(
        ExtractionJob.drawing_id == drawing_id, ExtractionJob.job_type == job_type
    )
    stmt = stmt.where(ExtractionJob.sheet_id == sheet_id) if sheet_id else stmt.where(ExtractionJob.sheet_id.is_(None))
    existing = (await session.execute(stmt)).scalars().first()
    if existing and existing.status == ExtractionJobStatus.SUCCEEDED.value:
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
                    bbox = _geometry_bbox(g)
                    session.add(
                        DrawingEntity(
                            tenant_id=drawing.tenant_id, sheet_id=sheet.id, project_id=drawing.project_id,
                            source="dxf", entity_type=g.entity_type, layer=g.layer, block_name=g.block_name,
                            handle=g.handle,
                            bbox_min_x=bbox[0] if bbox else None, bbox_min_y=bbox[1] if bbox else None,
                            bbox_max_x=bbox[2] if bbox else None, bbox_max_y=bbox[3] if bbox else None,
                            geometry={
                                "vertices": g.vertices, "closed": g.closed, "bulges": g.bulges or None,
                                "center": g.center, "radius": g.radius,
                                "start_angle_deg": g.start_angle_deg, "end_angle_deg": g.end_angle_deg,
                            },
                            attributes=g.attributes or None,
                        )
                    )
            drawing.sheet_count = len(layouts)
        else:
            pages = pdf_mod.index_pdf(data)
            for page in pages:
                sheet = DrawingSheet(
                    tenant_id=drawing.tenant_id, drawing_id=drawing.id, project_id=drawing.project_id,
                    sheet_index=page.index, source_name=f"page-{page.index + 1}",
                    width_pt=page.width_pt, height_pt=page.height_pt, is_raster=page.is_raster,
                    raw_text=page.raw_text, text_char_count=len(page.raw_text),
                    title_block=None,
                )
                session.add(sheet)
                await session.flush()
                sheet_ids.append(str(sheet.id))
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
    job = await _upsert_job(
        session, sheet.tenant_id, sheet.project_id, sheet.drawing_id, sheet.id,
        ExtractionJobType.EXTRACT_TITLE_BLOCK.value, task_id,
    )
    if job is None:
        return

    try:
        image_png = None
        candidate_text = sheet.raw_text or ""
        if sheet.is_raster or not candidate_text.strip():
            drawing = (await session.execute(select(Drawing).where(Drawing.id == sheet.drawing_id))).scalar_one()
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
        sheet.scale_ratio = scale_result.ratio
        sheet.scale_source = scale_result.source
        sheet.scale_confidence = scale_result.confidence

        await session.flush()
        await _finish_job(session, job, ok=True, error=None, started_at=t0)
    except Exception as exc:  # noqa: BLE001
        sheet.extraction_status = "failed"
        await session.flush()
        await _finish_job(session, job, ok=False, error=str(exc), started_at=t0)
        raise


@celery_app.task(
    bind=True, name="app.workers.tasks.takeoff.extract_sheet",
    autoretry_for=(ConnectionError, TimeoutError), retry_backoff=True, retry_jitter=True, max_retries=3,
    soft_time_limit=90,
)
def extract_sheet(self, sheet_id: str, tenant_id: str) -> None:
    ctx = build_worker_context(tenant_id)
    run_async(lambda: with_worker_session(ctx, _extract_sheet_body, sheet_id, self.request.id))()


# ---------------------------------------------------------------------------
# embed_drawing
# ---------------------------------------------------------------------------

async def _embed_drawing_body(session: AsyncSession, drawing_id: str, task_id: str) -> None:
    t0 = time.monotonic()
    drawing = (await session.execute(select(Drawing).where(Drawing.id == UUID(drawing_id)))).scalar_one()
    job = await _upsert_job(session, drawing.tenant_id, drawing.project_id, drawing.id, None, ExtractionJobType.EMBED_SHEET.value, task_id)
    if job is None:
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
        await _finish_job(session, job, ok=True, error=None, started_at=t0)
    except Exception as exc:  # noqa: BLE001
        await _finish_job(session, job, ok=False, error=str(exc), started_at=t0)
        raise


@celery_app.task(
    bind=True, name="app.workers.tasks.takeoff.embed_drawing",
    autoretry_for=(ConnectionError,), retry_backoff=True, retry_jitter=True, max_retries=3,
)
def embed_drawing(self, drawing_id: str, tenant_id: str) -> None:
    ctx = build_worker_context(tenant_id)
    run_async(lambda: with_worker_session(ctx, _embed_drawing_body, drawing_id, self.request.id))()


# ---------------------------------------------------------------------------
# extract_geometry_measurements (Phase 2b)
# ---------------------------------------------------------------------------

# Entity types that carry a `geometry` payload (see index_dxf_geometry());
# excludes "text"/"mtext"/"attrib"/"dimension", which never do.
_GEOMETRIC_ENTITY_TYPES = ("line", "lwpolyline", "arc", "insert_node")


def _row_to_geometric_entity(row: DrawingEntity) -> GeometricEntity:
    geometry = row.geometry or {}
    return GeometricEntity(
        entity_type=row.entity_type,
        layer=row.layer,
        handle=row.handle,
        vertices=[tuple(v) for v in (geometry.get("vertices") or [])],
        closed=bool(geometry.get("closed", False)),
        bulges=list(geometry.get("bulges") or []),
        block_name=row.block_name,
        attributes=dict(row.attributes or {}),
        center=tuple(geometry["center"]) if geometry.get("center") else None,
        radius=geometry.get("radius"),
        start_angle_deg=geometry.get("start_angle_deg"),
        end_angle_deg=geometry.get("end_angle_deg"),
    )


async def _extract_geometry_measurements_body(session: AsyncSession, drawing_id: str, task_id: str) -> None:
    t0 = time.monotonic()
    drawing = (await session.execute(select(Drawing).where(Drawing.id == UUID(drawing_id)))).scalar_one()
    job = await _upsert_job(
        session, drawing.tenant_id, drawing.project_id, drawing.id, None, ExtractionJobType.EXTRACT_GEOMETRY.value, task_id
    )
    if job is None:
        return

    try:
        if get_settings().takeoff_persist_geometry:
            # Imported here (not at module load) so importing this module
            # never has the side effect of populating the geometry
            # registry -- only actually running this task does.
            from app.takeoff.geometry.base import get_registry
            from app.takeoff.geometry import stubs as _geometry_stubs  # noqa: F401 -- registers extractors

            registry = get_registry()
            sheets = (await session.execute(select(DrawingSheet).where(DrawingSheet.drawing_id == drawing.id))).scalars().all()

            for sheet in sheets:
                rows = (
                    await session.execute(
                        select(DrawingEntity).where(
                            DrawingEntity.sheet_id == sheet.id,
                            DrawingEntity.entity_type.in_(_GEOMETRIC_ENTITY_TYPES),
                        )
                    )
                ).scalars().all()
                if not rows:
                    continue
                entities = [_row_to_geometric_entity(r) for r in rows]

                for extractor in registry.values():
                    if not extractor.supports(sheet):
                        continue
                    for m in extractor.extract(sheet, entities):
                        session.add(
                            DrawingMeasurement(
                                tenant_id=drawing.tenant_id, drawing_id=drawing.id, sheet_id=sheet.id,
                                project_id=drawing.project_id, capability=extractor.capability, kind=m.kind,
                                value=m.value, unit=m.unit, confidence=m.confidence,
                                source_entity_ids=m.source_entity_ids, extractor_metadata=m.metadata,
                            )
                        )
        await session.flush()
        await _finish_job(session, job, ok=True, error=None, started_at=t0)
    except Exception as exc:  # noqa: BLE001
        await _finish_job(session, job, ok=False, error=str(exc), started_at=t0)
        raise


@celery_app.task(
    bind=True, name="app.workers.tasks.takeoff.extract_geometry_measurements",
    autoretry_for=(ConnectionError,), retry_backoff=True, retry_jitter=True, max_retries=3,
)
def extract_geometry_measurements(self, drawing_id: str, tenant_id: str) -> None:
    ctx = build_worker_context(tenant_id)
    run_async(lambda: with_worker_session(ctx, _extract_geometry_measurements_body, drawing_id, self.request.id))()


# ---------------------------------------------------------------------------
# finalize_drawing
# ---------------------------------------------------------------------------

async def _finalize_drawing_body(session: AsyncSession, drawing_id: str, task_id: str) -> None:
    t0 = time.monotonic()
    drawing = (await session.execute(select(Drawing).where(Drawing.id == UUID(drawing_id)))).scalar_one()
    job = await _upsert_job(session, drawing.tenant_id, drawing.project_id, drawing.id, None, ExtractionJobType.FINALIZE.value, task_id)
    if job is None:
        return

    jobs = (await session.execute(select(ExtractionJob).where(ExtractionJob.drawing_id == drawing.id))).scalars().all()
    any_failed = any(j.status == ExtractionJobStatus.FAILED.value for j in jobs)
    drawing.status = DrawingStatus.PARTIAL.value if any_failed else DrawingStatus.READY.value
    await session.flush()
    await _finish_job(session, job, ok=True, error=None, started_at=t0)


@celery_app.task(bind=True, name="app.workers.tasks.takeoff.finalize_drawing")
def finalize_drawing(self, drawing_id: str, tenant_id: str) -> None:
    ctx = build_worker_context(tenant_id)
    run_async(lambda: with_worker_session(ctx, _finalize_drawing_body, drawing_id, self.request.id))()
