"""AI-assisted reading workers: PDF BOQ extraction and drawing annotation reading.

Runs on the existing ``vlm`` queue (the model-backed worker). Progress and
failures are written from independent sessions so the UI can poll a running
job and a failure is recorded even though the task's own transaction rolls back.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select

from app.core.context import RequestContext
from app.models.boq import BoqPdfExtraction
from app.services import annotations as annotations_service
from app.services import boq_pdf as boq_pdf_service
from app.workers.base import build_worker_context, run_async, with_worker_session
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


async def _set_progress(ctx: RequestContext, extraction_id: UUID, done: int, total: int, summary: list[dict]) -> None:
    async def _w(session) -> None:
        ex = (await session.execute(select(BoqPdfExtraction).where(BoqPdfExtraction.id == extraction_id))).scalar_one()
        ex.pages_done, ex.pages_total, ex.page_summary = done, total, summary
        await session.flush()

    await with_worker_session(ctx, _w)


async def _claim_extraction(ctx: RequestContext, extraction_id: UUID) -> None:
    async def _w(session) -> None:
        ex = (await session.execute(select(BoqPdfExtraction).where(BoqPdfExtraction.id == extraction_id))).scalar_one()
        if ex.status in ("queued", "failed"):
            ex.status, ex.error, ex.pages_done = "running", None, 0
            await session.flush()

    await with_worker_session(ctx, _w)


async def _mark_extraction_failed(ctx: RequestContext, extraction_id: UUID, message: str) -> None:
    async def _w(session) -> None:
        ex = (await session.execute(select(BoqPdfExtraction).where(BoqPdfExtraction.id == extraction_id))).scalar_one_or_none()
        if ex is not None and ex.status != "committed":
            ex.status, ex.error = "failed", message[:500]
            await session.flush()

    await with_worker_session(ctx, _w)


async def _extract(ctx: RequestContext, extraction_id: str) -> None:
    eid = UUID(extraction_id)

    async def progress(done: int, total: int, summary: list[dict]) -> None:
        await _set_progress(ctx, eid, done, total, summary)

    async def _body(session) -> None:
        await boq_pdf_service.run_extraction(session, ctx, eid, progress)

    try:
        await _claim_extraction(ctx, eid)
        await with_worker_session(ctx, _body)
    except Exception as exc:  # noqa: BLE001 -- recorded on the extraction, from an independent session
        logger.exception("boq_pdf: extraction %s failed", extraction_id)
        await _mark_extraction_failed(ctx, eid, f"{type(exc).__name__}: {exc}")


@celery_app.task(bind=True, name="app.workers.tasks.ai_reading.extract_boq_pdf", soft_time_limit=3000)
def extract_boq_pdf(self, extraction_id: str, tenant_id: str, actor_user_id: str | None, actor_roles: list[str] | None = None) -> None:
    ctx = build_worker_context(tenant_id, actor_user_id, actor_roles)
    run_async(lambda: _extract(ctx, extraction_id))()


async def _read_sheets(ctx: RequestContext, sheet_ids: list[str]) -> None:
    for sid in sheet_ids:
        sheet_id = UUID(sid)

        async def _one(session, sheet_id: UUID = sheet_id) -> None:
            await annotations_service.read_sheet_annotations(session, ctx, sheet_id)

        try:
            await with_worker_session(ctx, _one)
        except Exception:  # noqa: BLE001 -- one bad sheet must not stop the rest
            logger.exception("annotations: sheet %s failed", sid)

            async def _fail(session, sheet_id: UUID = sheet_id) -> None:
                await annotations_service.mark_failed(session, sheet_id)

            try:
                await with_worker_session(ctx, _fail)
            except Exception:  # noqa: BLE001
                logger.exception("annotations: could not record failure for %s", sid)


@celery_app.task(bind=True, name="app.workers.tasks.ai_reading.read_sheet_annotations", soft_time_limit=3000)
def read_sheet_annotations(self, sheet_ids: list[str], tenant_id: str, actor_user_id: str | None, actor_roles: list[str] | None = None) -> None:
    ctx = build_worker_context(tenant_id, actor_user_id, actor_roles)
    run_async(lambda: _read_sheets(ctx, sheet_ids))()
