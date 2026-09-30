"""Tender document intake: upload, review actions and routing.

Upload stores originals content-addressed in S3 and creates ``received``
rows; the worker (services/tender_intake_processing.py) classifies them into
``proposed``. Nothing is routed until a lead_estimator+ confirms: confirming a
document routes it in the same transaction (drawing pipeline, BOQ wizard
pre-fill, addenda register, or the project document register). Every state
change is audited.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import Text, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.context import RequestContext
from app.core.enums import AuditAction, BidSettlementStatus, DrawingKind
from app.core.errors import ConflictError, NotFoundError, ValidationAppError
from app.integrations.s3 import get_object_bytes, presign_get_url, put_object_streaming
from app.intake.boq import suggest_mapping
from app.intake.constants import (
    ALL_CLASSES,
    DEFAULT_CLASS_LABELS,
    DRAWING_SUB_TYPES,
    REGISTER_CLASSES,
    ClassificationSource,
    DocClass,
    DocStatus,
    Flag,
    PackageStatus,
)
from app.intake.metadata import normalise_doc_no, revision_sort_key
from app.intake.rules import normalise_folder
from app.intake.safety import extension_of
from app.models.settlement import BidSettlement
from app.models.tender_intake import (
    Addendum,
    AddendumLink,
    DocumentClassification,
    ProjectDocument,
    TenderClassConfig,
    TenderPackage,
)
from app.schemas.tender_intake import (
    AddendumLinkOut,
    AddendumOut,
    BoqPrefillOut,
    BulkConfirmOut,
    ConfirmItemResult,
    TenderClassOut,
    TenderClassUpdate,
)
from app.services import audit
from app.services import takeoff as takeoff_service
from app.services.projects import assert_can_see_project
from app.services.tender_intake_processing import bucket_for, get_document, object_key_for

# Drawings first, BOQ next, register documents, addenda last: an addendum's
# references resolve against what the same batch just routed.
_ROUTE_PRIORITY = {DocClass.DRAWING.value: 0, DocClass.BOQ.value: 1, DocClass.ADDENDUM.value: 3}
_INGEST_COUNTDOWN_S = 5
_BULK_BLOCKING_FLAGS = {
    Flag.CONFLICT.value, Flag.LOW_CONFIDENCE.value, Flag.DUPLICATE.value, Flag.MODEL_UNAVAILABLE.value,
}
_REF = re.compile(r"^([A-Z]{1,4}-\d{2,5}(?:-\d{1,3})?)(?:\s+Rev\s+(\S+))?$", re.I)


def _safe_name(name: str) -> str:
    base = name.replace("\\", "/").rsplit("/", 1)[-1].strip() or "unnamed"
    return base[:512]


# --------------------------------------------------------------------- packages
async def _add_files(
    session: AsyncSession, ctx: RequestContext, package: TenderPackage, files: list[tuple[str, bytes]]
) -> list[UUID]:
    settings = get_settings()
    created: list[ProjectDocument] = []
    for raw_name, data in files:
        name = _safe_name(raw_name)
        folder = normalise_folder(raw_name)
        sha = hashlib.sha256(data).hexdigest()
        earlier = (
            await session.execute(
                select(ProjectDocument)
                .where(ProjectDocument.project_id == package.project_id, ProjectDocument.sha256 == sha)
                .order_by(ProjectDocument.created_at, ProjectDocument.id)
                .limit(1)
            )
        ).scalar_one_or_none()
        key = object_key_for(ctx.tenant_id, sha)
        if earlier is None:
            stored = await put_object_streaming(key, data, None, bucket=bucket_for(settings))
            if stored != sha:
                raise ConflictError("Stored object checksum did not match the upload")
        doc = ProjectDocument(
            tenant_id=ctx.tenant_id, project_id=package.project_id, package_id=package.id, original_filename=name,
            ext=extension_of(name), sha256=sha, bucket=bucket_for(settings),
            object_key=earlier.object_key if earlier is not None else key, size_bytes=len(data),
            status=DocStatus.RECEIVED.value, duplicate_of_id=earlier.id if earlier is not None else None,
            flags=[Flag.DUPLICATE.value] if earlier is not None else [],
            archive_path=f"{folder}/{name}"[:1024] if folder else None,
        )
        session.add(doc)
        await session.flush()
        created.append(doc)
    package.file_count = (package.file_count or 0) + len(files)
    package.status = PackageStatus.PROCESSING.value
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.IMPORT, entity_type="tender_package", entity_id=package.id,
        project_id=package.project_id, payload={"files": len(files), "label": package.label, "transmittal_ref": package.transmittal_ref},
    )
    return [d.id for d in created]


async def create_package(
    session: AsyncSession,
    ctx: RequestContext,
    project_id: UUID,
    files: list[tuple[str, bytes]],
    *,
    label: str | None = None,
    transmittal_ref: str | None = None,
    received_date: date | None = None,
) -> tuple[TenderPackage, list[UUID]]:
    """Stores every original (sha256-keyed, once per content) and creates the rows the
    worker will process. Size/count caps are enforced by the route before bytes get here."""
    if not files:
        raise ValidationAppError("No files were uploaded")
    await assert_can_see_project(session, ctx, project_id)
    package = TenderPackage(
        tenant_id=ctx.tenant_id, project_id=project_id, label=label, transmittal_ref=transmittal_ref,
        received_date=received_date or date.today(), status=PackageStatus.PROCESSING.value, file_count=0,
    )
    session.add(package)
    await session.flush()
    return package, await _add_files(session, ctx, package, files)


async def add_files(
    session: AsyncSession, ctx: RequestContext, package_id: UUID, files: list[tuple[str, bytes]]
) -> tuple[TenderPackage, list[UUID]]:
    """More files for an existing package (the UI sends large drops in batches)."""
    if not files:
        raise ValidationAppError("No files were uploaded")
    package = await get_package(session, package_id)
    await assert_can_see_project(session, ctx, package.project_id)
    return package, await _add_files(session, ctx, package, files)


async def get_package(session: AsyncSession, package_id: UUID) -> TenderPackage:
    row = (await session.execute(select(TenderPackage).where(TenderPackage.id == package_id))).scalar_one_or_none()
    if row is None:
        raise NotFoundError(f"Tender package {package_id} not found")
    return row


async def list_packages(session: AsyncSession, project_id: UUID) -> list[TenderPackage]:
    result = await session.execute(
        select(TenderPackage).where(TenderPackage.project_id == project_id).order_by(TenderPackage.created_at.desc())
    )
    return list(result.scalars().all())


async def refresh_package_status(session: AsyncSession, package_id: UUID) -> None:
    package = await get_package(session, package_id)
    rows = (await session.execute(select(ProjectDocument.status).where(ProjectDocument.package_id == package_id))).scalars().all()
    if any(s in (DocStatus.RECEIVED.value, DocStatus.PROCESSING.value) for s in rows):
        return
    live = [s for s in rows if s != DocStatus.ARCHIVE.value]
    package.status = PackageStatus.FAILED.value if live and all(s in (DocStatus.FAILED.value, DocStatus.REJECTED.value) for s in live) else PackageStatus.READY.value
    await session.flush()


# -------------------------------------------------------------------- documents
async def list_documents(
    session: AsyncSession,
    project_id: UUID,
    *,
    package_id: UUID | None = None,
    doc_class: str | None = None,
    status: str | None = None,
    flag: str | None = None,
    q: str | None = None,
    limit: int = 100,
    offset: int = 0,
    routed_kind: str | None = None,
) -> tuple[list[ProjectDocument], int]:
    stmt = select(ProjectDocument).where(ProjectDocument.project_id == project_id)
    if package_id:
        stmt = stmt.where(ProjectDocument.package_id == package_id)
    if doc_class:
        stmt = stmt.where(ProjectDocument.doc_class == doc_class)
    if status:
        stmt = stmt.where(ProjectDocument.status == status)
    if flag:
        stmt = stmt.where(ProjectDocument.flags.contains([flag]))
    if routed_kind:
        stmt = stmt.where(ProjectDocument.routed_kind == routed_kind)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                ProjectDocument.original_filename.ilike(like),
                ProjectDocument.title.ilike(like),
                ProjectDocument.document_number.ilike(like),
                ProjectDocument.archive_path.ilike(like),
                cast(ProjectDocument.doc_metadata, Text).ilike(like),
            )
        )
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = await session.execute(
        stmt.order_by(ProjectDocument.created_at, ProjectDocument.original_filename, ProjectDocument.id).limit(limit).offset(offset)
    )
    return list(rows.scalars().all()), total


async def get_document_detail(session: AsyncSession, document_id: UUID) -> tuple[ProjectDocument, list[DocumentClassification]]:
    doc = await get_document(session, document_id)
    rows = await session.execute(
        select(DocumentClassification).where(DocumentClassification.document_id == doc.id).order_by(DocumentClassification.created_at)
    )
    return doc, list(rows.scalars().all())


async def enabled_classes(session: AsyncSession) -> set[str]:
    rows = (await session.execute(select(TenderClassConfig))).scalars().all()
    disabled = {r.code for r in rows if not r.enabled}
    return set(ALL_CLASSES) - disabled


async def _require_editable(doc: ProjectDocument, *, allowed: tuple[str, ...] = (DocStatus.PROPOSED.value,)) -> None:
    if doc.status not in allowed:
        raise ConflictError(f"Document is {doc.status}; this action needs it to be {' or '.join(allowed)}")


async def reclassify(
    session: AsyncSession, ctx: RequestContext, document_id: UUID, doc_class: str, sub_type: str | None, note: str | None
) -> ProjectDocument:
    doc = await get_document(session, document_id)
    await _require_editable(doc, allowed=(DocStatus.PROPOSED.value, DocStatus.FAILED.value))
    if doc_class not in ALL_CLASSES:
        raise ValidationAppError(f"Unknown class {doc_class!r}")
    if doc_class not in await enabled_classes(session):
        raise ConflictError(f"Class {doc_class!r} is disabled for this tenant")
    if sub_type is not None and (doc_class != DocClass.DRAWING.value or sub_type not in DRAWING_SUB_TYPES):
        raise ValidationAppError("sub_type only applies to drawings and must be a known discipline")
    before = {"doc_class": doc.doc_class, "sub_type": doc.sub_type, "confidence": float(doc.confidence) if doc.confidence is not None else None}
    from sqlalchemy import update

    await session.execute(update(DocumentClassification).where(DocumentClassification.document_id == doc.id).values(is_current=False))
    session.add(
        DocumentClassification(
            tenant_id=ctx.tenant_id, project_id=doc.project_id, document_id=doc.id, source=ClassificationSource.USER.value,
            doc_class=doc_class, sub_type=sub_type, confidence=1.0,
            evidence=[{"rule": "user", "matched": note or "", "page": None}], doc_metadata=dict(doc.doc_metadata), is_current=True,
        )
    )
    doc.doc_class, doc.sub_type, doc.confidence = doc_class, sub_type, 1.0
    doc.flags = [f for f in doc.flags if f not in (Flag.CONFLICT.value, Flag.LOW_CONFIDENCE.value, Flag.MODEL_UNAVAILABLE.value)]
    if doc.status == DocStatus.FAILED.value:
        doc.status, doc.error_message = DocStatus.PROPOSED.value, None
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.UPDATE, entity_type="project_document", entity_id=doc.id, project_id=doc.project_id,
        payload={"event": "reclassify", "from": before, "to": {"doc_class": doc_class, "sub_type": sub_type}, "note": note},
    )
    return doc


async def edit_metadata(
    session: AsyncSession, ctx: RequestContext, document_id: UUID, *, metadata: dict | None, title: str | None,
    document_number: str | None, revision_label: str | None,
) -> ProjectDocument:
    doc = await get_document(session, document_id)
    await _require_editable(doc, allowed=(DocStatus.PROPOSED.value, DocStatus.FAILED.value))
    before = {"title": doc.title, "document_number": doc.document_number, "revision_label": doc.revision_label, "keys": sorted(doc.doc_metadata)}
    merged = dict(doc.doc_metadata)
    if metadata:
        merged.update(metadata)
    if title is not None:
        doc.title = title[:512] or None
        merged["title"] = title
    if document_number is not None:
        doc.document_number = normalise_doc_no(document_number) or None
        merged["document_number"] = doc.document_number
    if revision_label is not None:
        doc.revision_label = revision_label.strip().upper()[:32] or None
        merged["revision"] = doc.revision_label
    doc.doc_metadata = merged
    if doc.status == DocStatus.FAILED.value:
        doc.status, doc.error_message = DocStatus.PROPOSED.value, None
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.UPDATE, entity_type="project_document", entity_id=doc.id, project_id=doc.project_id,
        payload={
            "event": "edit_metadata", "from": before,
            "to": {"title": doc.title, "document_number": doc.document_number, "revision_label": doc.revision_label, "keys": sorted(merged)},
        },
    )
    return doc


async def exclude(session: AsyncSession, ctx: RequestContext, document_id: UUID, reason: str) -> ProjectDocument:
    doc = await get_document(session, document_id)
    await _require_editable(
        doc, allowed=(DocStatus.PROPOSED.value, DocStatus.FAILED.value, DocStatus.REJECTED.value, DocStatus.RECEIVED.value)
    )
    previous = doc.status
    doc.status = DocStatus.EXCLUDED.value
    doc.error_message = f"excluded: {reason}"[:500]
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.UPDATE, entity_type="project_document", entity_id=doc.id, project_id=doc.project_id,
        payload={"event": "exclude", "from": previous, "reason": reason},
    )
    return doc


async def request_rerun(session: AsyncSession, ctx: RequestContext, document_id: UUID) -> ProjectDocument:
    doc = await get_document(session, document_id)
    stale_processing = (
        doc.status == DocStatus.PROCESSING.value and doc.updated_at < datetime.now(timezone.utc) - timedelta(minutes=15)
    )
    if doc.status not in (DocStatus.PROPOSED.value, DocStatus.FAILED.value, DocStatus.RECEIVED.value) and not stale_processing:
        raise ConflictError(f"Document is {doc.status}; only proposed, failed, received or stuck documents can be re-run")
    if doc.safety_status not in ("pending", "accepted"):
        raise ConflictError("Document was rejected by the safety check and cannot be re-run")
    previous = doc.status
    doc.status = DocStatus.RECEIVED.value
    doc.error_message = None
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.UPDATE, entity_type="project_document", entity_id=doc.id, project_id=doc.project_id,
        payload={"event": "rerun", "from": previous},
    )
    from app.workers.tasks.tender_intake import rerun_document

    rerun_document.apply_async(
        args=(str(doc.id), str(ctx.tenant_id), str(ctx.user_id) if ctx.user_id else None, list(ctx.roles)), countdown=3
    )
    return doc


async def download_url(session: AsyncSession, ctx: RequestContext, document_id: UUID) -> str:
    doc = await get_document(session, document_id)
    if doc.safety_status != "accepted":
        raise ConflictError("This document did not pass the safety check and cannot be downloaded")
    await audit.record(
        session, ctx, action=AuditAction.DOWNLOAD, entity_type="project_document", entity_id=doc.id, project_id=doc.project_id,
        payload={"filename": doc.original_filename, "sha256": doc.sha256},
    )
    return await presign_get_url(doc.object_key, bucket=doc.bucket)


async def document_content(session: AsyncSession, ctx: RequestContext, document_id: UUID) -> tuple[ProjectDocument, bytes]:
    """The bytes themselves, same-origin (the BOQ wizard pre-fill reads the workbook through this,
    because a browser fetch of the presigned S3 redirect is cross-origin). Accepted documents only."""
    doc = await get_document(session, document_id)
    if doc.safety_status != "accepted":
        raise ConflictError("This document did not pass the safety check and cannot be downloaded")
    await audit.record(
        session, ctx, action=AuditAction.DOWNLOAD, entity_type="project_document", entity_id=doc.id, project_id=doc.project_id,
        payload={"filename": doc.original_filename, "sha256": doc.sha256, "via": "content"},
    )
    return doc, await get_object_bytes(doc.object_key, bucket=doc.bucket)


# ---------------------------------------------------------------------- routing
def _parse_ref(text: str) -> tuple[str | None, str | None]:
    m = _REF.match(text.strip())
    return (normalise_doc_no(m.group(1)), m.group(2).upper() if m.group(2) else None) if m else (None, None)


async def _routed_with_number(session: AsyncSession, project_id: UUID, number: str) -> list[ProjectDocument]:
    result = await session.execute(
        select(ProjectDocument).where(
            ProjectDocument.project_id == project_id,
            ProjectDocument.document_number == number,
            ProjectDocument.status == DocStatus.ROUTED.value,
            ProjectDocument.routed_kind != "duplicate",
        )
    )
    return list(result.scalars().all())


async def _relink_lineage(session: AsyncSession, project_id: UUID, number: str | None) -> None:
    """Order-independent revision lineage: every routed document with this number points at
    the previous revision. Drawings mirror it on the Drawing row (the old one stays readable)."""
    if not number:
        return
    docs = await _routed_with_number(session, project_id, number)
    distinct: dict[str, ProjectDocument] = {}
    for d in sorted(docs, key=lambda d: (revision_sort_key(d.revision_label), d.created_at)):
        distinct.setdefault(d.sha256, d)
    ordered = sorted(distinct.values(), key=lambda d: (revision_sort_key(d.revision_label), d.created_at))
    for prev, cur in zip(ordered, ordered[1:], strict=False):
        if revision_sort_key(prev.revision_label) == revision_sort_key(cur.revision_label):
            continue
        cur.supersedes_id = prev.id
        prev.routed_ref = {**prev.routed_ref, "superseded_by": str(cur.id)}
        cur_drawing, prev_drawing = cur.routed_ref.get("drawing_id"), prev.routed_ref.get("drawing_id")
        if cur_drawing and prev_drawing:
            from app.models.takeoff import Drawing

            drawing = (await session.execute(select(Drawing).where(Drawing.id == UUID(cur_drawing)))).scalar_one_or_none()
            if drawing is not None:
                drawing.supersedes_id = UUID(prev_drawing)
    await session.flush()


async def _resolve_target(session: AsyncSession, project_id: UUID, reference: str) -> ProjectDocument | None:
    if reference.strip().upper() == "BOQ":
        result = await session.execute(
            select(ProjectDocument)
            .where(
                ProjectDocument.project_id == project_id, ProjectDocument.doc_class == DocClass.BOQ.value,
                ProjectDocument.status == DocStatus.ROUTED.value, ProjectDocument.routed_kind == "boq_wizard",
            )
            .order_by(ProjectDocument.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
    number, rev = _parse_ref(reference)
    if not number:
        return None
    candidates = await _routed_with_number(session, project_id, number)
    if rev:
        candidates = [c for c in candidates if (c.revision_label or "") == rev]
    return max(candidates, key=lambda c: revision_sort_key(c.revision_label)) if candidates else None


async def _resolve_open_links(session: AsyncSession, project_id: UUID) -> None:
    result = await session.execute(
        select(AddendumLink).where(AddendumLink.project_id == project_id, AddendumLink.resolved.is_(False))
    )
    for link in result.scalars().all():
        target = await _resolve_target(session, project_id, link.reference_text)
        if target is not None:
            link.target_document_id, link.resolved = target.id, True
    await session.flush()


async def _flag_settlements(session: AsyncSession, project_id: UUID) -> list[str]:
    result = await session.execute(
        select(BidSettlement.id).where(
            BidSettlement.project_id == project_id,
            BidSettlement.is_current.is_(True),
            BidSettlement.status.in_([BidSettlementStatus.DRAFT.value, BidSettlementStatus.SUBMITTED.value]),
        )
    )
    return [str(i) for i in result.scalars().all()]


async def _route_drawing(session: AsyncSession, ctx: RequestContext, doc: ProjectDocument) -> None:
    flags = list(doc.flags)
    if doc.ext in ("jpg", "jpeg", "png"):
        doc.routed_kind, doc.routed_ref = "not_measurable", {"note": "raster image: not measurable"}
        return
    if doc.ext not in ("dxf", "pdf", "dwg"):
        raise ConflictError(f"A .{doc.ext} file cannot be routed as a drawing")
    is_dwg = doc.ext == "dwg"
    # A DWG is routed like any drawing: the convert worker turns it into a DXF
    # and then runs the normal pipeline (or parks it in needs_conversion with a
    # reason when the converter is off/missing -- see app/workers/tasks/dwg.py).
    scanned = Flag.NOT_MEASURABLE.value in flags and not is_dwg
    if is_dwg:
        kind, content_type = DrawingKind.DWG.value, "application/acad"
    elif doc.ext == "dxf":
        kind, content_type = DrawingKind.DXF.value, "application/dxf"
    else:
        kind = DrawingKind.SCANNED_PDF.value if scanned else DrawingKind.VECTOR_PDF.value
        content_type = "application/pdf"
    drawing, created = await takeoff_service.create_drawing_from_stored(
        session, ctx, project_id=doc.project_id, filename=doc.original_filename,
        content_type=content_type, kind=kind, bucket=doc.bucket,
        object_key=doc.object_key, sha256=doc.sha256, size_bytes=doc.size_bytes, revision_label=doc.revision_label,
        discipline_hint=doc.sub_type,
    )
    if created:
        await takeoff_service.trigger_ingest(session, ctx, drawing.id, countdown=_INGEST_COUNTDOWN_S)
    doc.routed_kind = "drawing"
    doc.routed_ref = {"drawing_id": str(drawing.id), "kind": kind, "ingest_started": created, "not_measurable": scanned}


async def _route_boq(session: AsyncSession, ctx: RequestContext, doc: ProjectDocument) -> None:
    # A PDF BOQ opens the wizard's PDF flow (table reader first, AI only for unclear pages); an .xls is routed but not importable.
    if doc.ext not in ("xlsx", "csv", "xls", "pdf"):
        raise ConflictError(f"A .{doc.ext} file cannot go to the BOQ import wizard")
    mapping = suggest_mapping(doc.doc_metadata)
    doc.routed_kind = "boq_wizard"
    doc.routed_ref = {
        "sheet_name": mapping["sheet_name"], "header_row": mapping["header_row"], "suggested_mapping": mapping,
        "importable": doc.ext in ("xlsx", "csv", "pdf"),
    }


async def _route_addendum(session: AsyncSession, ctx: RequestContext, doc: ProjectDocument) -> None:
    md = doc.doc_metadata
    supersedes, amends = list(md.get("supersedes", [])), list(md.get("amends", []))
    addendum = Addendum(
        tenant_id=ctx.tenant_id, project_id=doc.project_id, document_id=doc.id, package_id=doc.package_id,
        addendum_no=str(md["addendum_number"]) if md.get("addendum_number") else None,
        issue_date=str(md["addendum_issue_date"]) if md.get("addendum_issue_date") else None,
        title=doc.title or doc.original_filename,
        summary="; ".join(filter(None, [f"Supersedes: {', '.join(supersedes)}" if supersedes else "", f"Amends: {', '.join(amends)}" if amends else ""])) or None,
        routed_at=datetime.now(timezone.utc),
    )
    session.add(addendum)
    await session.flush()
    for action, refs in (("supersedes", supersedes), ("amends", amends)):
        for ref in refs:
            target = await _resolve_target(session, doc.project_id, ref)
            session.add(
                AddendumLink(
                    tenant_id=ctx.tenant_id, project_id=doc.project_id, addendum_id=addendum.id,
                    target_document_id=target.id if target is not None else None, reference_text=ref[:255], action=action,
                    resolved=target is not None,
                )
            )
            if target is not None and action == "supersedes":
                target.routed_ref = {**target.routed_ref, "superseded_by_addendum": str(addendum.id)}
    addendum.flagged_settlement_ids = await _flag_settlements(session, doc.project_id)
    await session.flush()
    doc.routed_kind = "addendum"
    doc.routed_ref = {"addendum_id": str(addendum.id), "flagged_settlements": addendum.flagged_settlement_ids}


async def route_document(session: AsyncSession, ctx: RequestContext, doc: ProjectDocument) -> None:
    """Called by confirm. Sets routed_kind/routed_ref and status routed."""
    if doc.duplicate_of_id is not None or Flag.DUPLICATE.value in doc.flags:
        doc.routed_kind, doc.routed_ref = "duplicate", {"duplicate_of": str(doc.duplicate_of_id) if doc.duplicate_of_id else None}
    elif doc.doc_class == DocClass.DRAWING.value:
        await _route_drawing(session, ctx, doc)
    elif doc.doc_class == DocClass.BOQ.value:
        await _route_boq(session, ctx, doc)
    elif doc.doc_class == DocClass.ADDENDUM.value:
        await _route_addendum(session, ctx, doc)
    elif doc.doc_class in REGISTER_CLASSES:
        doc.routed_kind, doc.routed_ref = "register", {}
    else:
        raise ConflictError(f"Document has no routable class ({doc.doc_class!r})")
    doc.status = DocStatus.ROUTED.value
    await session.flush()
    if doc.routed_kind != "duplicate":
        await _relink_lineage(session, doc.project_id, doc.document_number)
        await _resolve_open_links(session, doc.project_id)
    await audit.record(
        session, ctx, action=AuditAction.UPDATE, entity_type="project_document", entity_id=doc.id, project_id=doc.project_id,
        payload={"event": "route", "doc_class": doc.doc_class, "routed_kind": doc.routed_kind, "routed_ref": doc.routed_ref},
    )


async def confirm_document(session: AsyncSession, ctx: RequestContext, document_id: UUID) -> ProjectDocument:
    doc = await get_document(session, document_id)
    await _require_editable(doc)
    if not doc.doc_class:
        raise ConflictError("Document has no class to confirm")
    if doc.doc_class not in await enabled_classes(session):
        raise ConflictError(f"Class {doc.doc_class!r} is disabled: reclassify first")
    doc.status = DocStatus.CONFIRMED.value
    doc.confirmed_by, doc.confirmed_at = ctx.user_id, datetime.now(timezone.utc)
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.UPDATE, entity_type="project_document", entity_id=doc.id, project_id=doc.project_id,
        payload={"event": "confirm", "doc_class": doc.doc_class, "sub_type": doc.sub_type, "confidence": float(doc.confidence or 0)},
    )
    await route_document(session, ctx, doc)
    return doc


async def bulk_confirm(
    session: AsyncSession, ctx: RequestContext, project_id: UUID, *, package_id: UUID | None = None,
    document_ids: list[UUID] | None = None, min_confidence: float | None = None,
) -> BulkConfirmOut:
    """Explicit ids: confirms exactly those (the reviewer chose them). Otherwise: only
    proposals at or above the confidence minimum that carry no conflict/low-confidence/
    duplicate/model-unavailable flag. Each document runs in its own savepoint, so one that
    fails to route does not undo the others."""
    await assert_can_see_project(session, ctx, project_id)
    settings = get_settings()
    stmt = select(ProjectDocument).where(ProjectDocument.project_id == project_id)
    if document_ids is not None:
        stmt = stmt.where(ProjectDocument.id.in_(document_ids))
    else:
        stmt = stmt.where(ProjectDocument.status == DocStatus.PROPOSED.value)
        if package_id:
            stmt = stmt.where(ProjectDocument.package_id == package_id)
    docs = list((await session.execute(stmt)).scalars().all())

    minimum = settings.intake_bulk_confirm_min if min_confidence is None else min_confidence
    results: list[ConfirmItemResult] = []
    eligible: list[ProjectDocument] = []
    skipped = 0
    for d in docs:
        if d.status != DocStatus.PROPOSED.value:
            results.append(ConfirmItemResult(id=d.id, ok=False, status=d.status, error=f"not proposed ({d.status})"))
            skipped += 1
        elif document_ids is None and (
            (d.confidence or 0) < minimum or _BULK_BLOCKING_FLAGS & set(d.flags)
        ):
            skipped += 1
        else:
            eligible.append(d)

    confirmed = failed = 0
    for d in sorted(eligible, key=lambda d: (_ROUTE_PRIORITY.get(d.doc_class or "", 2), d.created_at)):
        try:
            async with session.begin_nested():
                await confirm_document(session, ctx, d.id)
            results.append(ConfirmItemResult(id=d.id, ok=True, status=d.status, routed_kind=d.routed_kind))
            confirmed += 1
        except Exception as exc:  # noqa: BLE001 -- reported per item
            await session.refresh(d)
            results.append(ConfirmItemResult(id=d.id, ok=False, status=d.status, error=str(exc)[:300]))
            failed += 1
    await audit.record(
        session, ctx, action=AuditAction.UPDATE, entity_type="tender_package", entity_id=package_id, project_id=project_id,
        payload={"event": "bulk_confirm", "confirmed": confirmed, "failed": failed, "skipped": skipped, "min_confidence": minimum},
    )
    return BulkConfirmOut(confirmed=confirmed, failed=failed, skipped=skipped, results=results)


# ------------------------------------------------------------ registers / views
async def list_addenda(session: AsyncSession, project_id: UUID) -> list[AddendumOut]:
    addenda = (
        await session.execute(select(Addendum).where(Addendum.project_id == project_id).order_by(Addendum.routed_at.desc()))
    ).scalars().all()
    out: list[AddendumOut] = []
    for a in addenda:
        links = (await session.execute(select(AddendumLink).where(AddendumLink.addendum_id == a.id))).scalars().all()
        item = AddendumOut.model_validate(a)
        item.links = [AddendumLinkOut.model_validate(link) for link in links]
        ids = [UUID(i) for i in a.flagged_settlement_ids]
        if ids:
            rows = (await session.execute(select(BidSettlement).where(BidSettlement.id.in_(ids)))).scalars().all()
            item.open_settlement_ids = [
                s.id for s in rows
                if s.is_current
                and (
                    s.status == BidSettlementStatus.SUBMITTED.value
                    or (
                        s.status == BidSettlementStatus.DRAFT.value
                        and (s.quantities_refreshed_at is None or s.quantities_refreshed_at < a.routed_at)
                    )
                )
            ]
        out.append(item)
    return out


async def boq_prefill(session: AsyncSession, document_id: UUID) -> BoqPrefillOut:
    doc = await get_document(session, document_id)
    if doc.doc_class != DocClass.BOQ.value:
        raise ConflictError("Only a document classified as a BOQ can pre-fill the import wizard")
    if doc.status != DocStatus.ROUTED.value or doc.routed_kind != "boq_wizard":
        raise ConflictError("The BOQ has not been confirmed yet")
    mapping = doc.routed_ref.get("suggested_mapping") or suggest_mapping(doc.doc_metadata)
    return BoqPrefillOut(
        document_id=doc.id, filename=doc.original_filename, sheet_name=mapping.get("sheet_name"),
        header_row=mapping.get("header_row"), sheet_names=list(doc.doc_metadata.get("sheet_names", [])), suggested_mapping=mapping,
    )


# ---------------------------------------------------------------- class config
async def list_classes(session: AsyncSession) -> list[TenderClassOut]:
    overrides = {r.code: r for r in (await session.execute(select(TenderClassConfig))).scalars().all()}
    out = []
    for idx, code in enumerate(ALL_CLASSES):
        row = overrides.get(code)
        out.append(
            TenderClassOut(
                code=code, label=row.label if row else DEFAULT_CLASS_LABELS[code], default_label=DEFAULT_CLASS_LABELS[code],
                enabled=row.enabled if row else True, sort_order=row.sort_order if row else idx,
            )
        )
    return sorted(out, key=lambda c: (c.sort_order, c.code))


async def update_class(session: AsyncSession, ctx: RequestContext, code: str, data: TenderClassUpdate) -> TenderClassOut:
    if code not in ALL_CLASSES:
        raise NotFoundError(f"Unknown class {code!r}")
    row = (await session.execute(select(TenderClassConfig).where(TenderClassConfig.code == code))).scalar_one_or_none()
    before = None
    if row is None:
        row = TenderClassConfig(tenant_id=ctx.tenant_id, code=code, label=DEFAULT_CLASS_LABELS[code], enabled=True, sort_order=ALL_CLASSES.index(code))
        session.add(row)
    else:
        before = {"label": row.label, "enabled": row.enabled, "sort_order": row.sort_order}
    if data.label is not None:
        row.label = data.label
    if data.enabled is not None:
        row.enabled = data.enabled
    if data.sort_order is not None:
        row.sort_order = data.sort_order
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.UPDATE, entity_type="tender_class_config", entity_id=row.id,
        payload={"code": code, "from": before, "to": {"label": row.label, "enabled": row.enabled, "sort_order": row.sort_order}},
    )
    return next(c for c in await list_classes(session) if c.code == code)
