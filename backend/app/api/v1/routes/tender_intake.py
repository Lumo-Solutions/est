from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi import Response
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_session, require_roles
from app.core.config import Settings, get_settings
from app.core.context import RequestContext
from app.core.errors import ValidationAppError
from app.intake.constants import CLASS_ADMIN_ROLES, CONFIRM_ROLES, UPLOAD_ROLES
from app.schemas.tender_intake import (
    AddendumOut,
    BoqPrefillOut,
    BulkConfirmIn,
    BulkReclassifyIn,
    IntakeSettingsIn,
    IntakeSettingsOut,
    TreeOut,
    BulkConfirmOut,
    ClassificationOut,
    DocFilter,
    DocumentPage,
    EditMetadataIn,
    ExcludeIn,
    ProjectDocumentDetailOut,
    ProjectDocumentOut,
    ReclassifyIn,
    TenderClassOut,
    TenderClassUpdate,
    PackageControlOut,
    RegisterPackageIn,
    RegisterPackageOut,
    TenderPackageAccepted,
    TenderPackageOut,
    TreeItemPage,
    UploadResult,
)
from app.services import ai_admin
from app.services import tender_intake as intake_service
from app.services import tender_intake_tree
from app.services import tender_intake_upload as upload_service

router = APIRouter(tags=["tender-intake"])

_MEDIA_TYPES = {
    "pdf": "application/pdf",
    "dxf": "application/dxf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xls": "application/vnd.ms-excel",
    "csv": "text/csv",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "zip": "application/zip",
}


async def _read_uploads(files: list[UploadFile], settings: Settings) -> list[tuple[str, bytes]]:
    if len(files) > settings.intake_max_files_per_request:
        raise ValidationAppError(
            f"At most {settings.intake_max_files_per_request} files per request: put the rest in a .zip or send another batch"
        )
    out: list[tuple[str, bytes]] = []
    total = 0
    for f in files:
        # This path buffers the file: its ceiling is the per-request limit (big files use the streaming upload).
        ceiling = min(settings.intake_max_file_size_bytes, settings.intake_max_request_bytes)
        data = await f.read(ceiling + 1)
        if len(data) > ceiling:
            raise ValidationAppError(f"{f.filename!r} is larger than the {ceiling // (1024 * 1024)} MiB this endpoint takes; the app uploads big files with the streaming upload")
        total += len(data)
        if total > settings.intake_max_request_bytes:
            raise ValidationAppError(f"This batch is larger than the {settings.intake_max_request_bytes // (1024 * 1024)} MiB per-request limit: send fewer files at once")
        out.append((f.filename or "unnamed", data))
    return out


def _dispatch(ctx: RequestContext, package_id: UUID, document_ids: list[UUID] | None = None) -> None:
    """Asks the dispatcher to enqueue the pack's received files (after the request transaction commits). The files
    are in the database either way: if this message is lost the 30-second tick picks them up."""
    from app.workers.tasks.tender_intake import dispatch_intake

    try:
        dispatch_intake.apply_async(args=(str(ctx.tenant_id), str(package_id)), countdown=2)
    except Exception:  # noqa: BLE001 -- the tick covers it
        pass


