"""Tender intake: the worker-side pipeline for one document (AI-first).

safety check -> (zip: expand into child documents) -> extract -> rules (hints) -> AI reads the file
-> persist the proposal. A document ends as ``proposed`` (or rejected/failed); whether it is then
routed without a person is decided afterwards by ``tender_intake.auto_accept_document`` against the
tenant's threshold (services/tender_intake.py).

The AI call is the slow step, so a group of documents is *prepared* concurrently (download, safety,
extract, rules, AI call; no database writes) and then persisted one at a time. A hard AI failure (not
configured, not allowed, over budget) or a run of soft failures trips a breaker for the rest of the
run and every remaining file is classified by the rules, labelled as such.

CPU-bound steps (parsing, archive expansion) run in a thread so the per-document deadline can be
enforced with asyncio timeouts.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.errors import AIBudgetExceeded, AIDisabledForTenant, AIError, AINotConfigured, AIRateLimited, describe_reason
from app.ai.gateway import AIMeta
from app.core.config import Settings, get_settings
from app.core.context import RequestContext
from app.core.enums import AttachmentSafetyStatus, AuditAction
from app.core.errors import NotFoundError
from app.integrations.s3 import get_object_bytes, put_object_streaming
from app.intake.archive import ArchiveLimits, expand_zip
from app.intake.classifier import (
    ModelClassification,
    Proposal,
    build_images,
    classify_with_model,
    combine,
    looks_like_injection,
    rule_hints,
    text_is_sufficient,
)
from app.intake.constants import ClassificationSource, Decider, DocClass, DocStatus, Flag
from app.intake.extract import DocContent, extract_content
from app.intake.metadata import normalise_doc_no, revision_sort_key
from app.intake.rules import RuleOutcome, classify_rules, normalise_folder
from app.intake.safety import IntakeSafety, check_file, extension_of
from app.models.tender_intake import DocumentClassification, ProjectDocument
from app.services import audit

logger = logging.getLogger(__name__)

_IMAGE_EXTS = ("jpg", "jpeg", "png")
_RATE_LIMIT_RETRIES = 3
_RATE_LIMIT_WAIT_S = 5.0


def object_key_for(tenant_id: UUID, sha256: str) -> str:
    return f"tender/{tenant_id}/{sha256}"


def bucket_for(settings: Settings) -> str:
    # Reuses the drawings bucket (a new bucket needs env + SeaweedFS identity changes).
    return settings.s3_bucket_drawings


async def get_document(session: AsyncSession, document_id: UUID) -> ProjectDocument:
    result = await session.execute(select(ProjectDocument).where(ProjectDocument.id == document_id))
    doc = result.scalar_one_or_none()
    if doc is None:
        raise NotFoundError(f"Document {document_id} not found")
    return doc


# ---------------------------------------------------------------- the AI run (breaker, concurrency)
class AiRun:
    """State shared by the documents of one worker run."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.sem = asyncio.Semaphore(max(1, self.settings.intake_ai_concurrency))
        self.stopped_reason: str | None = None
        self.calls = 0
        self._failures = 0

    def stop(self, reason: str) -> None:
        if self.stopped_reason is None:
            logger.warning("tender_intake: AI stopped for this run: %s", reason)
            self.stopped_reason = reason

    def succeeded(self) -> None:
        self._failures = 0

    def failed(self, reason: str) -> None:
        self._failures += 1
        if self._failures >= max(1, self.settings.intake_ai_max_consecutive_failures):
            self.stop(reason)


@dataclass(slots=True)
class DocSnapshot:
    """The few columns the AI step needs, read before the concurrent phase (no ORM objects cross tasks)."""

    id: UUID
    project_id: UUID
    original_filename: str
    ext: str
    archive_path: str | None
    bucket: str
    object_key: str
    is_duplicate: bool

    @classmethod
    def of(cls, doc: ProjectDocument) -> "DocSnapshot":
        return cls(
            doc.id, doc.project_id, doc.original_filename, doc.ext, doc.archive_path, doc.bucket, doc.object_key,
            doc.duplicate_of_id is not None or Flag.DUPLICATE.value in (doc.flags or []),
        )


@dataclass(slots=True)
class Prepared:
    """Everything the persist step needs, computed without touching the database."""

    safety: IntakeSafety
    content: DocContent | None = None
    rules: RuleOutcome | None = None
    model: ModelClassification | None = None
    ai_reason: str | None = None
    injection: str | None = None
    used_images: bool = False
    ai_text_chars: int = 0
    error: BaseException | None = None
    extras: dict = field(default_factory=dict)


