"""Tender intake worker (docs/tender-intake-plan.md, section 11).

Runs on the existing ``ingest`` queue. Each document is processed in its own
committed session (claim-first style): a failure on one document is recorded
on that document from an independent session and never rolls back, or stops,
the rest of the package. A zip's members are created by the parent's session
and processed afterwards, so expansion and classification never share a
transaction.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select

from app.core.context import RequestContext
from app.intake.constants import DocStatus
from app.models.tender_intake import ProjectDocument
from app.services import tender_intake as intake_service
from app.services import tender_intake_processing as processing
from app.workers.base import build_worker_context, run_async, with_worker_session
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


async def _pending_ids(session, package_id: UUID) -> list[UUID]:
    rows = await session.execute(
        select(ProjectDocument.id)
        .where(ProjectDocument.package_id == package_id, ProjectDocument.status == DocStatus.RECEIVED.value)
        .order_by(ProjectDocument.created_at, ProjectDocument.id)
    )
    return list(rows.scalars().all())


async def _process_documents(ctx: RequestContext, package_id: UUID | None, ids: list[UUID], project_package_ids: set[UUID] | None = None) -> None:
    queue = list(ids)
    touched_packages: set[UUID] = set(project_package_ids or ())
    if package_id:
        touched_packages.add(package_id)

    async def _one(session, document_id: UUID) -> list[UUID]:
        doc = await processing.get_document(session, document_id)
        touched_packages.add(doc.package_id)
        return await processing.process_document(session, ctx, document_id)

    while queue:
        document_id = queue.pop(0)
        try:
            queue.extend(await with_worker_session(ctx, _one, document_id))
        except Exception as exc:  # noqa: BLE001 -- isolate: record on the document, keep going
            logger.exception("tender_intake: document %s failed", document_id)

            async def _fail(session, doc_id: UUID = document_id, message: str = f"{type(exc).__name__}: {exc}") -> None:
                await processing.mark_failed(session, ctx, doc_id, message)

            try:
                await with_worker_session(ctx, _fail)
            except Exception:  # noqa: BLE001
                logger.exception("tender_intake: could not record failure for %s", document_id)

    async def _finalize(session, pid: UUID) -> None:
        await intake_service.refresh_package_status(session, pid)

    for pid in touched_packages:
        await with_worker_session(ctx, _finalize, pid)


async def _process_package(ctx: RequestContext, package_id: str, document_ids: list[str] | None) -> None:
    pid = UUID(package_id)
    ids = [UUID(i) for i in document_ids] if document_ids else await with_worker_session(ctx, _pending_ids, pid)
    await _process_documents(ctx, pid, ids)


@celery_app.task(bind=True, name="app.workers.tasks.tender_intake.process_tender_package", soft_time_limit=1800)
def process_tender_package(
    self, package_id: str, tenant_id: str, actor_user_id: str | None, actor_roles: list[str] | None = None,
    document_ids: list[str] | None = None,
) -> None:
    ctx = build_worker_context(tenant_id, actor_user_id, actor_roles)
    run_async(lambda: _process_package(ctx, package_id, document_ids))()


@celery_app.task(bind=True, name="app.workers.tasks.tender_intake.rerun_document", soft_time_limit=300)
def rerun_document(self, document_id: str, tenant_id: str, actor_user_id: str | None, actor_roles: list[str] | None = None) -> None:
    ctx = build_worker_context(tenant_id, actor_user_id, actor_roles)
    run_async(lambda: _process_documents(ctx, None, [UUID(document_id)]))()