@router.post("/projects/{project_id}/tender-packages", response_model=TenderPackageAccepted, status_code=202)
async def create_package_endpoint(
    project_id: UUID,
    files: list[UploadFile] = File(...),
    label: str | None = Form(default=None),
    transmittal_ref: str | None = Form(default=None),
    received_date: date | None = Form(default=None),
    ctx: RequestContext = Depends(require_roles(*UPLOAD_ROLES)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> TenderPackageAccepted:
    uploads = await _read_uploads(files, settings)
    package, doc_ids = await intake_service.create_package(
        session, ctx, project_id, uploads, label=label, transmittal_ref=transmittal_ref, received_date=received_date
    )
    _dispatch(ctx, package.id, doc_ids)
    return TenderPackageAccepted(package_id=package.id, file_count=package.file_count, status=package.status)


@router.post("/tender-packages/{package_id}/files", response_model=TenderPackageAccepted, status_code=202)
async def add_files_endpoint(
    package_id: UUID,
    files: list[UploadFile] = File(...),
    ctx: RequestContext = Depends(require_roles(*UPLOAD_ROLES)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> TenderPackageAccepted:
    uploads = await _read_uploads(files, settings)
    package, doc_ids = await intake_service.add_files(session, ctx, package_id, uploads)
    _dispatch(ctx, package.id, doc_ids)
    return TenderPackageAccepted(package_id=package.id, file_count=package.file_count, status=package.status)


# --------------------------------------------------------------- resumable upload (the UI's path)
@router.post("/projects/{project_id}/tender-packages/register", response_model=RegisterPackageOut)
async def register_files_endpoint(
    project_id: UUID,
    data: RegisterPackageIn,
    ctx: RequestContext = Depends(require_roles(*UPLOAD_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> RegisterPackageOut:
    """Announces files (path, size, sha256) before any bytes are sent. The answer says which files still need their
    bytes: re-dropping the same folder after an interruption resumes instead of starting over."""
    out = await upload_service.register_files(session, ctx, project_id, data)
    # Files whose bytes were already here are `received` at once.
    _dispatch(ctx, out.package_id)
    return out


@router.put("/tender-packages/{package_id}/documents/{document_id}/content", response_model=UploadResult)
async def upload_document_content_endpoint(
    package_id: UUID,
    document_id: UUID,
    request: Request,
    ctx: RequestContext = Depends(require_roles(*UPLOAD_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> UploadResult:
    """One file's raw bytes (not multipart), streamed straight to S3 a chunk at a time: the server never holds more
    than one upload part in memory. The registered sha256 must match what arrives."""
    raw_length = request.headers.get("content-length")
    result = await upload_service.receive_upload(
        session, ctx, package_id, document_id, request.stream(),
        declared_size=int(raw_length) if raw_length and raw_length.isdigit() else None,
    )
    _dispatch(ctx, package_id)
    return result


@router.post("/tender-packages/{package_id}/pause", response_model=PackageControlOut)
async def pause_package_endpoint(
    package_id: UUID, ctx: RequestContext = Depends(require_roles(*CONFIRM_ROLES)), session: AsyncSession = Depends(get_session)
) -> PackageControlOut:
    return await upload_service.pause_package(session, ctx, package_id)


@router.post("/tender-packages/{package_id}/resume", response_model=PackageControlOut)
async def resume_package_endpoint(
    package_id: UUID, ctx: RequestContext = Depends(require_roles(*CONFIRM_ROLES)), session: AsyncSession = Depends(get_session)
) -> PackageControlOut:
    out = await upload_service.resume_package(session, ctx, package_id)
    _dispatch(ctx, package_id)
    return out


@router.post("/tender-packages/{package_id}/cancel", response_model=PackageControlOut)
async def cancel_package_endpoint(
    package_id: UUID, ctx: RequestContext = Depends(require_roles(*CONFIRM_ROLES)), session: AsyncSession = Depends(get_session)
) -> PackageControlOut:
    return await upload_service.cancel_package(session, ctx, package_id)


@router.get("/projects/{project_id}/tender-packages", response_model=list[TenderPackageOut])
async def list_packages_endpoint(
    project_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> list[TenderPackageOut]:
    return [TenderPackageOut.model_validate(p) for p in await intake_service.list_packages(session, project_id)]


@router.get("/tender-packages/{package_id}", response_model=TenderPackageOut)
async def get_package_endpoint(
    package_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> TenderPackageOut:
    return TenderPackageOut.model_validate(await intake_service.get_package(session, package_id))


@router.get("/projects/{project_id}/tender-documents", response_model=DocumentPage)
async def list_documents_endpoint(
    project_id: UUID,
    package_id: UUID | None = None,
    doc_class: str | None = None,
    status: str | None = None,
    flag: str | None = None,
    q: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    ctx: RequestContext = CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> DocumentPage:
    rows, total = await intake_service.list_documents(
        session, project_id, package_id=package_id, doc_class=doc_class, status=status, flag=flag, q=q, limit=limit, offset=offset
    )
    return DocumentPage(items=[ProjectDocumentOut.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.get("/projects/{project_id}/document-register", response_model=DocumentPage)
async def document_register_endpoint(
    project_id: UUID,
    doc_class: str | None = None,
    q: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    ctx: RequestContext = CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> DocumentPage:
    rows, total = await intake_service.list_documents(
        session, project_id, doc_class=doc_class, status="routed", routed_kind="register", q=q, limit=limit, offset=offset
    )
    return DocumentPage(items=[ProjectDocumentOut.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.get("/projects/{project_id}/addenda", response_model=list[AddendumOut])
async def list_addenda_endpoint(
    project_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> list[AddendumOut]:
    return await intake_service.list_addenda(session, project_id)


@router.get("/tender-documents/{document_id}", response_model=ProjectDocumentDetailOut)
async def get_document_endpoint(
    document_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> ProjectDocumentDetailOut:
    doc, classifications = await intake_service.get_document_detail(session, document_id)
    out = ProjectDocumentDetailOut.model_validate(doc)
    out.classifications = [ClassificationOut.model_validate(c) for c in classifications]
    return out


@router.get("/tender-documents/{document_id}/download")
async def download_document_endpoint(
    document_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> RedirectResponse:
    return RedirectResponse(await intake_service.download_url(session, ctx, document_id), status_code=302)


@router.get("/tender-documents/{document_id}/content")
async def document_content_endpoint(
    document_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> Response:
    doc, data = await intake_service.document_content(session, ctx, document_id)
    media = _MEDIA_TYPES.get(doc.ext, "application/octet-stream")
    return Response(content=data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{doc.original_filename}"'})


@router.get("/tender-documents/{document_id}/boq-prefill", response_model=BoqPrefillOut)
async def boq_prefill_endpoint(
    document_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> BoqPrefillOut:
    return await intake_service.boq_prefill(session, document_id)


@router.post("/tender-documents/{document_id}/confirm", response_model=ProjectDocumentOut)
async def confirm_endpoint(
    document_id: UUID, ctx: RequestContext = Depends(require_roles(*CONFIRM_ROLES)), session: AsyncSession = Depends(get_session)
) -> ProjectDocumentOut:
    return ProjectDocumentOut.model_validate(await intake_service.confirm_document(session, ctx, document_id))


@router.post("/tender-documents/{document_id}/reclassify", response_model=ProjectDocumentOut)
async def reclassify_endpoint(
    document_id: UUID, data: ReclassifyIn,
    ctx: RequestContext = Depends(require_roles(*CONFIRM_ROLES)), session: AsyncSession = Depends(get_session),
) -> ProjectDocumentOut:
    doc = await intake_service.reclassify(
        session, ctx, document_id, data.doc_class, data.sub_type, data.note, drawing_type=data.drawing_type, confirm=data.confirm
    )
    return ProjectDocumentOut.model_validate(doc)


@router.post("/tender-documents/{document_id}/edit", response_model=ProjectDocumentOut)
async def edit_endpoint(
    document_id: UUID, data: EditMetadataIn,
    ctx: RequestContext = Depends(require_roles(*CONFIRM_ROLES)), session: AsyncSession = Depends(get_session),
) -> ProjectDocumentOut:
    doc = await intake_service.edit_metadata(
        session, ctx, document_id, metadata=data.metadata, title=data.title, document_number=data.document_number,
        revision_label=data.revision_label,
    )
    return ProjectDocumentOut.model_validate(doc)


@router.post("/tender-documents/{document_id}/exclude", response_model=ProjectDocumentOut)
async def exclude_endpoint(
    document_id: UUID, data: ExcludeIn,
    ctx: RequestContext = Depends(require_roles(*CONFIRM_ROLES)), session: AsyncSession = Depends(get_session),
) -> ProjectDocumentOut:
    return ProjectDocumentOut.model_validate(await intake_service.exclude(session, ctx, document_id, data.reason))


@router.post("/tender-documents/{document_id}/rerun", response_model=ProjectDocumentOut, status_code=202)
async def rerun_endpoint(
    document_id: UUID, ctx: RequestContext = Depends(require_roles(*CONFIRM_ROLES)), session: AsyncSession = Depends(get_session)
) -> ProjectDocumentOut:
    return ProjectDocumentOut.model_validate(await intake_service.request_rerun(session, ctx, document_id))


@router.post("/projects/{project_id}/tender-documents/bulk-confirm", response_model=BulkConfirmOut)
async def bulk_confirm_endpoint(
    project_id: UUID, data: BulkConfirmIn,
    ctx: RequestContext = Depends(require_roles(*CONFIRM_ROLES)), session: AsyncSession = Depends(get_session),
) -> BulkConfirmOut:
    return await intake_service.bulk_confirm(
        session, ctx, project_id, package_id=data.package_id, document_ids=data.document_ids, min_confidence=data.min_confidence,
        doc_filter=data.filter, cursor=data.cursor,
    )


@router.post("/projects/{project_id}/tender-documents/bulk-reclassify", response_model=BulkConfirmOut)
async def bulk_reclassify_endpoint(
    project_id: UUID, data: BulkReclassifyIn,
    ctx: RequestContext = Depends(require_roles(*CONFIRM_ROLES)), session: AsyncSession = Depends(get_session),
) -> BulkConfirmOut:
    return await intake_service.bulk_reclassify(
        session, ctx, project_id, data.document_ids, data.doc_class, data.sub_type, data.drawing_type, data.note, data.confirm,
        doc_filter=data.filter, cursor=data.cursor,
    )


@router.get("/projects/{project_id}/tender-documents/tree", response_model=TreeOut)
async def document_tree_endpoint(
    project_id: UUID,
    ctx: RequestContext = CurrentUser,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> TreeOut:
    """Counts only (summary, group counts, folder counts, packs): never the documents themselves, so it stays small
    and fast for a pack of thousands. The documents of one group come from `/tender-documents/items`."""
    status = await ai_admin.get_status(session, ctx, settings)
    return await tender_intake_tree.build_summary(session, project_id, ai_available=status.available, ai_message=status.message)


@router.get("/projects/{project_id}/tender-documents/items", response_model=TreeItemPage)
async def tree_items_endpoint(
    project_id: UUID,
    package_id: UUID | None = None,
    doc_class: str | None = None,
    discipline: str | None = None,
    drawing_type: str | None = None,
    display_status: str | None = None,
    decided_by: str | None = None,
    flag: str | None = None,
    folder: str | None = None,
    include_subfolders: bool = False,
    has_class: bool | None = None,
    q: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    ctx: RequestContext = CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> TreeItemPage:
    """One page of the documents matching a filter, as the compact rows the project page shows, in a stable order."""
    doc_filter = DocFilter(
        package_id=package_id, doc_class=doc_class, discipline=discipline, drawing_type=drawing_type,
        display_status=display_status, decided_by=decided_by, flag=flag, folder=folder, include_subfolders=include_subfolders,
        has_class=has_class, q=q,
    )
    items, total = await tender_intake_tree.list_tree_items(session, project_id, doc_filter, limit=limit, offset=offset)
    return TreeItemPage(items=items, total=total, limit=limit, offset=offset)


@router.get("/tender-intake/settings", response_model=IntakeSettingsOut)
async def intake_settings_endpoint(ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)) -> IntakeSettingsOut:
    return IntakeSettingsOut(auto_accept_min=await intake_service.get_auto_accept_min(session))


@router.put("/admin/intake-settings", response_model=IntakeSettingsOut)
async def set_intake_settings_endpoint(
    data: IntakeSettingsIn,
    ctx: RequestContext = Depends(require_roles(*CLASS_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> IntakeSettingsOut:
    return IntakeSettingsOut(auto_accept_min=await intake_service.set_auto_accept_min(session, ctx, data.auto_accept_min))


@router.get("/tender-classes", response_model=list[TenderClassOut])
async def list_classes_endpoint(ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)) -> list[TenderClassOut]:
    return await intake_service.list_classes(session)


@router.patch("/tender-classes/{code}", response_model=TenderClassOut)
async def update_class_endpoint(
    code: str, data: TenderClassUpdate,
    ctx: RequestContext = Depends(require_roles(*CLASS_ADMIN_ROLES)), session: AsyncSession = Depends(get_session),
) -> TenderClassOut:
    return await intake_service.update_class(session, ctx, code, data)