async def _ai_read(
    run: AiRun, snap: DocSnapshot, content: DocContent, rules: RuleOutcome, data: bytes, project_id: UUID
) -> tuple[ModelClassification | None, str | None, bool]:
    """(model answer, plain-language reason when there is none, whether images were sent)."""
    if run.stopped_reason:
        return None, run.stopped_reason, False
    folder = normalise_folder(snap.archive_path)
    used_images = False
    async with run.sem:
        if run.stopped_reason:
            return None, run.stopped_reason, False
        images: list[bytes] = []
        if not text_is_sufficient(content):
            images = await asyncio.to_thread(build_images, snap.ext, data, content)
        used_images = bool(images)
        for attempt in range(_RATE_LIMIT_RETRIES + 1):
            try:
                run.calls += 1
                model = await asyncio.wait_for(
                    classify_with_model(
                        filename=snap.original_filename, content=content, images=images, folder_path=folder,
                        hints=rule_hints(rules),
                        meta=AIMeta(project_id=project_id, entity_type="project_document", entity_id=str(snap.id)),
                    ),
                    timeout=run.settings.intake_doc_timeout_s * 2,
                )
                run.succeeded()
                return model, None, used_images
            except AIRateLimited:
                if attempt == _RATE_LIMIT_RETRIES:
                    return None, describe_reason("ai_rate_limited"), used_images
                await asyncio.sleep(_RATE_LIMIT_WAIT_S)
            except (AINotConfigured, AIDisabledForTenant, AIBudgetExceeded) as exc:
                reason = describe_reason(exc.code)
                run.stop(reason)  # nothing will change during this run: stop asking, use the rules
                return None, reason, used_images
            except AIError as exc:
                reason = describe_reason(exc.code)
                run.failed(reason)
                return None, reason, used_images
            except asyncio.TimeoutError:
                run.failed("the AI did not answer in time")
                return None, "the AI did not answer in time", used_images
            except Exception:  # noqa: BLE001 -- a model failure must never fail the document
                logger.warning("tender_intake: AI step failed for %s", snap.id, exc_info=True)
                run.failed("the AI step failed")
                return None, "the AI step failed", used_images
    return None, "the AI step failed", used_images  # pragma: no cover


async def prepare_document(ctx: RequestContext, snap: DocSnapshot, run: AiRun) -> Prepared:
    """Download, safety check, extract, rules and the AI call for one file. Writes nothing to the database."""
    settings = run.settings
    data = await get_object_bytes(snap.object_key, bucket=snap.bucket)
    safety: IntakeSafety = await asyncio.to_thread(check_file, filename=snap.original_filename, data=data, settings=settings)
    if not safety.accepted or safety.is_archive:
        return Prepared(safety=safety, extras={"data": data if safety.is_archive else None})
    content = await asyncio.wait_for(
        asyncio.to_thread(extract_content, filename=snap.original_filename, ext=snap.ext, sniffed=safety.sniffed, data=data),
        timeout=settings.intake_doc_timeout_s,
    )
    rules = classify_rules(content, snap.original_filename, folder=normalise_folder(snap.archive_path))
    injection = looks_like_injection(content.text, content.title_block_text, snap.original_filename)
    model, reason, used_images = await _ai_read(run, snap, content, rules, data, snap.project_id)
    return Prepared(
        safety=safety, content=content, rules=rules, model=model, ai_reason=reason, injection=injection,
        used_images=used_images, ai_text_chars=len(content.text or ""),
    )


async def prepare_batch(ctx: RequestContext, snaps: list[DocSnapshot], run: AiRun) -> dict[UUID, Prepared]:
    """Concurrent `prepare_document` for a group. Duplicates are left out (they copy their original's class when
    they are persisted, so no second AI call is made for the same bytes). A failure is carried in `Prepared.error`
    and re-raised by `process_document`, so failure isolation stays per document."""

    async def one(snap: DocSnapshot) -> tuple[UUID, Prepared]:
        try:
            return snap.id, await prepare_document(ctx, snap, run)
        except Exception as exc:  # noqa: BLE001
            logger.warning("tender_intake: could not prepare %s", snap.id, exc_info=True)
            return snap.id, Prepared(safety=IntakeSafety(status="pending", sniffed=None), error=exc)

    results = await asyncio.gather(*(one(s) for s in snaps if not s.is_duplicate))
    return dict(results)


