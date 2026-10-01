"""Resumable tender uploads, per-file dispatch, pack controls and the sweeper (docs/intake-scale/report.md).

The flow, built so that no step holds more than one file in memory and nothing depends on a message surviving in
the broker:

1. **register**: the browser announces every file (path, size, sha256) in batches. Each becomes a
   ``pending_upload`` row (or ``received`` at once when the same bytes are already in the project). The response
   says which files still need their bytes, so re-dropping the same folder after a crash sends only the rest.
2. **upload**: one request per file streams the body straight to S3 (``put_object_from_stream``); the stored digest
   must equal the registered sha256, and only then does the row become ``received``.
3. **dispatch**: the database is the queue. ``claim_for_dispatch`` picks ``received`` files of packs that are not
   paused, bounded by ``INTAKE_DISPATCH_LIMIT`` in flight, marks them ``queued_at`` and the caller enqueues one small
   Celery task per file. A file whose message was lost simply comes back once ``queued_at`` is stale.
4. **sweep**: a file left ``processing`` by a dead worker goes back to ``received`` (or, after too many attempts, is
   parked as failed for a person), and package statuses are recomputed.
5. **pause / resume / cancel** change the pack's status; the dispatcher honours it, the workers re-check it.
"""

from __future__ import annotations

import logging
import asyncio
from collections.abc import AsyncIterator
from datetime import date, datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import bindparam, func, select, text, update
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.context import RequestContext
from app.core.enums import AuditAction
from app.core.errors import ConflictError, NotFoundError, ValidationAppError
from app.integrations.s3 import UploadAborted, put_object_from_stream
from app.intake.constants import DocStatus, Flag, PackageStatus
from app.intake.rules import normalise_folder
from app.intake.safety import ALLOWED_EXTENSIONS, MACRO_EXTENSIONS, extension_of
from app.models.tender_intake import ProjectDocument, TenderPackage
from app.schemas.tender_intake import (
    PackageControlOut,
    RegisteredFileOut,
    RegisterFileIn,
    RegisterPackageIn,
    RegisterPackageOut,
    UploadResult,
)
from app.services import audit
from app.services.projects import assert_can_see_project
from app.services.tender_intake import get_package, refresh_package_status
from app.services.tender_intake_processing import bucket_for, get_document, object_key_for

logger = logging.getLogger(__name__)

_SKIPPED_NAMES = {".ds_store", "thumbs.db", "desktop.ini"}


def _safe_name(path: str) -> str:
    return (path.replace("\\", "/").rsplit("/", 1)[-1].strip() or "unnamed")[:512]


def _reject_reason(f: RegisterFileIn, settings: Settings) -> str | None:
    name = _safe_name(f.path)
    ext = extension_of(name)
    if name.lower() in _SKIPPED_NAMES or name.startswith("~$") or name.startswith("._"):
        return "system file, skipped"
    if f.size <= 0:
        return "empty file"
    if ext in MACRO_EXTENSIONS:
        return f"macro-enabled format .{ext} is not accepted"
    if ext not in ALLOWED_EXTENSIONS:
        return f"file type .{ext or '?'} is not accepted"
    if f.size > settings.intake_max_file_size_bytes:
        return f"larger than the {settings.intake_max_file_size_bytes // (1024 * 1024)} MiB upload limit"
    return None


