from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_session, require_roles
from app.boq.import_parser import BoqImportColumnMapping
from app.core.context import RequestContext
from app.core.enums import Role
from app.core.errors import ValidationAppError
from app.schemas.boq import (
    AddMeasurementLink,
    BoqImportColumnMappingIn,
    BoqImportCommitOut,
    BoqImportPreviewOut,
    BoqLineItemCreate,
    BoqLineItemOut,
    BoqToleranceOut,
    BoqToleranceSet,
    LinkedMeasurementOut,
)
from app.services import boq as boq_service
from app.services import boq_import as boq_import_service

router = APIRouter(tags=["boq"])

# Structural edits (create/reparent the tender BOQ tree) mirror the DB
# policy's WRITE_ROLES in migration 0011 -- more senior than day-to-day
# reconciliation, matching trade taxonomy's own write-role precedent.
_STRUCTURE_ROLES = (Role.LEAD_ESTIMATOR.value, Role.PROCUREMENT_HEAD.value, Role.MANAGING_DIRECTOR.value)
_DELETE_ROLES = (Role.LEAD_ESTIMATOR.value, Role.PROCUREMENT_HEAD.value, Role.MANAGING_DIRECTOR.value)
# Linking a measurement / recomputing a discrepancy is normal, frequent
# estimating work -- same role set as everywhere else in Module B
# (app/api/v1/routes/drawings.py's _UPLOAD_ROLES).
_RECONCILE_ROLES = (
    Role.ESTIMATOR.value, Role.LEAD_ESTIMATOR.value, Role.PROCUREMENT_HEAD.value,
    Role.BD_DIRECTOR.value, Role.MANAGING_DIRECTOR.value,
)


