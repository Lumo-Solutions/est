from __future__ import annotations

import hashlib
import hmac
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.enums import CertificateStatus, DrawingStatus, ExtractionJobStatus
from app.db.session import session_scope
from app.models.audit import AuditCheckpoint
from app.models.prequal import CertificateAlert, VendorCertificate
from app.models.takeoff import Drawing, ExtractionJob
from app.models.tenancy import Tenant
from app.services.audit import get_chain_head, verify_chain
from app.workers.base import run_async, system_ctx, with_worker_session
from app.workers.celery_app import celery_app
from app.workers.tasks.takeoff import aggregate_drawing_status

_STALE_JOB_TIMEOUT = timedelta(hours=1)
_NIL_TENANT = "00000000-0000-0000-0000-000000000000"


async def _all_tenant_ids() -> list[str]:
    """`tenants` carries no tenant_id column and has no RLS policy of its
    own (see migration 0002), so any session can list it -- the nil-UUID
    context here just satisfies session_scope()'s signature."""
    async with session_scope(system_ctx(_NIL_TENANT)) as session:
        result = await session.execute(select(Tenant.id).where(Tenant.is_active.is_(True)))
        return [str(row[0]) for row in result.all()]


async def _scan_certificate_expiry_body(session: AsyncSession, tenant_id: str) -> int:
    today = date.today()
    warn_window_days = 90  # widest warn_days_before we expect; narrowed below per-cert
    result = await session.execute(
        select(VendorCertificate).where(
            VendorCertificate.expiry_date.is_not(None),
            VendorCertificate.expiry_date <= today + timedelta(days=warn_window_days),
            VendorCertificate.status.in_([CertificateStatus.VALID.value, CertificateStatus.EXPIRING.value]),
        )
    )
    created = 0
    for cert in result.scalars().all():
        assert cert.expiry_date is not None
        days_left = (cert.expiry_date - today).days
        if days_left > 60:
            continue  # not within the default warn window yet
        new_status = CertificateStatus.EXPIRED.value if days_left < 0 else CertificateStatus.EXPIRING.value
        if cert.status != new_status:
            cert.status = new_status
        alert_type = "expired" if days_left < 0 else "expiring"
        already_alerted = await session.execute(
            select(CertificateAlert).where(
                CertificateAlert.vendor_certificate_id == cert.id, CertificateAlert.alert_type == alert_type
            )
        )
        if already_alerted.scalars().first() is not None:
            continue
        session.add(
            CertificateAlert(
                tenant_id=cert.tenant_id, vendor_certificate_id=cert.id, alert_type=alert_type,
                due_date=cert.expiry_date,
            )
        )
        created += 1
    await session.flush()
    return created


@celery_app.task(name="app.workers.tasks.maintenance.scan_certificate_expiry")
def scan_certificate_expiry() -> None:
    async def _run() -> None:
        for tenant_id in await _all_tenant_ids():
            await with_worker_session(system_ctx(tenant_id), _scan_certificate_expiry_body, tenant_id)

    run_async(_run)()


