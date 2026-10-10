"""Builds manifest entries for documents that have none (existing packs), without touching the documents themselves:
no classification, status, routing or flag is changed (docs/boq-agent/plan.md section 2, brief Phase 1 step 6).

Run through ``python -m app.cli backfill-manifest``; ``--dry-run`` only counts.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select

from app.core.config import get_settings
from app.core.context import RequestContext, system_context
from app.db.session import session_scope
from app.integrations.s3 import get_object_bytes
from app.intake.extract import DocContent, extract_content
from app.intake.manifest import build_entry
from app.intake.rules import classify_rules, normalise_folder
from app.models.tender_intake import ProjectDocument, ProjectFileIndex
from app.services import file_manifest

logger = logging.getLogger(__name__)
_SKIP_STATUSES = ("received", "processing", "failed", "rejected", "archive", "excluded")


@dataclass(slots=True)
class BackfillStats:
    candidates: int = 0
    indexed: int = 0
    copied: int = 0
    partial: int = 0
    failed: int = 0
    seconds: float = 0.0


async def _candidates(ctx: RequestContext, project_id: UUID | None, limit: int | None) -> list[ProjectDocument]:
    async with session_scope(ctx) as session:
        stmt = (
            select(ProjectDocument)
            .outerjoin(ProjectFileIndex, ProjectFileIndex.document_id == ProjectDocument.id)
            .where(
                ProjectFileIndex.id.is_(None),
                ProjectDocument.safety_status == "accepted",
                ProjectDocument.status.not_in(_SKIP_STATUSES),
            )
            .order_by(ProjectDocument.project_id, ProjectDocument.duplicate_of_id.is_not(None), ProjectDocument.created_at)
        )
        if project_id is not None:
            stmt = stmt.where(ProjectDocument.project_id == project_id)
        if limit:
            stmt = stmt.limit(limit)
        rows = list((await session.execute(stmt)).scalars().all())
        session.expunge_all()
        return rows


async def _one(ctx: RequestContext, doc: ProjectDocument, stats: BackfillStats, sem: asyncio.Semaphore) -> None:
    from app.services.tender_intake_processing import _embed_one  # the same local-embedder wrapper as upload

    settings = get_settings()
    async with sem:
        try:
            if doc.duplicate_of_id is not None:
                async with session_scope(ctx) as session:
                    if await file_manifest.copy_entry(session, ctx, doc):
                        stats.copied += 1
                        return
            partial_reason = None
            try:
                data = await get_object_bytes(doc.object_key, bucket=doc.bucket)
                content = await asyncio.wait_for(
                    asyncio.to_thread(
                        extract_content, filename=doc.original_filename, ext=doc.ext, sniffed=doc.content_type_sniffed, data=data, fast=True
                    ),
                    timeout=settings.intake_doc_timeout_s,
                )
            except asyncio.TimeoutError:
                content = DocContent(filename=doc.original_filename, ext=doc.ext, sniffed=doc.content_type_sniffed)
                partial_reason = f"reading took longer than {settings.intake_doc_timeout_s} s"
            folder = normalise_folder(doc.archive_path)
            rules = classify_rules(content, doc.original_filename, folder=folder)
            entry = build_entry(
                content=content, rules=rules, filename=doc.original_filename, folder=folder,
                path=doc.archive_path or doc.original_filename, size_bytes=doc.size_bytes or 0, sha256=doc.sha256,
                partial_reason=partial_reason,
            )
            embedding = await asyncio.to_thread(_embed_one, entry.embedding_text())
            async with session_scope(ctx) as session:
                await file_manifest.upsert_entry(
                    session, ctx, project_id=doc.project_id, document_id=doc.id, entry=entry, embedding=embedding
                )
            stats.indexed += 1
            stats.partial += 1 if entry.partial_index else 0
        except Exception:  # noqa: BLE001 -- one bad file must not stop the backfill
            logger.warning("backfill: %s failed", doc.id, exc_info=True)
            stats.failed += 1


async def backfill_tenant(
    tenant_id: UUID, *, project_id: UUID | None = None, limit: int | None = None, dry_run: bool = False, concurrency: int = 4
) -> BackfillStats:
    ctx = system_context(tenant_id)
    stats = BackfillStats()
    started = time.monotonic()
    docs = await _candidates(ctx, project_id, limit)
    stats.candidates = len(docs)
    if not dry_run:
        # Originals before their duplicates, so a copy finds its source.
        sem = asyncio.Semaphore(max(1, concurrency))
        originals = [d for d in docs if d.duplicate_of_id is None]
        copies = [d for d in docs if d.duplicate_of_id is not None]
        for group in (originals, copies):
            await asyncio.gather(*(_one(ctx, d, stats, sem) for d in group))
    stats.seconds = round(time.monotonic() - started, 1)
    return stats
