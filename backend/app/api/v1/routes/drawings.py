from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_session, require_roles
from app.core.config import Settings, get_settings
from app.core.context import RequestContext
from app.core.enums import Role
from app.core.errors import ValidationAppError
from app.schemas.drawings import (
    DrawingMeasurementOut,
    DrawingOut,
    DrawingSheetOut,
    ExtractionJobOut,
    ManualScaleCalibration,
    PdfLayerMappingRuleIn,
    PdfLayerMappingRuleOut,
    SheetScaleCalibrationOut,
    SheetSearchQuery,
    SheetSearchResult,
)
from app.services import takeoff as takeoff_service

router = APIRouter(tags=["takeoff"])

_UPLOAD_ROLES = (Role.ESTIMATOR.value, Role.LEAD_ESTIMATOR.value, Role.PROCUREMENT_HEAD.value, Role.BD_DIRECTOR.value, Role.MANAGING_DIRECTOR.value)
_ALLOWED_CONTENT_TYPES = {"application/pdf", "application/dxf", "image/vnd.dxf"}


@router.post("/projects/{project_id}/drawings", response_model=DrawingOut, status_code=201)
async def upload_drawing_endpoint(
    project_id: UUID,
    file: UploadFile = File(...),
    ctx: RequestContext = Depends(require_roles(*_UPLOAD_ROLES)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> DrawingOut:
    content_type = file.content_type or ""
    filename = file.filename or "upload"
    if content_type not in _ALLOWED_CONTENT_TYPES and not filename.lower().endswith((".pdf", ".dxf")):
        raise ValidationAppError(f"Unsupported content type '{content_type}' for {filename}")

    data = await file.read(settings.max_upload_size_bytes + 1)
    if len(data) > settings.max_upload_size_bytes:
        raise ValidationAppError(f"File exceeds the {settings.max_upload_size_bytes} byte upload limit")

    drawing = await takeoff_service.upload_drawing(session, ctx, project_id, filename, content_type, data)
    return DrawingOut.model_validate(drawing)


@router.post("/drawings/{drawing_id}/ingest", status_code=202)
async def ingest_drawing_endpoint(
    drawing_id: UUID,
    ctx: RequestContext = Depends(require_roles(*_UPLOAD_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    job_ids = await takeoff_service.trigger_ingest(session, ctx, drawing_id)
    return {"job_ids": job_ids}


@router.get("/drawings/{drawing_id}", response_model=DrawingOut)
async def get_drawing_endpoint(
    drawing_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> DrawingOut:
    return DrawingOut.model_validate(await takeoff_service.get_drawing(session, drawing_id))


@router.get("/drawings/{drawing_id}/jobs", response_model=list[ExtractionJobOut])
async def list_jobs_endpoint(
    drawing_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> list[ExtractionJobOut]:
    jobs = await takeoff_service.list_jobs(session, drawing_id)
    return [ExtractionJobOut.model_validate(j) for j in jobs]


@router.get("/drawings/{drawing_id}/sheets/{sheet_index}", response_model=DrawingSheetOut)
async def get_sheet_endpoint(
    drawing_id: UUID, sheet_index: int, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> DrawingSheetOut:
    sheet = await takeoff_service.get_sheet(session, drawing_id, sheet_index)
    return DrawingSheetOut.model_validate(sheet)


@router.patch("/drawings/{drawing_id}/sheets/{sheet_index}/scale", response_model=DrawingSheetOut)
async def set_manual_scale_endpoint(
    drawing_id: UUID,
    sheet_index: int,
    data: ManualScaleCalibration,
    ctx: RequestContext = Depends(require_roles(*_UPLOAD_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> DrawingSheetOut:
    sheet = await takeoff_service.set_manual_scale(
        session, ctx, drawing_id, sheet_index, data.p1, data.p2, data.known_length_m
    )
    return DrawingSheetOut.model_validate(sheet)


@router.get("/drawings/{drawing_id}/sheets/{sheet_index}/scale-calibrations", response_model=list[SheetScaleCalibrationOut])
async def list_scale_calibrations_endpoint(
    drawing_id: UUID, sheet_index: int, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> list[SheetScaleCalibrationOut]:
    calibrations = await takeoff_service.list_scale_calibrations(session, drawing_id, sheet_index)
    return [SheetScaleCalibrationOut.model_validate(c) for c in calibrations]


@router.post("/drawings/{drawing_id}/sheets/{sheet_index}/scale-calibrations/{calibration_id}/revert", response_model=DrawingSheetOut)
async def revert_scale_calibration_endpoint(
    drawing_id: UUID, sheet_index: int, calibration_id: UUID,
    ctx: RequestContext = Depends(require_roles(*_UPLOAD_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> DrawingSheetOut:
    sheet = await takeoff_service.revert_scale_calibration(session, ctx, drawing_id, sheet_index, calibration_id)
    return DrawingSheetOut.model_validate(sheet)


@router.put("/projects/{project_id}/pdf-layer-mapping-rules", response_model=list[PdfLayerMappingRuleOut])
async def replace_pdf_layer_mapping_rules_endpoint(
    project_id: UUID,
    data: list[PdfLayerMappingRuleIn],
    ctx: RequestContext = Depends(require_roles(*_UPLOAD_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> list[PdfLayerMappingRuleOut]:
    rules = await takeoff_service.replace_pdf_layer_mapping_rules(
        session, ctx, project_id, [r.model_dump() for r in data]
    )
    return [PdfLayerMappingRuleOut.model_validate(r) for r in rules]


@router.get("/projects/{project_id}/pdf-layer-mapping-rules", response_model=list[PdfLayerMappingRuleOut])
async def list_pdf_layer_mapping_rules_endpoint(
    project_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> list[PdfLayerMappingRuleOut]:
    rules = await takeoff_service.list_pdf_layer_mapping_rules(session, project_id)
    return [PdfLayerMappingRuleOut.model_validate(r) for r in rules]


@router.get("/drawings/{drawing_id}/measurements", response_model=list[DrawingMeasurementOut])
async def list_measurements_endpoint(
    drawing_id: UUID,
    sheet_id: UUID | None = None,
    ctx: RequestContext = CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> list[DrawingMeasurementOut]:
    measurements = await takeoff_service.list_measurements(session, drawing_id, sheet_id)
    return [DrawingMeasurementOut.model_validate(m) for m in measurements]


@router.get("/drawings/{drawing_id}/download")
async def download_drawing_endpoint(
    drawing_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> RedirectResponse:
    url = await takeoff_service.presigned_download_url(session, ctx, drawing_id)
    return RedirectResponse(url)


@router.post("/projects/{project_id}/sheets:search", response_model=list[SheetSearchResult])
async def search_sheets_endpoint(
    project_id: UUID,
    data: SheetSearchQuery,
    ctx: RequestContext = CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> list[SheetSearchResult]:
    rows = await takeoff_service.search_sheets(session, project_id, data.query, data.top_k)
    return [SheetSearchResult(**row) for row in rows]