# ---------------------------------------------------------------- persistence
async def _earliest_with_sha(session: AsyncSession, project_id: UUID, sha256: str, exclude_id: UUID | None) -> ProjectDocument | None:
    stmt = (
        select(ProjectDocument)
        .where(ProjectDocument.project_id == project_id, ProjectDocument.sha256 == sha256)
        .order_by(ProjectDocument.created_at, ProjectDocument.id)
        .limit(1)
    )
    if exclude_id is not None:
        stmt = stmt.where(ProjectDocument.id != exclude_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def _create_children(
    session: AsyncSession, ctx: RequestContext, parent: ProjectDocument, files, settings: Settings
) -> list[UUID]:
    child_ids: list[UUID] = []
    for member in files:
        sha = hashlib.sha256(member.data).hexdigest()
        earlier = await _earliest_with_sha(session, parent.project_id, sha, None)
        key = object_key_for(ctx.tenant_id, sha)
        if earlier is None:
            stored = await put_object_streaming(key, member.data, None, bucket=bucket_for(settings))
            assert stored == sha
        name = member.path.rsplit("/", 1)[-1]
        child = ProjectDocument(
            tenant_id=ctx.tenant_id,
            project_id=parent.project_id,
            package_id=parent.package_id,
            parent_document_id=parent.id,
            archive_path=member.path,
            original_filename=name[:512],
            ext=extension_of(name),
            sha256=sha,
            bucket=bucket_for(settings),
            object_key=earlier.object_key if earlier is not None else key,
            size_bytes=len(member.data),
            status=DocStatus.RECEIVED.value,
            duplicate_of_id=earlier.id if earlier is not None else None,
            flags=[Flag.DUPLICATE.value] if earlier is not None else [],
        )
        session.add(child)
        await session.flush()
        child_ids.append(child.id)
    return child_ids


async def _flag_revision(session: AsyncSession, doc: ProjectDocument, flags: list[str], metadata: dict) -> None:
    """Same document number, different content, different revision: mark it as a revision of the latest earlier one."""
    if not doc.document_number:
        return
    result = await session.execute(
        select(ProjectDocument).where(
            ProjectDocument.project_id == doc.project_id,
            ProjectDocument.document_number == doc.document_number,
            ProjectDocument.id != doc.id,
            ProjectDocument.sha256 != doc.sha256,
            ProjectDocument.status.notin_([DocStatus.EXCLUDED.value, DocStatus.REJECTED.value, DocStatus.FAILED.value]),
        )
    )
    others = [o for o in result.scalars().all() if o.revision_label != doc.revision_label]
    earlier = [o for o in others if revision_sort_key(o.revision_label) < revision_sort_key(doc.revision_label)]
    if earlier:
        latest = max(earlier, key=lambda o: revision_sort_key(o.revision_label))
        if Flag.REVISION_OF.value not in flags:
            flags.append(Flag.REVISION_OF.value)
        metadata["revision_of_document_id"] = str(latest.id)


async def persist_proposal(
    session: AsyncSession,
    ctx: RequestContext,
    doc: ProjectDocument,
    content: DocContent,
    rules: RuleOutcome,
    proposal: Proposal,
    model_result,
    *,
    injection: str | None = None,
    used_images: bool = False,
) -> None:
    """Writes the classification history and the document's current proposal."""
    await session.execute(
        update(DocumentClassification).where(DocumentClassification.document_id == doc.id).values(is_current=False)
    )
    session.add(
        DocumentClassification(
            tenant_id=ctx.tenant_id, project_id=doc.project_id, document_id=doc.id,
            source=ClassificationSource.RULES.value, doc_class=rules.doc_class, sub_type=rules.sub_type,
            confidence=rules.confidence, evidence=rules.evidence, doc_metadata=rules.metadata,
            is_current=proposal.source == ClassificationSource.RULES.value,
        )
    )
    if model_result is not None:
        session.add(
            DocumentClassification(
                tenant_id=ctx.tenant_id, project_id=doc.project_id, document_id=doc.id,
                source=ClassificationSource.MODEL.value, doc_class=model_result.doc_class, sub_type=model_result.sub_type,
                confidence=min(model_result.confidence, 1.0),
                evidence=[{"rule": "model", "matched": model_result.evidence_quote or "", "page": model_result.evidence_page}],
                doc_metadata={**model_result.metadata.model_dump(), "drawing_type": model_result.drawing_type},
                is_current=proposal.source == ClassificationSource.MODEL.value,
            )
        )

    flags = list(dict.fromkeys([*doc.flags, *proposal.flags]))
    metadata = dict(proposal.metadata)
    if injection:
        if Flag.INJECTION_SUSPECTED.value not in flags:
            flags.append(Flag.INJECTION_SUSPECTED.value)
        metadata["injection_phrase"] = injection
    metadata["ai_input"] = {"images_sent": used_images, "text_chars": len(content.text or "")}
    if proposal.doc_class == DocClass.DRAWING.value:
        if doc.ext == "dwg":
            # Measurable through the converter sandbox; only flag it for a
            # manual conversion when that is switched off.
            if get_settings().dwg_conversion_enabled is False:
                flags += [f for f in (Flag.CONVERT_TO_DXF.value, Flag.NOT_MEASURABLE.value) if f not in flags]
        elif content.is_raster or doc.ext in _IMAGE_EXTS:
            if Flag.NOT_MEASURABLE.value not in flags:
                flags.append(Flag.NOT_MEASURABLE.value)
    if content.error and "extract_error" not in metadata:
        metadata["extract_error"] = content.error

    doc.doc_class = proposal.doc_class
    doc.sub_type = proposal.sub_type
    doc.confidence = proposal.confidence
    doc.title = (metadata.get("title") or None) and str(metadata["title"])[:512]
    doc.document_number = normalise_doc_no(metadata.get("document_number"))
    doc.revision_label = (str(metadata["revision"])[:32] if metadata.get("revision") else None)
    doc.classified_by = Decider.AI.value if proposal.source == ClassificationSource.MODEL.value else Decider.RULES.value
    doc.auto_accepted = False
    await _flag_revision(session, doc, flags, metadata)
    doc.doc_metadata = metadata
    doc.evidence = proposal.evidence
    doc.flags = flags
    doc.status = DocStatus.PROPOSED.value
    doc.error_message = None
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.UPDATE, entity_type="project_document", entity_id=doc.id,
        project_id=doc.project_id,
        payload={
            "event": "classify", "decided_by": doc.classified_by, "source": proposal.source, "doc_class": proposal.doc_class,
            "sub_type": proposal.sub_type, "confidence": float(proposal.confidence), "ai_called": model_result is not None,
            "images_sent": used_images, "flags": flags, "ai_unavailable_reason": metadata.get("ai_unavailable_reason"),
        },
    )


