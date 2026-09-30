"""The project page's document tree: every document of a project as one compact row, with the status a person
reads (queued, reading, classified, extracting, ready, needs check, failed) worked out from the document and, for a
routed drawing, from the drawing's own extraction status. The grouping (class, discipline, drawing type) is done by
the client from these rows; the server only supplies the facts and the counts."""

from __future__ import annotations

from collections import Counter
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.intake.constants import Decider, DocClass, DocStatus, Flag, PackageStatus
from app.models.takeoff import Drawing
from app.models.tender_intake import Addendum, ProjectDocument, TenderPackage
from app.schemas.tender_intake import TreeItem, TreeOut, TreeSummary
from app.services.tender_intake import get_auto_accept_min, would_auto_accept

_DRAWING_IN_PROGRESS = {"uploaded", "queued", "converting", "indexing", "extracting", "embedding"}
IN_PROGRESS = ("queued", "reading", "classified", "extracting")


def _evidence_quote(doc: ProjectDocument) -> tuple[str | None, int | None]:
    for ev in doc.evidence or []:
        if ev.get("rule") == "model" and ev.get("matched"):
            return str(ev["matched"])[:200], ev.get("page")
    for ev in doc.evidence or []:
        if ev.get("matched"):
            return str(ev["matched"])[:200], ev.get("page")
    return None, None


def _decided_by(doc: ProjectDocument) -> str | None:
    if doc.auto_accepted:
        return Decider.AI.value
    if doc.confirmed_by is not None or doc.classified_by == Decider.USER.value:
        return Decider.USER.value
    return doc.classified_by


def _display(doc: ProjectDocument, threshold: float, drawings: dict[UUID, Drawing]) -> tuple[str, str | None]:
    status = doc.status
    if status == DocStatus.RECEIVED.value:
        return "queued", None
    if status == DocStatus.PROCESSING.value:
        return "reading", None
    if status == DocStatus.EXCLUDED.value:
        return "excluded", doc.error_message
    if status == DocStatus.REJECTED.value:
        return "failed", doc.rejection_reason or "rejected by the safety check"
    if status == DocStatus.FAILED.value:
        return "failed", doc.error_message or "processing failed"
    if status == DocStatus.PROPOSED.value:
        if would_auto_accept(doc, threshold):
            return "classified", None  # about to be accepted and routed
        reason = doc.error_message
        if not reason:
            flags = set(doc.flags or [])
            if Flag.INJECTION_SUSPECTED.value in flags:
                reason = "The file contains text aimed at the classifier; please check it"
            elif Flag.RULES_FALLBACK.value in flags:
                reason = (doc.doc_metadata or {}).get("ai_unavailable_reason")
                reason = f"Classified by rules ({reason})" if reason else "Classified by rules"
            elif Flag.CONFLICT.value in flags:
                reason = "The AI and the automatic rules disagree"
            elif float(doc.confidence or 0) < threshold:
                reason = "Confidence is below the auto-accept threshold"
        return "needs_check", reason
    # confirmed / routed
    if doc.routed_kind == "drawing":
        drawing_id = doc.routed_ref.get("drawing_id")
        drawing = drawings.get(UUID(drawing_id)) if drawing_id else None
        if drawing is None:
            return "ready", None
        if drawing.status in _DRAWING_IN_PROGRESS:
            return "extracting", None
        if drawing.status == "failed":
            return "failed", drawing.error_message or "drawing extraction failed"
        if drawing.status == "needs_conversion":
            return "needs_check", "The DWG needs conversion before it can be measured"
        if drawing.status == "partial":
            return "ready", "Some sheets could not be fully read"
        return "ready", None
    if doc.routed_kind == "not_measurable":
        return "ready", str(doc.routed_ref.get("note") or "not measurable")
    if doc.routed_kind == "duplicate":
        return "ready", "Identical to another file in this project"
    return "ready", None