async def _write_checkpoint_body(session: AsyncSession, tenant_id: str) -> None:
    settings = get_settings()
    today = date.today()
    head_seq, head_hash = await get_chain_head(session, UUID(tenant_id), today)
    if head_seq == 0:
        return
    payload = f"{tenant_id}|{today.isoformat()}|{head_seq}|{head_hash}"
    checkpoint_hmac = hmac.new(
        settings.audit_checkpoint_hmac_key.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    session.add(
        AuditCheckpoint(
            tenant_id=UUID(tenant_id), chain_date=today, head_seq=head_seq,
            head_hash=head_hash, hmac=checkpoint_hmac, created_at=datetime.now(timezone.utc),
        )
    )
    await session.flush()


@celery_app.task(name="app.workers.tasks.maintenance.write_audit_checkpoints")
def write_audit_checkpoints() -> None:
    async def _run() -> None:
        for tenant_id in await _all_tenant_ids():
            await with_worker_session(system_ctx(tenant_id), _write_checkpoint_body, tenant_id)

    run_async(_run)()


async def _verify_chain_body(session: AsyncSession, tenant_id: str) -> None:
    today = date.today()
    await verify_chain(session, UUID(tenant_id), today - timedelta(days=7), today)


@celery_app.task(name="app.workers.tasks.maintenance.verify_audit_chain_all_tenants")
def verify_audit_chain_all_tenants() -> None:
    """Raises (and lets Celery record the task failure) if any tenant's
    chain fails verification in the trailing 7 days -- see
    services/audit.py::verify_chain and docs/audit-chain.md for the
    operational runbook on what to do if this fires."""

    async def _run() -> None:
        for tenant_id in await _all_tenant_ids():
            await with_worker_session(system_ctx(tenant_id), _verify_chain_body, tenant_id)

    run_async(_run)()


async def _reap_stale_jobs_body(session: AsyncSession, tenant_id: str) -> int:
    cutoff = datetime.now(timezone.utc) - _STALE_JOB_TIMEOUT
    result = await session.execute(
        text(
            "UPDATE extraction_jobs SET status = :failed, error = 'stale: exceeded timeout', "
            "finished_at = now() WHERE status = :running AND started_at < :cutoff "
            "RETURNING id"
        ),
        {"failed": ExtractionJobStatus.FAILED.value, "running": ExtractionJobStatus.RUNNING.value, "cutoff": cutoff},
    )
    return len(result.all())


@celery_app.task(name="app.workers.tasks.maintenance.reap_stale_jobs")
def reap_stale_jobs() -> None:
    async def _run() -> None:
        for tenant_id in await _all_tenant_ids():
            await with_worker_session(system_ctx(tenant_id), _reap_stale_jobs_body, tenant_id)

    run_async(_run)()


_STUCK_DRAWING_STATUSES = (DrawingStatus.INDEXING.value, DrawingStatus.EXTRACTING.value, DrawingStatus.EMBEDDING.value)


async def _reap_stuck_drawings_body(session: AsyncSession, tenant_id: str) -> int:
    """Backstop for app.workers.tasks.takeoff's pipeline: a drawing can be
    left in indexing/extracting/embedding forever if a worker crashes
    mid-chord (no exception is ever raised to record a failure, unlike the
    ordinary failure paths those tasks already handle -- see
    aggregate_drawing_status's docstring). Reaps any drawing that hasn't
    moved in DRAWING_STUCK_TIMEOUT_S: fails its still-running
    extraction_jobs rows (same as _reap_stale_jobs_body above, but scoped to
    this drawing so a fresh, genuinely-still-running drawing elsewhere for
    the same tenant is untouched), then resolves the drawing itself via the
    same ready/partial/failed aggregation finalize_drawing uses, so the
    frontend's "Retry extraction" action (drawings whose status is failed/
    partial) becomes available again instead of the drawing staying stuck."""
    settings = get_settings()
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=settings.drawing_stuck_timeout_s)
    stuck = (
        await session.execute(
            select(Drawing).where(Drawing.status.in_(_STUCK_DRAWING_STATUSES), Drawing.updated_at < cutoff)
        )
    ).scalars().all()
    for drawing in stuck:
        await session.execute(
            text(
                "UPDATE extraction_jobs SET status = :failed, error = 'stale: exceeded timeout', "
                "finished_at = now() WHERE drawing_id = :drawing_id AND status = :running"
            ),
            {
                "failed": ExtractionJobStatus.FAILED.value,
                "running": ExtractionJobStatus.RUNNING.value,
                "drawing_id": str(drawing.id),
            },
        )
        jobs = (
            await session.execute(select(ExtractionJob).where(ExtractionJob.drawing_id == drawing.id))
        ).scalars().all()
        status, reason = aggregate_drawing_status(jobs)
        drawing.status = status
        # aggregate_drawing_status only ever returns reason=None alongside
        # `ready` -- a rescued drawing that turns out to have nothing
        # actually failed (e.g. every job that did run succeeded; a job
        # that never got as far as its own extraction_jobs row at all,
        # such as a broker message truly lost before any worker picked it
        # up, is invisible to this aggregation -- a known, narrow blind
        # spot of this recovery path, not the normal one) must not carry a
        # stale-looking "stalled" message alongside a ready status.
        if reason is None:
            drawing.error_message = None
        else:
            drawing.error_message = (
                f"Extraction stalled: no progress for over {settings.drawing_stuck_timeout_s}s; "
                f"rescued by the stale-drawing sweeper. {reason}"
            )
    await session.flush()
    return len(stuck)


@celery_app.task(name="app.workers.tasks.maintenance.reap_stuck_drawings")
def reap_stuck_drawings() -> None:
    async def _run() -> None:
        for tenant_id in await _all_tenant_ids():
            await with_worker_session(system_ctx(tenant_id), _reap_stuck_drawings_body, tenant_id)

    run_async(_run)()