@router.post("/projects/{project_id}/boq-items", response_model=BoqLineItemOut, status_code=201)
async def create_boq_item_endpoint(
    project_id: UUID,
    data: BoqLineItemCreate,
    ctx: RequestContext = Depends(require_roles(*_STRUCTURE_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> BoqLineItemOut:
    item = await boq_service.create_line_item(session, ctx, project_id, data)
    return BoqLineItemOut.model_validate(item)


@router.get("/projects/{project_id}/boq-items", response_model=list[BoqLineItemOut])
async def list_boq_items_endpoint(
    project_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> list[BoqLineItemOut]:
    items = await boq_service.list_line_items(session, ctx, project_id)
    return [BoqLineItemOut.model_validate(i) for i in items]


@router.get("/boq-items/{item_id}", response_model=BoqLineItemOut)
async def get_boq_item_endpoint(
    item_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> BoqLineItemOut:
    item = await boq_service.get_line_item(session, ctx, item_id)
    return BoqLineItemOut.model_validate(item)


@router.post("/boq-items/{item_id}/measurements", response_model=BoqLineItemOut)
async def add_measurement_link_endpoint(
    item_id: UUID,
    data: AddMeasurementLink,
    ctx: RequestContext = Depends(require_roles(*_RECONCILE_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> BoqLineItemOut:
    item = await boq_service.add_measurement_link(session, ctx, item_id, data.measurement_id)
    return BoqLineItemOut.model_validate(item)


@router.delete("/boq-items/{item_id}/measurements/{measurement_id}", response_model=BoqLineItemOut)
async def remove_measurement_link_endpoint(
    item_id: UUID,
    measurement_id: UUID,
    ctx: RequestContext = Depends(require_roles(*_RECONCILE_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> BoqLineItemOut:
    item = await boq_service.remove_measurement_link(session, ctx, item_id, measurement_id)
    return BoqLineItemOut.model_validate(item)


@router.get("/boq-items/{item_id}/measurements", response_model=list[LinkedMeasurementOut])
async def list_measurement_links_endpoint(
    item_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> list[LinkedMeasurementOut]:
    measurements = await boq_service.list_measurement_links(session, item_id)
    return [LinkedMeasurementOut.model_validate(m) for m in measurements]


@router.post("/boq-items/{item_id}/reconcile", response_model=BoqLineItemOut)
async def reconcile_boq_item_endpoint(
    item_id: UUID,
    ctx: RequestContext = Depends(require_roles(*_RECONCILE_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> BoqLineItemOut:
    item = await boq_service.reconcile_item(session, ctx, item_id)
    return BoqLineItemOut.model_validate(item)


@router.delete("/boq-items/{item_id}", status_code=204, response_model=None)
async def delete_boq_item_endpoint(
    item_id: UUID,
    ctx: RequestContext = Depends(require_roles(*_DELETE_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> None:
    await boq_service.delete_line_item(session, ctx, item_id)


@router.put("/projects/{project_id}/boq-tolerances", response_model=BoqToleranceOut)
async def set_boq_tolerance_endpoint(
    project_id: UUID,
    data: BoqToleranceSet,
    ctx: RequestContext = Depends(require_roles(*_STRUCTURE_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> BoqToleranceOut:
    row = await boq_service.set_tolerance(session, ctx, project_id, data.trade_node_id, data.tolerance_pct)
    return BoqToleranceOut.model_validate(row)


@router.get("/projects/{project_id}/boq-tolerances", response_model=list[BoqToleranceOut])
async def list_boq_tolerances_endpoint(
    project_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> list[BoqToleranceOut]:
    rows = await boq_service.list_tolerances(session, project_id)
    return [BoqToleranceOut.model_validate(r) for r in rows]


@router.get("/projects/{project_id}/measurements:unlinked", response_model=list[LinkedMeasurementOut])
async def list_unlinked_measurements_endpoint(
    project_id: UUID,
    drawing_id: UUID | None = None,
    ctx: RequestContext = CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> list[LinkedMeasurementOut]:
    measurements = await boq_service.list_unlinked_measurements(session, project_id, drawing_id)
    return [LinkedMeasurementOut.model_validate(m) for m in measurements]


def _parse_mapping(mapping: str) -> BoqImportColumnMapping:
    try:
        parsed = BoqImportColumnMappingIn.model_validate_json(mapping)
    except ValueError as exc:
        raise ValidationAppError(f"Invalid mapping JSON: {exc}") from exc
    return BoqImportColumnMapping(**parsed.model_dump())


@router.post("/projects/{project_id}/boq-items:import-preview", response_model=BoqImportPreviewOut)
async def import_boq_preview_endpoint(
    project_id: UUID,
    file: UploadFile = File(...),
    mapping: str = Form(..., description="JSON-encoded BoqImportColumnMappingIn"),
    ctx: RequestContext = Depends(require_roles(*_STRUCTURE_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> BoqImportPreviewOut:
    data = await file.read()
    result = await boq_import_service.preview_import(
        session, ctx, project_id, data, file.filename or "upload", _parse_mapping(mapping)
    )
    return BoqImportPreviewOut(
        rows=[
            {
                "row_number": r.row_number, "item_no": r.item_no, "description": r.description, "uom": r.uom,
                "boq_quantity": r.boq_quantity, "parent_item_no": r.parent_item_no, "errors": r.errors,
            }
            for r in result.rows
        ],
        valid_count=result.valid_count,
        error_count=result.error_count,
    )


@router.post("/projects/{project_id}/boq-items:import-commit", response_model=BoqImportCommitOut)
async def import_boq_commit_endpoint(
    project_id: UUID,
    file: UploadFile = File(...),
    mapping: str = Form(..., description="JSON-encoded BoqImportColumnMappingIn"),
    ctx: RequestContext = Depends(require_roles(*_STRUCTURE_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> BoqImportCommitOut:
    data = await file.read()
    created = await boq_import_service.commit_import(
        session, ctx, project_id, data, file.filename or "upload", _parse_mapping(mapping)
    )
    return BoqImportCommitOut(created_item_ids=[item.id for item in created], created_count=len(created))
