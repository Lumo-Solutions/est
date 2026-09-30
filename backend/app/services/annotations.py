"""Drawing annotation reading: queue per sheet, read (worker), list.

Reading is explicit (a person asks for it, or the verification run asks for it)
so AI spend is predictable. Re-reading a sheet replaces its AI annotations.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.errors import AIError
from app.ai.gateway import AIGateway, AIMeta
from app.core.context import RequestContext
from app.core.enums import AuditAction, DrawingKind
from app.integrations.s3 import get_object_bytes
from app.models.takeoff import Drawing, DrawingAnnotation, DrawingSheet
from app.services import audit
from app.services.projects import assert_can_see_project
from app.takeoff import pdf as pdf_mod
from app.takeoff.annotations import read_sheet

STATUS_QUEUED, STATUS_DONE, STATUS_UNAVAILABLE, STATUS_FAILED, STATUS_SKIPPED = (
    "queued", "done", "unavailable", "failed", "skipped",
)


async def queue_sheets(
    session: AsyncSession, ctx: RequestContext, project_id: UUID, *, drawing_id: UUID | None = None, force: bool = False
) -> list[UUID]:
    """Marks the project's (or one drawing's) sheets 'queued' and returns their ids. Sheets already
    read are skipped unless force=True."""
    await assert_can_see_project(session, ctx, project_id)
    stmt = select(DrawingSheet).where(DrawingSheet.project_id == project_id)
    if drawing_id:
        stmt = stmt.where(DrawingSheet.drawing_id == drawing_id)
    sheets = (await session.execute(stmt.order_by(DrawingSheet.drawing_id, DrawingSheet.sheet_index))).scalars().all()
    ids: list[UUID] = []
    for s in sheets:
        if not force and s.annotations_status == STATUS_DONE:
            continue
        s.annotations_status = STATUS_QUEUED
        ids.append(s.id)
    await session.flush()
    if ids:
        await audit.record(
            session, ctx, action=AuditAction.UPDATE, entity_type="drawing_annotations", entity_id=drawing_id or project_id,
            project_id=project_id, payload={"event": "queue", "sheets": len(ids), "force": force},
        )
    return ids


async def read_sheet_annotations(
    session: AsyncSession, ctx: RequestContext, sheet_id: UUID, gateway: AIGateway | None = None
) -> int:
    """Worker body for one sheet. Returns the number of annotations stored."""
    from app.boq.pdf_ai import default_gateway

    sheet = (await session.execute(select(DrawingSheet).where(DrawingSheet.id == sheet_id))).scalar_one()
    drawing = (await session.execute(select(Drawing).where(Drawing.id == sheet.drawing_id))).scalar_one()
    gw = gateway or default_gateway()
    image_png: bytes | None = None
    if drawing.measure_kind in (DrawingKind.VECTOR_PDF.value, DrawingKind.SCANNED_PDF.value):
        data = await get_object_bytes(drawing.measure_object_key)
        image_png = pdf_mod.render_page_png(data, sheet.sheet_index)
    elif not (sheet.raw_text or "").strip():
        sheet.annotations_status = STATUS_SKIPPED  # a DXF layout with no text has nothing to read
        await session.flush()
        return 0
    meta = AIMeta(project_id=sheet.project_id, entity_type="drawing_sheet", entity_id=str(sheet.id))
    try:
        reading = await read_sheet(
            gw, page_number=sheet.sheet_index + 1, sheet_text=sheet.raw_text or "", image_png=image_png, meta=meta
        )
    except AIError as exc:
        sheet.annotations_status = STATUS_UNAVAILABLE
        sheet.ai_notes = {"unavailable": exc.code}
        await session.flush()
        return 0
    await session.execute(
        delete(DrawingAnnotation).where(DrawingAnnotation.sheet_id == sheet.id, DrawingAnnotation.source == "ai")
    )
    for a in reading.annotations:
        session.add(
            DrawingAnnotation(
                tenant_id=ctx.tenant_id, project_id=sheet.project_id, drawing_id=sheet.drawing_id, sheet_id=sheet.id,
                page=sheet.sheet_index + 1, text=a.text, kind=a.kind, value=a.value, unit=a.unit, material=a.material,
                bbox=a.bbox, source="ai", confidence=reading.confidence, ai_call_id=reading.ai_call_id,
                created_by=ctx.user_id,
            )
        )
    sheet.ai_notes = reading.notes
    sheet.annotations_status = STATUS_DONE
    sheet.annotations_read_at = datetime.now(timezone.utc)
    await session.flush()
    return len(reading.annotations)


async def mark_failed(session: AsyncSession, sheet_id: UUID) -> None:
    sheet = (await session.execute(select(DrawingSheet).where(DrawingSheet.id == sheet_id))).scalar_one_or_none()
    if sheet is not None:
        sheet.annotations_status = STATUS_FAILED
        await session.flush()


async def list_annotations(
    session: AsyncSession, project_id: UUID, *, drawing_id: UUID | None = None, sheet_id: UUID | None = None,
    limit: int = 500, offset: int = 0,
) -> tuple[list[DrawingAnnotation], int]:
    stmt = select(DrawingAnnotation).where(DrawingAnnotation.project_id == project_id)
    if drawing_id:
        stmt = stmt.where(DrawingAnnotation.drawing_id == drawing_id)
    if sheet_id:
        stmt = stmt.where(DrawingAnnotation.sheet_id == sheet_id)
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        await session.execute(stmt.order_by(DrawingAnnotation.drawing_id, DrawingAnnotation.page, DrawingAnnotation.created_at).limit(limit).offset(offset))
    ).scalars().all()
    return list(rows), total


async def summary(session: AsyncSession, project_id: UUID) -> dict[str, int]:
    rows = (
        await session.execute(
            select(DrawingSheet.annotations_status, func.count()).where(DrawingSheet.project_id == project_id).group_by(DrawingSheet.annotations_status)
        )
    ).all()
    out = {"sheets": 0, "done": 0, "queued": 0, "unavailable": 0, "failed": 0, "skipped": 0, "unread": 0}
    for status, n in rows:
        out["sheets"] += n
        out[status if status in out else "unread"] += n
    ann = (await session.execute(select(func.count()).select_from(DrawingAnnotation).where(DrawingAnnotation.project_id == project_id))).scalar_one()
    out["annotations"] = ann
    return out