_COPY_FLAGS_SKIP = {Flag.DUPLICATE.value}


async def _copy_from_original(session: AsyncSession, ctx: RequestContext, doc: ProjectDocument) -> bool:
    """Same bytes as an earlier file of this project: reuse its classification instead of asking the AI again."""
    if doc.duplicate_of_id is None:
        return False
    original = (await session.execute(select(ProjectDocument).where(ProjectDocument.id == doc.duplicate_of_id))).scalar_one_or_none()
    if original is None or original.doc_class is None or original.status in (
        DocStatus.RECEIVED.value, DocStatus.PROCESSING.value, DocStatus.FAILED.value, DocStatus.REJECTED.value, DocStatus.EXCLUDED.value,
    ):
        return False
    doc.doc_class, doc.sub_type, doc.confidence = original.doc_class, original.sub_type, original.confidence
    doc.title, doc.document_number, doc.revision_label = original.title, original.document_number, original.revision_label
    doc.doc_metadata = {**original.doc_metadata, "same_file_as": str(original.id)}
    doc.evidence = [{"rule": "same_file", "class": original.doc_class, "weight": 1.0, "matched": f"identical to {original.original_filename}", "page": None}, *original.evidence]
    doc.flags = list(dict.fromkeys([*[f for f in original.flags if f not in (Flag.REVISION_OF.value,)], Flag.DUPLICATE.value]))
    doc.classified_by = original.classified_by
    doc.safety_status = original.safety_status
    doc.content_type_sniffed = original.content_type_sniffed
    doc.status = DocStatus.PROPOSED.value
    doc.error_message = None
    session.add(
        DocumentClassification(
            tenant_id=ctx.tenant_id, project_id=doc.project_id, document_id=doc.id,
            source=ClassificationSource.MODEL.value if original.classified_by == Decider.AI.value else ClassificationSource.RULES.value,
            doc_class=original.doc_class, sub_type=original.sub_type, confidence=original.confidence or 0,
            evidence=doc.evidence, doc_metadata=doc.doc_metadata, is_current=True,
        )
    )
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.UPDATE, entity_type="project_document", entity_id=doc.id, project_id=doc.project_id,
        payload={"event": "classify", "decided_by": doc.classified_by, "source": "same_file", "doc_class": doc.doc_class,
                 "confidence": float(doc.confidence or 0), "ai_called": False, "copied_from": str(original.id)},
    )
    return True


