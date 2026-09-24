from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "installtec",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.tasks.takeoff", "app.workers.tasks.maintenance", "app.workers.tasks.procurement"],
)

celery_app.conf.update(
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_routes={
        "app.workers.tasks.takeoff.index_sheets": {"queue": "ingest"},
        "app.workers.tasks.takeoff.extract_sheet": {"queue": "vlm"},
        "app.workers.tasks.takeoff.embed_drawing": {"queue": "embed"},
        "app.workers.tasks.takeoff.extract_geometry_measurements": {"queue": "ingest"},
        "app.workers.tasks.takeoff.finalize_drawing": {"queue": "ingest"},
        "app.workers.tasks.maintenance.*": {"queue": "ingest"},
        "app.workers.tasks.procurement.*": {"queue": "email"},
    },
    beat_schedule={
        "scan-certificate-expiry": {
            "task": "app.workers.tasks.maintenance.scan_certificate_expiry",
            "schedule": crontab(hour=2, minute=0),
        },
        "write-audit-checkpoints": {
            "task": "app.workers.tasks.maintenance.write_audit_checkpoints",
            "schedule": crontab(hour=3, minute=0),
        },
        "verify-audit-chain": {
            "task": "app.workers.tasks.maintenance.verify_audit_chain_all_tenants",
            "schedule": crontab(hour=4, minute=0, day_of_week=1),
        },
        "reap-stale-jobs": {
            "task": "app.workers.tasks.maintenance.reap_stale_jobs",
            "schedule": crontab(minute=0),
        },
    },
)
