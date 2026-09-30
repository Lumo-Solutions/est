from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_session, require_roles
from app.core.context import RequestContext
from app.core.enums import Role
from app.core.errors import ValidationAppError
from app.integrations.s3 import get_object_bytes
from app.models.boq import BoqPdfExtraction
from app.schemas.ai_reading import (
    AnnotationPage,
    AnnotationReadAccepted,
    AnnotationReadIn,
    AnnotationSummaryOut,
    BoqPdfCommitOut,
    BoqPdfExtractionDetail,
    BoqPdfExtractionOut,
    BoqPdfFileUrlOut,
    BoqPdfPageOut,
    BoqPdfRowOut,
    BoqPdfRowsIn,
    DrawingAnnotationOut,
)
from app.services import annotations as annotations_service
from app.services import boq_pdf as boq_pdf_service
from app.services import tender_intake_processing as intake_processing

router = APIRouter(tags=["ai-reading"])

# Same roles that may import a BOQ (boq.py _STRUCTURE_ROLES), and RLS enforces it.
_BOQ_ROLES = (Role.LEAD_ESTIMATOR.value, Role.PROCUREMENT_HEAD.value, Role.MANAGING_DIRECTOR.value)
# Reading annotations spends AI budget: lead_estimator and above.
_READ_ROLES = (Role.LEAD_ESTIMATOR.value, Role.PROCUREMENT_HEAD.value, Role.BD_DIRECTOR.value, Role.MANAGING_DIRECTOR.value)
MAX_UPLOAD = boq_pdf_service.MAX_PDF_BYTES


def _dispatch_extraction(ctx: RequestContext, extraction_id: UUID) -> None:
    from app.workers.tasks.ai_reading import extract_boq_pdf

    # countdown: the request transaction commits when the route returns.
    extract_boq_pdf.apply_async(
        args=(str(extraction_id), str(ctx.tenant_id), str(ctx.user_id) if ctx.user_id else None, list(ctx.roles)),
        countdown=2,
    )


def _detail(ex: BoqPdfExtraction) -> BoqPdfExtractionDetail:
    result = boq_pdf_service.validate_rows(ex.rows)
    rows = [
        BoqPdfRowOut(
            **{k: r.get(k) for k in ("row_id", "page", "item_no", "description", "uom", "quantity", "bbox", "page_size", "source", "confidence")},
            edited=bool(r.get("edited")), ai_read=r.get("source") == "ai", errors=parsed.errors,
        )
        for r, parsed in zip(ex.rows, result.rows, strict=True)
    ]
    base = BoqPdfExtractionOut.model_validate(ex)
    return BoqPdfExtractionDetail(
        **base.model_dump(),
        pages=[BoqPdfPageOut(**p) for p in ex.page_summary],
        rows=rows, valid_count=result.valid_count, error_count=result.error_count,
        ai_row_count=sum(1 for r in ex.rows if r.get("source") == "ai"),
    )


