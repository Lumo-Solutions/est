"""Tender intake worker (docs/tender-intake-plan.md section 11, docs/intake-scale/report.md).

One small Celery task per file, driven by the database:

* ``dispatch_intake`` claims ``received`` files (bounded by ``INTAKE_DISPATCH_LIMIT`` in flight, packs that are
  paused or cancelled are skipped) and enqueues ``process_intake_file`` for each. A file's ``queued_at`` is the only
  record that a message exists, so a message lost with the broker simply expires and the file is enqueued again.
* ``process_intake_file`` reads one file: claim it (``received -> processing``, attempts + 1), prepare (download, safety,
  extract, rules, the AI call) with no database session open, persist the proposal, auto-accept. Each step that writes
  uses its own committed session, so a failure is recorded on the document from an independent session and never
  rolls back anything else. A file that is too big, has too many pages or takes too long is parked under "Needs your
  check" instead of failing; a file whose worker keeps dying is retried up to ``INTAKE_MAX_ATTEMPTS`` times.
* ``intake_tick`` (celery-beat, every 30 s) is the sweeper and the safety net: files abandoned in ``processing`` by a dead
  worker go back to ``received``, pack statuses are recomputed and the dispatcher runs.

The tasks run with the system context for the document's tenant: classification is not an act of any one person
(the uploader's identity is on the upload audit entries; reading is attributed to the system).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import select, update

from app.core.config import get_settings
from app.core.context import RequestContext, system_context
from app.db.session import session_scope
from app.intake.constants import DocStatus, PackageStatus
from app.models.tender_intake import ProjectDocument, TenderPackage
from app.services import tender_intake as intake_service
from app.services import tender_intake_processing as processing
from app.services import tender_intake_upload as upload_service
from app.workers.base import run_async, with_worker_session
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)
_NIL_TENANT = "00000000-0000-0000-0000-000000000000"


def _limit(name: str, default: int) -> int:
    try:
        return getattr(get_settings(), name)
    except Exception:  # noqa: BLE001 -- decorating a task must not need a full environment
        return default


# ------------------------------------------------------------------------------------ dispatching
def enqueue_documents(ids: list[UUID], tenant_id: UUID) -> list[UUID]:
    """Sends one `process_intake_file` message per document; returns the ids the broker refused."""
    refused: list[UUID] = []
    for doc_id in ids:
        try:
            process_intake_file.apply_async(args=(str(doc_id), str(tenant_id)))
        except Exception:  # noqa: BLE001 -- broker down: the claim is released and the next pass tries again
            logger.exception("tender_intake: could not enqueue %s", doc_id)
            refused.append(doc_id)
    return refused


async def _claim_batch(session, tenant_id: UUID, package_id: UUID | None) -> list[UUID]:
    return await upload_service.claim_for_dispatch(session, tenant_id, package_id=package_id)


async def _release(session, ids: list[UUID]) -> None:
    await upload_service.release_claims(session, ids)


async def dispatch_for_tenant(tenant_id: UUID, package_id: UUID | None = None) -> int:
    ctx = system_context(tenant_id)
    claimed = await with_worker_session(ctx, _claim_batch, tenant_id, package_id)  # committed before any message is sent
    if not claimed:
        return 0
    refused = enqueue_documents(claimed, tenant_id)
    if refused:
        await with_worker_session(ctx, _release, refused)
    return len(claimed) - len(refused)


@celery_app.task(name="app.workers.tasks.tender_intake.dispatch_intake")
def dispatch_intake(tenant_id: str, package_id: str | None = None) -> int:
    """Enqueue the next files of a tenant (optionally one pack). Safe to call at any time, from anywhere, any number
    of times: the claim is atomic."""
    return run_async(lambda: dispatch_for_tenant(UUID(tenant_id), UUID(package_id) if package_id else None))()


# ------------------------------------------------------------------------------ one file, end to end
async def _claim(session, document_id: UUID) -> processing.DocSnapshot | None:
    """received -> processing (attempts + 1) for a file whose pack is running. A `processing` file whose last sign of
    life is older than the stuck threshold is taken over too: its worker is dead (the broker redelivered the message)."""
    settings = get_settings()
    row = (
        await session.execute(
            select(ProjectDocument)
            .where(ProjectDocument.id == document_id)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)  # the dispatcher and the sweeper change rows with plain SQL
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    package = (await session.execute(select(TenderPackage).where(TenderPackage.id == row.package_id))).scalar_one()
    if package.status in (PackageStatus.PAUSED.value, PackageStatus.CANCELLED.value):
        row.queued_at = None  # waits for resume
        await session.flush()
        return None
    if row.status == DocStatus.PROCESSING.value:
        age = (datetime.now(timezone.utc) - row.updated_at).total_seconds()
        if age < settings.intake_stuck_after_s:
            return None  # a live worker has it
    elif row.status != DocStatus.RECEIVED.value:
        return None
    if row.attempts >= settings.intake_max_attempts:
        row.status = DocStatus.FAILED.value
        row.error_message = "Reading stopped repeatedly (the worker died or timed out). Re-run it, or classify it yourself."
        await session.flush()
        return None
    row.status = DocStatus.PROCESSING.value
    row.attempts = (row.attempts or 0) + 1
    await session.flush()
    return processing.DocSnapshot.of(row)


async def _persist(session, ctx: RequestContext, document_id: UUID, prepared) -> list[UUID]:
    return await processing.process_document(session, ctx, document_id, prepared)


async def _auto_accept(session, ctx: RequestContext, document_id: UUID) -> bool:
    return await intake_service.auto_accept_document(session, ctx, document_id)


async def _finalize(session, package_id: UUID) -> None:
    await intake_service.refresh_package_status(session, package_id)


async def _package_of(session, document_id: UUID) -> UUID | None:
    return (await session.execute(select(ProjectDocument.package_id).where(ProjectDocument.id == document_id))).scalar_one_or_none()


async def _fail_or_retry(session, ctx: RequestContext, document_id: UUID, message: str) -> None:
    """A failure that is not about the file's size: try again later, and after `intake_max_attempts` park it as failed."""
    doc = await processing.get_document(session, document_id)
    if doc.status not in (DocStatus.PROCESSING.value, DocStatus.RECEIVED.value):
        return
    if (doc.attempts or 0) < get_settings().intake_max_attempts:
        # An explicit UPDATE: the dispatcher set queued_at with plain SQL, so an ORM "set to None" could look unchanged.
        await session.execute(
            update(ProjectDocument)
            .where(ProjectDocument.id == doc.id)
            .values(status=DocStatus.RECEIVED.value, queued_at=None, error_message=f"retrying after: {message}"[:500])
        )
        await session.refresh(doc)
        return
    await processing.mark_failed(session, ctx, document_id, message)


