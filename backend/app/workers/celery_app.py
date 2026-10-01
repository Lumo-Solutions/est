from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "installtec",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "app.workers.tasks.takeoff",
        "app.workers.tasks.maintenance",
        "app.workers.tasks.procurement",
        "app.workers.tasks.quotation_ingestion",
        "app.workers.tasks.tender_intake",
        "app.workers.tasks.dwg",
        "app.workers.tasks.ai_reading",
    ],
)

celery_app.conf.update(
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    # A message a dead worker had taken but not acknowledged comes back after this long (Redis default: an hour). It
    # must exceed the longest task (the hard limits are 300-360 s), so nothing running is ever delivered twice.
    # Priority queues (Redis emulates them with one list per step): what a person is looking at (0) runs before the
    # verification report's needs (3), before a bulk "Measure all" (6), before automatic measuring (9).
    broker_transport_options={"visibility_timeout": 1800, "priority_steps": [0, 3, 6, 9], "queue_order_strategy": "priority"},
    task_default_priority=6,
    # A worker child is recycled after this many tasks or once it holds this much memory (checked between tasks), so
    # a leak or one fat file cannot grow a worker without bound. `--max-tasks-per-child` / `--max-memory-per-child` on
    # the command line (deploy/docker-compose.yml) override these.
    worker_max_tasks_per_child=settings.celery_max_tasks_per_child,
    worker_max_memory_per_child=settings.celery_max_memory_per_child_kb,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_routes={
        # The page index and geometry of a drawing are the heaviest PDF work: own queue, own worker (celery-worker-index).
        "app.workers.tasks.takeoff.index_sheets": {"queue": "index"},
        "app.workers.tasks.takeoff.extract_sheet": {"queue": "vlm"},
        "app.workers.tasks.takeoff.embed_drawing": {"queue": "embed"},
        "app.workers.tasks.takeoff.extract_geometry_measurements": {"queue": "index"},
        "app.workers.tasks.takeoff.finalize_drawing": {"queue": "ingest"},
        "app.workers.tasks.takeoff.index_drawing_light": {"queue": "ingest"},
        # DWG -> DXF conversion (sandboxed ODA converter); own queue/worker so a
        # slow or hostile DWG can never back up DXF/PDF ingestion.
        "app.workers.tasks.dwg.convert_dwg": {"queue": "convert"},
        # AI-assisted reading (PDF BOQ pages, drawing annotations): the model-backed queue.
        "app.workers.tasks.ai_reading.*": {"queue": "vlm"},
        "app.workers.tasks.maintenance.*": {"queue": "ingest"},
        # Tender intake: classification of an uploaded pack (docs/tender-intake-plan.md).
        "app.workers.tasks.tender_intake.*": {"queue": "ingest"},
        "app.workers.tasks.procurement.*": {"queue": "email"},
        # --- Module C2: inbound quotation ingestion ---
        # poll_inbound_mailbox is pure IMAP I/O, same "talk to a mail
        # server" queue as C1's outbound SMTP dispatch. process_inbound_email
        # (untrusted-input safety checks for every attachment on one email,
        # then deterministic parsing) is kept off both of those -- a
        # hostile/oversized attachment must never back up outbound RFQ
        # dispatch or inbound polling. extract_quotation shares Module B's
        # vLLM-backed queue/worker.
        "app.workers.tasks.quotation_ingestion.poll_inbound_mailbox": {"queue": "email"},
        "app.workers.tasks.quotation_ingestion.process_inbound_email": {"queue": "quotation"},
        "app.workers.tasks.quotation_ingestion.extract_quotation": {"queue": "vlm"},
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
        "reap-stuck-drawings": {
            "task": "app.workers.tasks.maintenance.reap_stuck_drawings",
            "schedule": crontab(minute=0),
        },
        # Tender intake: the dispatcher and the sweeper for files abandoned by a dead worker (docs/intake-scale/report.md).
        "intake-tick": {
            "task": "app.workers.tasks.tender_intake.intake_tick",
            "schedule": 30.0,
        },
        "poll-inbound-mailbox": {
            "task": "app.workers.tasks.quotation_ingestion.poll_inbound_mailbox",
            "schedule": 60.0,
        },
    },
)
