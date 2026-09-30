"""Tender intake: the worker-side pipeline for one document.

safety check -> (zip: expand into child documents) -> extract -> stage 1 rules
-> stage 2 model when unsure/conflicted -> persist proposals. Nothing here
routes anything: a document ends as ``proposed`` (or rejected/failed) and a
lead_estimator+ confirms it later (services/tender_intake.py).

CPU-bound steps (parsing, archive expansion) run in a thread so the
per-document deadline can be enforced with asyncio timeouts.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.context import RequestContext
from app.core.enums import AttachmentSafetyStatus, AuditAction
from app.core.errors import NotFoundError
from app.integrations.s3 import get_object_bytes, put_object_streaming
from app.intake.archive import ArchiveLimits, expand_zip
from app.intake.classifier import Proposal, classify_with_model, combine
from app.intake.constants import ClassificationSource, DocClass, DocStatus, Flag
from app.intake.extract import DocContent, extract_content
from app.intake.metadata import normalise_doc_no, revision_sort_key
from app.intake.rules import RuleOutcome, classify_rules, needs_model
from app.intake.safety import IntakeSafety, check_file, extension_of
from app.models.tender_intake import DocumentClassification, ProjectDocument
from app.services import audit

logger = logging.getLogger(__name__)

_IMAGE_EXTS = ("jpg", "jpeg", "png")


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


def _page_image(ext: str, data: bytes) -> bytes | None:
    """PNG of page 1 for the model, only used when there is no text layer."""
    try:
        if ext == "pdf":
            from app.takeoff.pdf import render_page_png

            return render_page_png(data, 0, dpi=100)
        if ext in _IMAGE_EXTS:
            from PIL import Image

            with Image.open(io.BytesIO(data)) as img:
                out = io.BytesIO()
                img.convert("RGB").save(out, format="PNG")
                return out.getvalue()
    except Exception:  # noqa: BLE001 -- no image just means the model works from the filename/text
        logger.warning("tender_intake: could not render a page image", exc_info=True)
    return None


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
) -> None:
    """Writes the classification history and the document's current proposal."""
    from sqlalchemy import update

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
                doc_metadata=model_result.metadata.model_dump(),
                is_current=proposal.source == ClassificationSource.MODEL.value,
            )
        )

    flags = list(dict.fromkeys([*doc.flags, *proposal.flags]))
    metadata = dict(proposal.metadata)
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
            "event": "classify", "source": proposal.source, "doc_class": proposal.doc_class,
            "confidence": float(proposal.confidence), "model_called": model_result is not None, "flags": flags,
        },
    )


async def process_document(session: AsyncSession, ctx: RequestContext, document_id: UUID) -> list[UUID]:
    """Runs one document through the pipeline. Returns child document ids (for a zip)."""
    settings = get_settings()
    doc = await get_document(session, document_id)
    if doc.status not in (DocStatus.RECEIVED.value, DocStatus.PROCESSING.value):
        return []
    doc.status = DocStatus.PROCESSING.value
    await session.flush()

    data = await get_object_bytes(doc.object_key, bucket=doc.bucket)
    safety: IntakeSafety = await asyncio.to_thread(check_file, filename=doc.original_filename, data=data, settings=settings)
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

    content = await asyncio.wait_for(
        asyncio.to_thread(extract_content, filename=doc.original_filename, ext=doc.ext, sniffed=safety.sniffed, data=data),
        timeout=settings.intake_doc_timeout_s,
    )
    rules = classify_rules(content, doc.original_filename)
    wanted = needs_model(rules, settings.intake_rules_confident)
    model_result = None
    if wanted:
        image = await asyncio.to_thread(_page_image, doc.ext, data) if content.needs_image else None
        try:
            model_result = await asyncio.wait_for(
                classify_with_model(
                    filename=doc.original_filename, content=content, candidates=sorted(rules.candidates), image_png=image
                ),
                timeout=settings.intake_doc_timeout_s,
            )
        except Exception:  # noqa: BLE001 -- a model failure must never fail the document
            logger.warning("tender_intake: stage 2 unavailable for %s", document_id, exc_info=True)
    proposal = combine(rules, model_result, model_wanted=wanted, settings=settings)
    await persist_proposal(session, ctx, doc, content, rules, proposal, model_result)
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
    "AttachmentSafetyStatus",
    "bucket_for",
    "get_document",
    "mark_failed",
    "object_key_for",
    "persist_proposal",
    "process_document",
]
