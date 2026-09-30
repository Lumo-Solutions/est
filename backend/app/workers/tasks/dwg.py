"""DWG conversion task (queue `convert`).

    upload/intake -> trigger_ingest -> convert_dwg -> index_sheets -> (normal DXF chord)

`convert_dwg` runs on its own queue and worker so a slow or hostile DWG can
only ever hold up other conversions, never DXF/PDF ingestion. The DWG itself
is only ever opened inside the sandboxed converter container
(app/integrations/dwg_converter.py); this task just moves bytes between S3
and the spool volume.

Failure handling is deliberately NOT the raise-and-retry shape the rest of
the takeoff pipeline uses. Every failure -- converter missing or stopped,
corrupt file, timeout, an S3 error -- is written onto the drawing as
`needs_conversion` with a reason and the manual workaround, and the task
then returns normally, so the write commits (worker_session_scope rolls
back on an exception; see app/workers/tasks/takeoff.py's docstring) and the
drawing can never be left stuck in `converting`. A crash mid-task (worker
killed) is the one case that can: maintenance.reap_stuck_drawings resolves
those to needs_conversion too.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.context import RequestContext
from app.core.enums import AuditAction, DrawingStatus
from app.core.logging import get_logger
from app.integrations import dwg_converter
from app.integrations.dwg_converter import ConversionError
from app.integrations.s3 import get_object_bytes, put_object_streaming
from app.models.takeoff import Drawing
from app.services import audit
from app.workers.base import build_worker_context, run_async, with_worker_session
from app.workers.celery_app import celery_app

logger = get_logger(__name__)

_settings = get_settings()


def derived_object_key(drawing: Drawing) -> str:
    """Content-addressed by the ORIGINAL's sha256, so a re-conversion of the
    same bytes overwrites itself rather than piling up copies."""
    return f"projects/{drawing.project_id}/drawings/derived/{drawing.sha256}.dxf"


async def _claim_body(session: AsyncSession, drawing_id: str) -> bool:
    drawing = (await session.execute(select(Drawing).where(Drawing.id == UUID(drawing_id)))).scalar_one()
    if not drawing.is_dwg:
        return False
    drawing.status = DrawingStatus.CONVERTING.value
    drawing.error_message = None
    drawing.conversion_reason = None
    await session.flush()
    return True


async def _mark_needs_conversion(
    session: AsyncSession, ctx: RequestContext, drawing: Drawing, reason: str, message: str
) -> None:
    drawing.status = DrawingStatus.NEEDS_CONVERSION.value
    drawing.error_message = f"{message} {dwg_converter.MANUAL_WORKAROUND}"
    drawing.conversion_reason = reason
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.UPDATE, entity_type="drawing", entity_id=drawing.id,
        project_id=drawing.project_id, payload={"event": "dwg_conversion_failed", "reason": reason},
    )


async def _convert_body(session: AsyncSession, ctx: RequestContext, drawing_id: str) -> bool:
    """Returns True when the drawing now has a derived DXF (caller then
    starts the normal pipeline), False when it was parked in needs_conversion."""
    t0 = time.monotonic()
    drawing = (await session.execute(select(Drawing).where(Drawing.id == UUID(drawing_id)))).scalar_one()
    try:
        if drawing.derived_object_key:
            # Re-ingest of an already-converted drawing: the derived DXF is a
            # pure function of the original, so reuse it. (A failed attempt
            # never sets derived_object_key, so a retry always converts.)
            return True

        dwg_converter.check_available()
        original = await get_object_bytes(drawing.object_key)
        # Blocking file-poll on the spool volume: off the event loop.
        result = await asyncio.to_thread(dwg_converter.convert_dwg_to_dxf, original)
        key = derived_object_key(drawing)
        sha = await put_object_streaming(key, result.dxf, "application/dxf")

        drawing.derived_object_key = key
        drawing.derived_sha256 = sha
        drawing.derived_size_bytes = len(result.dxf)
        drawing.converter_version = result.converter_version
        drawing.conversion_target = result.target_version
        drawing.converted_at = datetime.now(timezone.utc)
        drawing.conversion_ms = result.duration_ms
        drawing.conversion_reason = None
        drawing.error_message = None
        await session.flush()
        await audit.record(
            session, ctx, action=AuditAction.UPDATE, entity_type="drawing", entity_id=drawing.id,
            project_id=drawing.project_id,
            payload={
                "event": "dwg_converted", "converter_version": result.converter_version,
                "target": result.target_version, "derived_sha256": sha, "ms": result.duration_ms,
            },
        )
        return True
    except ConversionError as exc:
        logger.warning("dwg conversion failed for drawing %s: %s (%s)", drawing_id, exc.message, exc.reason)
        await _mark_needs_conversion(session, ctx, drawing, exc.reason, exc.message)
        return False
    except Exception as exc:  # noqa: BLE001 -- must never leave the drawing in `converting`
        logger.exception("dwg conversion crashed for drawing %s after %.1fs", drawing_id, time.monotonic() - t0)
        await _mark_needs_conversion(
            session, ctx, drawing, dwg_converter.R_FAILED,
            f"The DWG could not be converted ({type(exc).__name__}).",
        )
        return False


@celery_app.task(
    bind=True, name="app.workers.tasks.dwg.convert_dwg",
    soft_time_limit=_settings.dwg_convert_timeout_s * 2 + 60,
)
def convert_dwg(self, drawing_id: str, tenant_id: str, actor_user_id: str | None, actor_roles: list[str] | None = None) -> None:
    ctx = build_worker_context(tenant_id, actor_user_id, actor_roles)

    async def _run() -> None:
        if not await with_worker_session(ctx, _claim_body, drawing_id):
            return
        converted = await with_worker_session(ctx, _convert_body, ctx, drawing_id)
        if converted:
            from app.workers.tasks.takeoff import index_sheets

            index_sheets.delay(drawing_id, tenant_id, actor_user_id, actor_roles)

    run_async(_run)()