async def build_tree(session: AsyncSession, project_id: UUID, *, ai_available: bool, ai_message: str | None) -> TreeOut:
    threshold = await get_auto_accept_min(session)
    docs = list(
        (
            await session.execute(
                select(ProjectDocument)
                .where(ProjectDocument.project_id == project_id, ProjectDocument.status != DocStatus.ARCHIVE.value)
                .order_by(ProjectDocument.created_at, ProjectDocument.original_filename, ProjectDocument.id)
            )
        ).scalars().all()
    )
    drawing_ids = [UUID(d.routed_ref["drawing_id"]) for d in docs if d.routed_kind == "drawing" and d.routed_ref.get("drawing_id")]
    drawings: dict[UUID, Drawing] = {}
    if drawing_ids:
        drawings = {
            d.id: d for d in (await session.execute(select(Drawing).where(Drawing.id.in_(drawing_ids)))).scalars().all()
        }
    items: list[TreeItem] = []
    by_status: Counter[str] = Counter()
    by_class: Counter[str] = Counter()
    boq_docs: list[UUID] = []
    drawings_total = drawings_ready = 0
    for doc in docs:
        display, reason = _display(doc, threshold, drawings)
        md = doc.doc_metadata or {}
        quote, page = _evidence_quote(doc)
        is_drawing = doc.doc_class == DocClass.DRAWING.value
        items.append(
            TreeItem(
                id=doc.id, package_id=doc.package_id, name=doc.original_filename, path=doc.archive_path, ext=doc.ext,
                size_bytes=doc.size_bytes, doc_class=doc.doc_class, discipline=doc.sub_type if is_drawing else None,
                drawing_type=md.get("drawing_type") if is_drawing else None, unit_type=md.get("unit_type") if is_drawing else None,
                document_number=doc.document_number, title=doc.title, revision=doc.revision_label,
                sheet_number=md.get("sheet_number"), scale=md.get("scale"),
                confidence=float(doc.confidence) if doc.confidence is not None else None, status=doc.status,
                display_status=display, status_reason=reason, classified_by=doc.classified_by, decided_by=_decided_by(doc),
                auto_accepted=doc.auto_accepted, flags=list(doc.flags or []), routed_kind=doc.routed_kind,
                drawing_id=UUID(doc.routed_ref["drawing_id"]) if doc.routed_kind == "drawing" and doc.routed_ref.get("drawing_id") else None,
                evidence_quote=quote, evidence_page=page, ai_note=md.get("ai_unavailable_reason"),
                supersedes=[str(x) for x in md.get("supersedes", [])] if doc.doc_class == DocClass.ADDENDUM.value else [],
                created_at=doc.created_at,
            )
        )
        by_status[display] += 1
        if doc.doc_class and display != "excluded":
            by_class[doc.doc_class] += 1
        if doc.doc_class == DocClass.BOQ.value and doc.routed_kind == "boq_wizard" and doc.routed_ref.get("importable"):
            boq_docs.append(doc.id)
        if doc.routed_kind == "drawing":
            drawings_total += 1
            drawings_ready += display == "ready"
    addenda = len((await session.execute(select(Addendum.id).where(Addendum.project_id == project_id, Addendum.withdrawn_at.is_(None)))).scalars().all())
    processing = len(
        (
            await session.execute(
                select(TenderPackage.id).where(TenderPackage.project_id == project_id, TenderPackage.status == PackageStatus.PROCESSING.value)
            )
        ).scalars().all()
    )
    summary = TreeSummary(
        total=len(items), by_display_status=dict(by_status), by_class=dict(by_class),
        needs_check=by_status.get("needs_check", 0), in_progress=sum(by_status.get(k, 0) for k in IN_PROGRESS),
        drawings_total=drawings_total, drawings_ready=drawings_ready, boq_documents=boq_docs, addenda=addenda,
        packages_processing=processing, auto_accept_min=threshold, ai_available=ai_available, ai_message=ai_message,
    )
    return TreeOut(items=items, summary=summary)