# --------------------------------------------------------------------------------------- register
async def _unfinished_package(session: AsyncSession, project_id: UUID) -> TenderPackage | None:
    return (
        await session.execute(
            select(TenderPackage)
            .where(TenderPackage.project_id == project_id, TenderPackage.status == PackageStatus.UPLOADING.value)
            .order_by(TenderPackage.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


def _too_many(expected: int, cap: int) -> ValidationAppError:
    return ValidationAppError(
        f"This folder has {expected:,} files; one pack can hold at most {cap:,}. "
        "Split the upload (for example one discipline at a time) or zip some of the folders."
    )


async def register_files(session: AsyncSession, ctx: RequestContext, project_id: UUID, data: RegisterPackageIn) -> RegisterPackageOut:
    settings = get_settings()
    await assert_can_see_project(session, ctx, project_id)
    announced = data.total_files or len(data.files)
    if announced > settings.intake_max_files_per_pack:
        raise _too_many(announced, settings.intake_max_files_per_pack)

    resumed = False
    package: TenderPackage | None = None
    if data.package_id is not None:
        package = await get_package(session, data.package_id)
        if package.project_id != project_id:
            raise NotFoundError(f"Tender package {data.package_id} not found")
        resumed = True
    elif not data.new_package:
        package = await _unfinished_package(session, project_id)
        resumed = package is not None
    if package is not None and package.status == PackageStatus.CANCELLED.value:
        raise ConflictError("This pack was cancelled; start a new upload")
    if package is None:
        package = TenderPackage(
            tenant_id=ctx.tenant_id, project_id=project_id, label=data.label, transmittal_ref=data.transmittal_ref,
            received_date=data.received_date or date.today(), status=PackageStatus.UPLOADING.value, file_count=0,
        )
        session.add(package)
        await session.flush()
    if data.total_files is not None:
        package.expected_count = data.total_files
    elif package.expected_count is None:
        package.expected_count = len(data.files)

    # Rows this pack already has for the announced bytes, and the project's earliest row per sha.
    shas = sorted({f.sha256.lower() for f in data.files})
    in_pack: dict[tuple[str, str, str | None], ProjectDocument] = {}
    earliest: dict[str, ProjectDocument] = {}
    known = list(
        (
            await session.execute(
                select(ProjectDocument)
                .where(ProjectDocument.project_id == project_id, ProjectDocument.sha256.in_(shas))
                .order_by(ProjectDocument.created_at, ProjectDocument.id)
            )
        ).scalars().all()
    )
    by_id = {d.id: d for d in known}
    for doc in known:
        if doc.package_id == package.id:
            in_pack[(doc.sha256, doc.original_filename, doc.archive_path)] = doc
        # Always the root of a chain of copies: the file whose bytes the others wait for (or copy from).
        root = doc
        while root.duplicate_of_id is not None and root.duplicate_of_id in by_id and root.duplicate_of_id != root.id:
            root = by_id[root.duplicate_of_id]
        current = earliest.get(doc.sha256)
        # A row whose bytes are on the server beats one that is still pending.
        if current is None or (current.status == DocStatus.PENDING_UPLOAD.value and root.status != DocStatus.PENDING_UPLOAD.value):
            earliest[doc.sha256] = root

    existing_rows = (
        await session.execute(select(func.count()).select_from(ProjectDocument).where(ProjectDocument.package_id == package.id, ProjectDocument.parent_document_id.is_(None)))
    ).scalar_one()
    out: list[RegisteredFileOut] = []
    created = 0
    now = datetime.now(timezone.utc)
    bucket = bucket_for(settings)
    for f in data.files:
        sha = f.sha256.lower()
        reason = _reject_reason(f, settings)
        if reason is not None:
            out.append(RegisteredFileOut(path=f.path, sha256=sha, document_id=None, state="rejected", upload=False, reason=reason))
            continue
        name = _safe_name(f.path)
        folder = normalise_folder(f.path)
        archive_path = f"{folder}/{name}"[:1024] if folder else None
        known = in_pack.get((sha, name, archive_path))
        if known is not None:
            pending = known.status == DocStatus.PENDING_UPLOAD.value
            # A pending duplicate waits for its original's bytes; the original itself (or any other) must be sent.
            sends = pending and known.duplicate_of_id is None
            out.append(RegisteredFileOut(path=f.path, sha256=sha, document_id=known.id, state="pending" if pending else "uploaded", upload=sends))
            continue
        if existing_rows + created + 1 > settings.intake_max_files_per_pack:
            raise _too_many(existing_rows + created + 1, settings.intake_max_files_per_pack)
        original = earliest.get(sha)
        if original is not None and original.status == DocStatus.PENDING_UPLOAD.value and original.package_id != package.id:
            original = None  # an abandoned pack's pending row: nothing will ever send its bytes, so this file does
        doc = ProjectDocument(
            id=uuid4(), tenant_id=ctx.tenant_id, project_id=project_id, package_id=package.id, original_filename=name,
            ext=extension_of(name), sha256=sha, bucket=bucket, size_bytes=f.size, archive_path=archive_path,
            object_key=original.object_key if original is not None else object_key_for(ctx.tenant_id, sha),
            flags=[Flag.DUPLICATE.value] if original is not None else [],
            duplicate_of_id=original.id if original is not None else None,
        )
        if original is not None and original.status != DocStatus.PENDING_UPLOAD.value:
            doc.status, doc.uploaded_at = DocStatus.RECEIVED.value, now  # the bytes are already here
            state, sends = "uploaded", False
        else:
            doc.status = DocStatus.PENDING_UPLOAD.value
            state, sends = "pending", original is None
        session.add(doc)
        created += 1
        if original is None:
            earliest[sha] = doc
        in_pack[(sha, name, archive_path)] = doc
        out.append(RegisteredFileOut(path=f.path, sha256=sha, document_id=doc.id, state=state, upload=sends))
    await session.flush()

    package.file_count = existing_rows + created
    if package.status in (PackageStatus.READY.value, PackageStatus.FAILED.value):
        package.status = PackageStatus.UPLOADING.value
    await session.flush()
    await refresh_package_status(session, package.id)
    await audit.record(
        session, ctx, action=AuditAction.IMPORT, entity_type="tender_package", entity_id=package.id, project_id=project_id,
        payload={
            "event": "register", "files": len(data.files), "new": created, "resumed": resumed, "label": package.label,
            "expected_count": package.expected_count, "rejected": sum(1 for o in out if o.state == "rejected"),
        },
    )
    return RegisterPackageOut(package_id=package.id, status=package.status, resumed=resumed, expected_count=package.expected_count, files=out)


# ----------------------------------------------------------------------------------------- upload
async def _without_stalls(body: AsyncIterator[bytes], idle_s: float) -> AsyncIterator[bytes]:
    """Yields the body's chunks, but gives up when the sender goes quiet for `idle_s` seconds."""
    iterator = body.__aiter__()
    while True:
        try:
            chunk = await asyncio.wait_for(iterator.__anext__(), idle_s)
        except StopAsyncIteration:
            return
        except asyncio.TimeoutError as exc:
            raise UploadAborted(f"the upload stalled (nothing received for {int(idle_s)} seconds); send it again") from exc
        yield chunk


async def _counts(session: AsyncSession, package_id: UUID) -> tuple[int, int]:
    registered, pending = (
        await session.execute(
            select(
                func.count(),
                func.count().filter(ProjectDocument.status == DocStatus.PENDING_UPLOAD.value),
            ).where(ProjectDocument.package_id == package_id, ProjectDocument.parent_document_id.is_(None))
        )
    ).one()
    return int(registered), int(registered) - int(pending)


async def receive_upload(
    session: AsyncSession, ctx: RequestContext, package_id: UUID, document_id: UUID, body: AsyncIterator[bytes],
    *, declared_size: int | None,
) -> UploadResult:
    """Streams one file's body to S3 and, if its digest is the registered one, makes the document `received`."""
    settings = get_settings()
    doc = await get_document(session, document_id)
    if doc.package_id != package_id:
        raise NotFoundError(f"Document {document_id} is not in package {package_id}")
    package = await get_package(session, package_id)
    await assert_can_see_project(session, ctx, package.project_id)
    if package.status == PackageStatus.CANCELLED.value:
        raise ConflictError("This pack was cancelled")
    if package.status == PackageStatus.PAUSED.value:
        raise ConflictError("This pack is paused; resume it to keep uploading")
    if doc.status != DocStatus.PENDING_UPLOAD.value:
        registered, uploaded = await _counts(session, package_id)
        return UploadResult(
            document_id=doc.id, state="uploaded", package_status=package.status, registered=registered, uploaded=uploaded,
            expected_count=package.expected_count,
        )
    if doc.duplicate_of_id is not None:
        raise ConflictError("These bytes are sent with the first file that has them; nothing to send for this one")
    limit = settings.intake_max_file_size_bytes
    if declared_size is not None and declared_size > limit:
        raise ValidationAppError(f"{doc.original_filename!r} is larger than the {limit // (1024 * 1024)} MiB upload limit")

    try:
        stored = await put_object_from_stream(
            doc.object_key, _without_stalls(body, settings.intake_upload_idle_s), bucket=doc.bucket, expected_sha256=doc.sha256, max_bytes=limit,
            part_bytes=settings.intake_upload_part_bytes,
        )
    except UploadAborted as exc:
        raise ValidationAppError(f"{doc.original_filename!r}: {exc}") from exc

    now = datetime.now(timezone.utc)
    doc.status, doc.uploaded_at, doc.size_bytes = DocStatus.RECEIVED.value, now, stored.size
    await session.flush()
    # Files with the same bytes (waiting on this one, directly or through another copy) arrive with it.
    await session.execute(_ARRIVE_WITH_SQL, {"root": doc.id, "now": now})
    new_status = await refresh_package_status(session, package_id)
    registered, uploaded = await _counts(session, package_id)
    if registered == uploaded and new_status != PackageStatus.UPLOADING.value:
        await audit.record(
            session, ctx, action=AuditAction.IMPORT, entity_type="tender_package", entity_id=package_id, project_id=package.project_id,
            payload={"event": "upload_complete", "files": registered},
        )
    return UploadResult(
        document_id=doc.id, state="uploaded", package_status=new_status, registered=registered, uploaded=uploaded,
        expected_count=package.expected_count,
    )


_ARRIVE_WITH_SQL = text(
    """
    WITH RECURSIVE waiting AS (
        SELECT id FROM project_documents WHERE duplicate_of_id = :root AND status = 'pending_upload'
        UNION
        SELECT d.id FROM project_documents d JOIN waiting w ON d.duplicate_of_id = w.id WHERE d.status = 'pending_upload'
    )
    UPDATE project_documents SET status = 'received', uploaded_at = :now, updated_at = :now
    WHERE id IN (SELECT id FROM waiting)
    """
)


# --------------------------------------------------------------------------------------- controls
async def _package_for_control(session: AsyncSession, ctx: RequestContext, package_id: UUID) -> TenderPackage:
    package = await get_package(session, package_id)
    await assert_can_see_project(session, ctx, package.project_id)
    return package


async def pause_package(session: AsyncSession, ctx: RequestContext, package_id: UUID) -> PackageControlOut:
    package = await _package_for_control(session, ctx, package_id)
    if package.status not in (PackageStatus.UPLOADING.value, PackageStatus.PROCESSING.value):
        raise ConflictError(f"A {package.status} pack cannot be paused")
    before = package.status
    package.status, package.paused_at = PackageStatus.PAUSED.value, datetime.now(timezone.utc)
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.UPDATE, entity_type="tender_package", entity_id=package.id, project_id=package.project_id,
        payload={"event": "pause", "from": before},
    )
    return PackageControlOut(package_id=package.id, status=package.status)


async def resume_package(session: AsyncSession, ctx: RequestContext, package_id: UUID) -> PackageControlOut:
    package = await _package_for_control(session, ctx, package_id)
    if package.status != PackageStatus.PAUSED.value:
        raise ConflictError(f"A {package.status} pack is not paused")
    package.status, package.paused_at = PackageStatus.PROCESSING.value, None
    await session.flush()
    status = await refresh_package_status(session, package_id)
    await audit.record(
        session, ctx, action=AuditAction.UPDATE, entity_type="tender_package", entity_id=package.id, project_id=package.project_id,
        payload={"event": "resume", "to": status},
    )
    return PackageControlOut(package_id=package.id, status=status)


async def cancel_package(session: AsyncSession, ctx: RequestContext, package_id: UUID) -> PackageControlOut:
    """Stops the pack for good: everything not yet read (waiting for bytes, queued, being read) is excluded, with
    the reason on it. Files already classified or routed are left exactly as they are."""
    package = await _package_for_control(session, ctx, package_id)
    if package.status in (PackageStatus.CANCELLED.value, PackageStatus.READY.value, PackageStatus.FAILED.value):
        raise ConflictError(f"A {package.status} pack cannot be cancelled")
    now = datetime.now(timezone.utc)
    result = await session.execute(
        update(ProjectDocument)
        .where(
            ProjectDocument.package_id == package_id,
            ProjectDocument.status.in_([DocStatus.PENDING_UPLOAD.value, DocStatus.RECEIVED.value, DocStatus.PROCESSING.value]),
        )
        .values(status=DocStatus.EXCLUDED.value, error_message="excluded: pack cancelled", queued_at=None, updated_at=now)
        .returning(ProjectDocument.id)
    )
    cancelled = len(result.all())
    package.status, package.cancelled_at = PackageStatus.CANCELLED.value, now
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.UPDATE, entity_type="tender_package", entity_id=package.id, project_id=package.project_id,
        payload={"event": "cancel", "excluded_documents": cancelled},
    )
    return PackageControlOut(package_id=package.id, status=package.status, cancelled_documents=cancelled)


# ------------------------------------------------------------------------------------- dispatch
_INFLIGHT_SQL = text(
    """
    SELECT count(*) FROM project_documents
    WHERE tenant_id = :tenant
      AND ((status = 'received' AND queued_at IS NOT NULL AND queued_at > now() - make_interval(secs => :requeue))
        OR (status = 'processing' AND updated_at > now() - make_interval(secs => :stuck)))
    """
)

# Files the dispatcher may hand out: received, their pack not paused/cancelled, not retried to death, and (for a file
# whose bytes duplicate another's) only once that other file has been read, so it can copy the answer.
_CLAIM_SQL = text(
    """
    WITH cand AS (
        SELECT d.id FROM project_documents d
        JOIN tender_packages p ON p.id = d.package_id
        WHERE d.tenant_id = :tenant
          AND d.status = 'received'
          AND (d.queued_at IS NULL OR d.queued_at < now() - make_interval(secs => :requeue))
          AND d.attempts < :max_attempts
          AND p.status NOT IN ('paused', 'cancelled')
          AND (CAST(:package AS uuid) IS NULL OR d.package_id = CAST(:package AS uuid))
          AND (d.duplicate_of_id IS NULL OR EXISTS (
                SELECT 1 FROM project_documents o
                WHERE o.id = d.duplicate_of_id AND o.status NOT IN ('pending_upload', 'received', 'processing')))
        ORDER BY d.created_at, d.id
        LIMIT :n
        FOR UPDATE OF d SKIP LOCKED
    )
    UPDATE project_documents d SET queued_at = now(), updated_at = now()
    FROM cand WHERE d.id = cand.id
    RETURNING d.id
    """
).bindparams(bindparam("package", type_=PG_UUID(as_uuid=True)))


async def claim_for_dispatch(session: AsyncSession, tenant_id: UUID, *, package_id: UUID | None = None) -> list[UUID]:
    """Marks the next files as queued and returns their ids; the caller commits, then enqueues one task each.
    Nothing is claimed beyond `intake_dispatch_limit` files in flight, which is what keeps a 3,000-file pack from
    putting 3,000 messages (and 3,000 open downloads) into the system at once."""
    settings = get_settings()
    inflight = (
        await session.execute(
            _INFLIGHT_SQL, {"tenant": tenant_id, "requeue": settings.intake_requeue_after_s, "stuck": settings.intake_stuck_after_s}
        )
    ).scalar_one()
    room = settings.intake_dispatch_limit - int(inflight)
    if room <= 0:
        return []
    rows = await session.execute(
        _CLAIM_SQL,
        {
            "tenant": tenant_id, "requeue": settings.intake_requeue_after_s, "max_attempts": settings.intake_max_attempts,
            "package": package_id, "n": room,
        },
    )
    return [r[0] for r in rows.all()]


async def release_claims(session: AsyncSession, ids: list[UUID]) -> None:
    """The broker refused the message: let the next dispatch pass pick these files up again."""
    if ids:
        await session.execute(update(ProjectDocument).where(ProjectDocument.id.in_(ids)).values(queued_at=None))


# ---------------------------------------------------------------------------------- the sweeper
_STUCK_SQL = text(
    """
    UPDATE project_documents
    SET status = CASE WHEN attempts >= :max_attempts THEN 'failed' ELSE 'received' END,
        queued_at = NULL,
        updated_at = now(),
        error_message = CASE WHEN attempts >= :max_attempts
            THEN 'Reading stopped repeatedly (the worker died or timed out). Re-run it, or classify it yourself.'
            ELSE error_message END
    WHERE tenant_id = :tenant AND status = 'processing'
      AND updated_at < now() - make_interval(secs => :stuck)
    RETURNING id, package_id, status
    """
)


async def reap_stuck_documents(session: AsyncSession, tenant_id: UUID) -> dict[str, int]:
    """Intake files the workers abandoned: `processing` with no sign of life for `intake_stuck_after_s`. They go back
    to `received` (picked up again by the dispatcher) until `intake_max_attempts`, then are parked as failed with a
    reason a person can act on. Also recomputes the status of every pack that is still working."""
    settings = get_settings()
    rows = (
        await session.execute(
            _STUCK_SQL, {"tenant": tenant_id, "stuck": settings.intake_stuck_after_s, "max_attempts": settings.intake_max_attempts}
        )
    ).all()
    requeued = sum(1 for r in rows if r.status == DocStatus.RECEIVED.value)
    failed = len(rows) - requeued
    open_packages = (
        await session.execute(
            select(TenderPackage.id).where(
                TenderPackage.tenant_id == tenant_id,
                TenderPackage.status.in_([PackageStatus.PROCESSING.value, PackageStatus.UPLOADING.value]),
            )
        )
    ).scalars().all()
    for pid in open_packages:
        await refresh_package_status(session, pid)
    return {"requeued": requeued, "failed": failed, "packages": len(open_packages)}


__all__ = [
    "cancel_package",
    "claim_for_dispatch",
    "pause_package",
    "reap_stuck_documents",
    "receive_upload",
    "register_files",
    "release_claims",
    "resume_package",
]