async def process_document(
    session: AsyncSession, ctx: RequestContext, document_id: UUID, prepared: Prepared | None = None, run: AiRun | None = None
) -> list[UUID]:
    """Runs one document through the pipeline. Returns child document ids (for a zip)."""
    settings = get_settings()
    doc = await get_document(session, document_id)
    if doc.status not in (DocStatus.RECEIVED.value, DocStatus.PROCESSING.value):
        return []
    doc.status = DocStatus.PROCESSING.value
    await session.flush()

    if prepared is None and await _copy_from_original(session, ctx, doc):
        return []
    if prepared is None:
        prepared = await prepare_document(ctx, DocSnapshot.of(doc), run or AiRun(settings))
    if prepared.error is not None:
        raise prepared.error
    safety = prepared.safety
    doc.safety_status = safety.status
    doc.content_type_sniffed = safety.sniffed
    if not safety.accepted:
        doc.status = DocStatus.REJECTED.value
        doc.rejection_reason = safety.reason
        await session.flush()
        await audit.record(
            session, ctx, action=AuditAction.UPDATE, entity_type="project_document", entity_id=doc.id,
            project_id=doc.project_id, payload={"event": "reject", "safety_status": safety.status, "reason": safety.reason},
        )
        return []

    if safety.is_archive:
        data = prepared.extras.get("data") or await get_object_bytes(doc.object_key, bucket=doc.bucket)
        result = await asyncio.wait_for(
            asyncio.to_thread(expand_zip, data, ArchiveLimits.from_settings(settings)), timeout=settings.intake_doc_timeout_s
        )
        if result.fatal is not None:
            status, reason = result.fatal
            doc.safety_status, doc.rejection_reason, doc.status = status, reason, DocStatus.REJECTED.value
            await session.flush()
            await audit.record(
                session, ctx, action=AuditAction.UPDATE, entity_type="project_document", entity_id=doc.id,
                project_id=doc.project_id, payload={"event": "reject", "safety_status": status, "reason": reason},
            )
            return []
        child_ids = await _create_children(session, ctx, doc, result.files, settings)
        doc.status = DocStatus.ARCHIVE.value
        await session.flush()
        await audit.record(
            session, ctx, action=AuditAction.IMPORT, entity_type="project_document", entity_id=doc.id,
            project_id=doc.project_id, payload={"event": "expand_archive", "members": len(child_ids)},
        )
        return child_ids

    assert prepared.content is not None and prepared.rules is not None
    proposal = combine(prepared.rules, prepared.model, settings=settings, reason=prepared.ai_reason)
    await persist_proposal(
        session, ctx, doc, prepared.content, prepared.rules, proposal, prepared.model,
        injection=prepared.injection, used_images=prepared.used_images,
    )
    return []


async def mark_failed(session: AsyncSession, ctx: RequestContext, document_id: UUID, message: str) -> None:
    """Records a processing failure on the document, in its own (independent) session."""
    doc = await get_document(session, document_id)
    if doc.status in (DocStatus.PROPOSED.value, DocStatus.CONFIRMED.value, DocStatus.ROUTED.value):
        return
    doc.status = DocStatus.FAILED.value
    doc.error_message = message[:500]
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.UPDATE, entity_type="project_document", entity_id=doc.id,
        project_id=doc.project_id, payload={"event": "process_failed", "error": message[:200]},
    )


__all__ = [
    "AiRun",
    "AttachmentSafetyStatus",
    "DocSnapshot",
    "Prepared",
    "bucket_for",
    "get_document",
    "mark_failed",
    "object_key_for",
    "persist_proposal",
    "prepare_batch",
    "prepare_document",
    "process_document",
]