@router.post("/projects/{project_id}/boq-pdf-extractions", response_model=BoqPdfExtractionOut, status_code=202)
async def create_boq_pdf_extraction_endpoint(
    project_id: UUID,
    file: UploadFile | None = File(default=None),
    document_id: UUID | None = Form(default=None),
    use_ai: bool = Form(default=True),
    ctx: RequestContext = Depends(require_roles(*_BOQ_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> BoqPdfExtractionOut:
    """Upload a PDF BOQ, or point at an already-classified tender document (`document_id`)."""
    if (file is None) == (document_id is None):
        raise ValidationAppError("Send either a PDF file or a document_id")
    if file is not None:
        data = await file.read(MAX_UPLOAD + 1)
        filename = file.filename or "boq.pdf"
    else:
        doc = await intake_processing.get_document(session, document_id)  # type: ignore[arg-type]
        if doc.project_id != project_id:
            raise ValidationAppError("That document belongs to a different project")
        data = await get_object_bytes(doc.object_key, bucket=doc.bucket)
        filename = doc.original_filename
    ex = await boq_pdf_service.create_extraction(
        session, ctx, project_id, data=data, filename=filename, use_ai=use_ai, document_id=document_id
    )
    _dispatch_extraction(ctx, ex.id)
    return BoqPdfExtractionOut.model_validate(ex)


@router.get("/projects/{project_id}/boq-pdf-extractions", response_model=list[BoqPdfExtractionOut])
async def list_boq_pdf_extractions_endpoint(
    project_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> list[BoqPdfExtractionOut]:
    return [BoqPdfExtractionOut.model_validate(e) for e in await boq_pdf_service.list_extractions(session, project_id)]


@router.get("/boq-pdf-extractions/{extraction_id}", response_model=BoqPdfExtractionDetail)
async def get_boq_pdf_extraction_endpoint(
    extraction_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> BoqPdfExtractionDetail:
    return _detail(await boq_pdf_service.get_extraction(session, extraction_id))


@router.get("/boq-pdf-extractions/{extraction_id}/file-url", response_model=BoqPdfFileUrlOut)
async def boq_pdf_file_url_endpoint(
    extraction_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> BoqPdfFileUrlOut:
    """A short-lived link to the source PDF, so a row's page can be opened for checking
    (append `#page=N`)."""
    ex = await boq_pdf_service.get_extraction(session, extraction_id)
    url = await boq_pdf_service.source_url(session, ctx, ex)
    return BoqPdfFileUrlOut(url=url, filename=ex.source_filename)


@router.put("/boq-pdf-extractions/{extraction_id}/rows", response_model=BoqPdfExtractionDetail)
async def save_boq_pdf_rows_endpoint(
    extraction_id: UUID,
    body: BoqPdfRowsIn,
    ctx: RequestContext = Depends(require_roles(*_BOQ_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> BoqPdfExtractionDetail:
    ex = await boq_pdf_service.save_rows(session, ctx, extraction_id, [r.model_dump() for r in body.rows])
    return _detail(ex)


@router.post("/boq-pdf-extractions/{extraction_id}/commit", response_model=BoqPdfCommitOut, status_code=201)
async def commit_boq_pdf_extraction_endpoint(
    extraction_id: UUID,
    ctx: RequestContext = Depends(require_roles(*_BOQ_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> BoqPdfCommitOut:
    created = await boq_pdf_service.commit_extraction(session, ctx, extraction_id)
    ex = await boq_pdf_service.get_extraction(session, extraction_id)
    assert ex.batch_id is not None
    return BoqPdfCommitOut(created_count=len(created), batch_id=ex.batch_id, created_item_ids=[i.id for i in created])


@router.post("/boq-pdf-extractions/{extraction_id}/retry", response_model=BoqPdfExtractionOut, status_code=202)
async def retry_boq_pdf_extraction_endpoint(
    extraction_id: UUID,
    ctx: RequestContext = Depends(require_roles(*_BOQ_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> BoqPdfExtractionOut:
    ex = await boq_pdf_service.get_extraction(session, extraction_id)
    if ex.status not in ("failed", "ready"):
        raise ValidationAppError(f"Cannot re-run an extraction that is {ex.status}")
    if ex.status == "ready" and any(r.get("edited") for r in ex.rows):
        raise ValidationAppError("This extraction has manual edits; re-running would discard them. Start a new extraction instead.")
    ex.status, ex.error, ex.pages_done, ex.rows, ex.page_summary = "queued", None, 0, [], []
    await session.flush()
    _dispatch_extraction(ctx, ex.id)
    return BoqPdfExtractionOut.model_validate(ex)


# ------------------------------------------------------------------ drawing annotations


@router.post("/projects/{project_id}/drawing-annotations:read", response_model=AnnotationReadAccepted, status_code=202)
async def read_annotations_endpoint(
    project_id: UUID,
    body: AnnotationReadIn,
    ctx: RequestContext = Depends(require_roles(*_READ_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> AnnotationReadAccepted:
    from app.workers.tasks.ai_reading import read_sheet_annotations

    ids = await annotations_service.queue_sheets(session, ctx, project_id, drawing_id=body.drawing_id, force=body.force)
    for i in range(0, len(ids), 10):
        read_sheet_annotations.apply_async(
            args=([str(s) for s in ids[i : i + 10]], str(ctx.tenant_id), str(ctx.user_id) if ctx.user_id else None, list(ctx.roles)),
            countdown=2,
        )
    return AnnotationReadAccepted(queued_sheets=len(ids))


@router.get("/projects/{project_id}/drawing-annotations", response_model=AnnotationPage)
async def list_annotations_endpoint(
    project_id: UUID,
    drawing_id: UUID | None = None,
    sheet_id: UUID | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    ctx: RequestContext = CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> AnnotationPage:
    rows, total = await annotations_service.list_annotations(
        session, project_id, drawing_id=drawing_id, sheet_id=sheet_id, limit=limit, offset=offset
    )
    return AnnotationPage(items=[DrawingAnnotationOut.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.get("/projects/{project_id}/drawing-annotations/summary", response_model=AnnotationSummaryOut)
async def annotation_summary_endpoint(
    project_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> AnnotationSummaryOut:
    return AnnotationSummaryOut(**await annotations_service.summary(session, project_id))
