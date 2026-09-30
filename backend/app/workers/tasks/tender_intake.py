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

from app.core.config import get_settings
from app.core.context import RequestContext, system_context
from app.intake.constants import DocClass, DocStatus
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


_ROUTE_PRIORITY = {DocClass.DRAWING.value: 0, DocClass.BOQ.value: 1, DocClass.ADDENDUM.value: 3}


async def _claim(session, ids: list[UUID]) -> list[processing.DocSnapshot]:
    """Marks the still-unprocessed documents of a group as being read (the tree shows "reading") and returns what
    the concurrent AI phase needs. Documents that moved on in the meantime are skipped."""
    rows = await session.execute(
        select(ProjectDocument).where(
            ProjectDocument.id.in_(ids), ProjectDocument.status.in_([DocStatus.RECEIVED.value, DocStatus.PROCESSING.value])
        )
    )
    docs = {d.id: d for d in rows.scalars().all()}
    snaps = []
    for doc_id in ids:
        doc = docs.get(doc_id)
        if doc is None:
            continue
        doc.status = DocStatus.PROCESSING.value
        snaps.append(processing.DocSnapshot.of(doc))
    await session.flush()
    return snaps


async def _auto_accept(session, document_id: UUID, tenant_id: UUID) -> bool:
    return await intake_service.auto_accept_document(session, system_context(tenant_id), document_id)


async def _auto_accept_batch(ctx: RequestContext, ids: list[UUID]) -> None:
    """Routes what the AI classified at or above the tenant's threshold. It acts for the system (addenda are a
    lead_estimator-and-above write, and nobody confirmed these), one document per transaction, drawings first so
    an addendum's references resolve against what the same group just routed."""

    async def _kinds(session) -> dict[UUID, str | None]:
        rows = await session.execute(select(ProjectDocument.id, ProjectDocument.doc_class).where(ProjectDocument.id.in_(ids)))
        return {r[0]: r[1] for r in rows.all()}

    kinds = await with_worker_session(ctx, _kinds)
    sctx = system_context(ctx.tenant_id)
    for doc_id in sorted(ids, key=lambda i: _ROUTE_PRIORITY.get(kinds.get(i) or "", 2)):
        try:
            await with_worker_session(sctx, _auto_accept, doc_id, ctx.tenant_id)
        except Exception:  # noqa: BLE001 -- the document simply waits for a person
            logger.exception("tender_intake: auto-accept failed for %s", doc_id)


async def _process_documents(ctx: RequestContext, package_id: UUID | None, ids: list[UUID], project_package_ids: set[UUID] | None = None) -> None:
    settings = get_settings()
    run = processing.AiRun(settings)
    queue = list(ids)
    touched_packages: set[UUID] = set(project_package_ids or ())
    if package_id:
        touched_packages.add(package_id)
    batch_size = max(1, settings.intake_ai_batch_size)

    async def _one(session, document_id: UUID, prepared) -> list[UUID]:
        doc = await processing.get_document(session, document_id)
        touched_packages.add(doc.package_id)
        return await processing.process_document(session, ctx, document_id, prepared, run)

    while queue:
        group, queue = queue[:batch_size], queue[batch_size:]
        snaps = await with_worker_session(ctx, _claim, group)
        prepared = await processing.prepare_batch(ctx, snaps, run)  # the AI calls, a few at a time
        persisted: list[UUID] = []
        for snap in snaps:
            document_id = snap.id
            try:
                queue.extend(await with_worker_session(ctx, _one, document_id, prepared.get(document_id)))
                persisted.append(document_id)
            except Exception as exc:  # noqa: BLE001 -- isolate: record on the document, keep going
                logger.exception("tender_intake: document %s failed", document_id)

                async def _fail(session, doc_id: UUID = document_id, message: str = f"{type(exc).__name__}: {exc}") -> None:
                    await processing.mark_failed(session, ctx, doc_id, message)

                try:
                    await with_worker_session(ctx, _fail)
                except Exception:  # noqa: BLE001
                    logger.exception("tender_intake: could not record failure for %s", document_id)
        await _auto_accept_batch(ctx, persisted)

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