async def _park(session, ctx: RequestContext, document_id: UUID, why: str) -> None:
    doc = await processing.get_document(session, document_id)
    if doc.status in (DocStatus.PROCESSING.value, DocStatus.RECEIVED.value):
        await processing.park_for_check(session, ctx, doc, why)


async def process_one(tenant_id: UUID, document_id: UUID) -> None:
    settings = get_settings()
    ctx = system_context(tenant_id)
    snap = await with_worker_session(ctx, _claim, document_id)
    if snap is None:
        return
    shared = processing.SharedBreaker(settings.redis_url, tenant_id, settings)
    run = processing.AiRun(settings, shared)
    package_id: UUID | None = None
    try:
        prepared = None if snap.is_duplicate else await processing.prepare_one(ctx, snap, run)
        children = await with_worker_session(ctx, _persist, ctx, document_id, prepared)
        del prepared  # the file's bytes can go now
        try:
            await with_worker_session(ctx, _auto_accept, ctx, document_id)
        except Exception:  # noqa: BLE001 -- the document simply waits for a person
            logger.exception("tender_intake: auto-accept failed for %s", document_id)
        if children:
            logger.info("tender_intake: %s expanded into %d files", document_id, len(children))
    except SoftTimeLimitExceeded:
        limit = settings.intake_task_soft_limit_s
        await with_worker_session(ctx, _park, ctx, document_id, f"reading it took longer than {limit} seconds")
    except Exception as exc:  # noqa: BLE001 -- isolate: record on the document, keep going
        logger.exception("tender_intake: document %s failed", document_id)
        try:
            await with_worker_session(ctx, _fail_or_retry, ctx, document_id, f"{type(exc).__name__}: {exc}")
        except Exception:  # noqa: BLE001
            logger.exception("tender_intake: could not record failure for %s", document_id)
    finally:
        try:
            package_id = await with_worker_session(ctx, _package_of, document_id)
            if package_id:
                await with_worker_session(ctx, _finalize, package_id)
        except Exception:  # noqa: BLE001
            logger.exception("tender_intake: could not refresh the package status for %s", document_id)
    # This file is done: pull the next ones in (keeps the pipeline full without waiting for the next tick).
    try:
        await dispatch_for_tenant(tenant_id)
    except Exception:  # noqa: BLE001 -- the tick will do it
        logger.exception("tender_intake: dispatch after %s failed", document_id)


@celery_app.task(
    bind=True,
    name="app.workers.tasks.tender_intake.process_intake_file",
    soft_time_limit=_limit("intake_task_soft_limit_s", 240),
    time_limit=_limit("intake_task_hard_limit_s", 300),
    acks_late=True,
)
def process_intake_file(self, document_id: str, tenant_id: str) -> None:
    run_async(lambda: process_one(UUID(tenant_id), UUID(document_id)))()


@celery_app.task(name="app.workers.tasks.tender_intake.process_tender_package")
def process_tender_package(
    package_id: str, tenant_id: str, actor_user_id: str | None = None, actor_roles: list[str] | None = None,
    document_ids: list[str] | None = None,
) -> None:
    """Kept so messages from before the per-file design still drain: it just asks the dispatcher to run."""
    run_async(lambda: dispatch_for_tenant(UUID(tenant_id), UUID(package_id)))()


# ----------------------------------------------------------------------------------- sweeper / tick
async def _reap(session, tenant_id: UUID) -> dict[str, int]:
    return await upload_service.reap_stuck_documents(session, tenant_id)


async def tick_all_tenants() -> dict[str, int]:
    from app.models.tenancy import Tenant

    async with session_scope(system_context(UUID(_NIL_TENANT))) as session:
        tenant_ids = [row[0] for row in (await session.execute(select(Tenant.id).where(Tenant.is_active.is_(True)))).all()]
    totals = {"requeued": 0, "failed": 0, "dispatched": 0}
    for tenant_id in tenant_ids:
        stats = await with_worker_session(system_context(tenant_id), _reap, tenant_id)
        totals["requeued"] += stats["requeued"]
        totals["failed"] += stats["failed"]
        totals["dispatched"] += await dispatch_for_tenant(tenant_id)
    return totals


@celery_app.task(name="app.workers.tasks.tender_intake.intake_tick")
def intake_tick() -> dict[str, int]:
    """Beat, every 30 s: reap abandoned files, recompute pack statuses, then dispatch."""
    return run_async(tick_all_tenants)()
