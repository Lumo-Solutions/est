from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import RequestContext
from app.core.enums import AuditAction, DrawingStatus
from app.core.errors import ConflictError, NotFoundError
from app.integrations.embeddings import get_embedder
from app.integrations.s3 import presign_get_url, put_object_streaming
from app.models.takeoff import Drawing, DrawingMeasurement, DrawingSheet, ExtractionJob
from app.services import audit
from app.services.projects import assert_can_see_project

_ALLOWED_CONTENT_TYPES = {
    "application/pdf": "vector_pdf",  # refined to scanned_pdf per-page during indexing
    "application/dxf": "dxf",
    "image/vnd.dxf": "dxf",
}


async def upload_drawing(
    session: AsyncSession, ctx: RequestContext, project_id: UUID, filename: str, content_type: str | None, data: bytes
) -> Drawing:
    # `drawings` is project_scoped (RLS), but there's no prior read here to
    # let that policy silently filter an unauthorized caller out the way it
    # would for e.g. trigger_ingest's SELECT-then-UPDATE -- an INSERT's
    # WITH CHECK fails hard instead. Check first (before streaming to S3)
    # so an estimator/lead_estimator without project membership gets a
    # clean 403 immediately, not a 500 (or a wasted upload) partway through.
    await assert_can_see_project(session, ctx, project_id)

    kind = _ALLOWED_CONTENT_TYPES.get(content_type or "", "unknown")
    if kind == "unknown" and filename.lower().endswith(".dxf"):
        kind = "dxf"
    elif kind == "unknown" and filename.lower().endswith(".pdf"):
        kind = "vector_pdf"

    object_key = f"projects/{project_id}/drawings/{filename}"
    sha256 = await put_object_streaming(object_key, data, content_type)

    existing = await session.execute(
        select(Drawing).where(Drawing.project_id == project_id, Drawing.sha256 == sha256)
    )
    if (row := existing.scalar_one_or_none()) is not None:
        return row

    drawing = Drawing(
        tenant_id=ctx.tenant_id,
        project_id=project_id,
        original_filename=filename,
        content_type=content_type,
        kind=kind,
        bucket="installtec-drawings",
        object_key=object_key,
        size_bytes=len(data),
        sha256=sha256,
        status=DrawingStatus.UPLOADED.value,
        uploaded_by=ctx.user_id,
    )
    session.add(drawing)
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.CREATE, entity_type="drawing", entity_id=drawing.id,
        project_id=project_id, payload={"filename": filename, "size_bytes": len(data)},
    )
    return drawing


async def get_drawing(session: AsyncSession, drawing_id: UUID) -> Drawing:
    result = await session.execute(select(Drawing).where(Drawing.id == drawing_id))
    drawing = result.scalar_one_or_none()
    if drawing is None:
        raise NotFoundError(f"Drawing {drawing_id} not found")
    return drawing


async def trigger_ingest(session: AsyncSession, ctx: RequestContext, drawing_id: UUID) -> list[str]:
    from app.workers.tasks.takeoff import index_sheets

    drawing = await get_drawing(session, drawing_id)
    if drawing.status in (DrawingStatus.INDEXING.value, DrawingStatus.EXTRACTING.value, DrawingStatus.EMBEDDING.value):
        raise ConflictError(f"Drawing {drawing_id} is already being processed (status={drawing.status})")

    drawing.status = DrawingStatus.QUEUED.value
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.UPDATE, entity_type="drawing", entity_id=drawing.id,
        project_id=drawing.project_id, payload={"status": "queued"},
    )

    task = index_sheets.delay(
        str(drawing.id), str(ctx.tenant_id), str(ctx.user_id) if ctx.user_id else None, list(ctx.roles)
    )
    return [task.id]


async def list_jobs(session: AsyncSession, drawing_id: UUID) -> list[ExtractionJob]:
    result = await session.execute(
        select(ExtractionJob).where(ExtractionJob.drawing_id == drawing_id).order_by(ExtractionJob.started_at)
    )
    return list(result.scalars().all())


async def list_measurements(
    session: AsyncSession, drawing_id: UUID, sheet_id: UUID | None = None
) -> list[DrawingMeasurement]:
    stmt = select(DrawingMeasurement).where(DrawingMeasurement.drawing_id == drawing_id)
    if sheet_id is not None:
        stmt = stmt.where(DrawingMeasurement.sheet_id == sheet_id)
    stmt = stmt.order_by(DrawingMeasurement.sheet_id, DrawingMeasurement.capability, DrawingMeasurement.kind)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_sheet(session: AsyncSession, drawing_id: UUID, sheet_index: int) -> DrawingSheet:
    result = await session.execute(
        select(DrawingSheet).where(DrawingSheet.drawing_id == drawing_id, DrawingSheet.sheet_index == sheet_index)
    )
    sheet = result.scalar_one_or_none()
    if sheet is None:
        raise NotFoundError(f"Sheet {sheet_index} of drawing {drawing_id} not found")
    return sheet


async def set_manual_scale(
    session: AsyncSession, ctx: RequestContext, drawing_id: UUID, sheet_index: int,
    p1: tuple[float, float], p2: tuple[float, float], known_length_m: float,
) -> DrawingSheet:
    sheet = await get_sheet(session, drawing_id, sheet_index)
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    drawing_distance = (dx**2 + dy**2) ** 0.5
    if drawing_distance <= 0:
        raise ConflictError("The two calibration points must be distinct")
    sheet.scale_ratio = known_length_m / drawing_distance
    sheet.scale_source = "manual_two_point"
    sheet.scale_confidence = 1.0
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.UPDATE, entity_type="drawing_sheet", entity_id=sheet.id,
        project_id=None, payload={"scale_source": "manual_two_point", "scale_ratio": float(sheet.scale_ratio)},
    )
    return sheet


async def presigned_download_url(session: AsyncSession, ctx: RequestContext, drawing_id: UUID) -> str:
    drawing = await get_drawing(session, drawing_id)
    url = await presign_get_url(drawing.object_key)
    await audit.record(
        session, ctx, action=AuditAction.DOWNLOAD, entity_type="drawing", entity_id=drawing.id,
        project_id=drawing.project_id,
    )
    return url


async def search_sheets(session: AsyncSession, project_id: UUID, query: str, top_k: int) -> list[dict]:
    """Thin pgvector similarity probe -- proves the embedding store works.
    NOT BOQ reconciliation (deferred; see docs/architecture.md)."""
    embedder = get_embedder()
    vector = embedder.embed([query])[0]
    result = await session.execute(
        text(
            "SELECT sheet_id, drawing_id, chunk_type, content, embedding <=> (:v)::vector AS distance "
            "FROM sheet_chunks WHERE project_id = :p ORDER BY embedding <=> (:v)::vector LIMIT :k"
        ),
        {"v": str(vector), "p": str(project_id), "k": top_k},
    )
    return [dict(row._mapping) for row in result.all()]
