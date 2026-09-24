from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_session, require_roles
from app.core.context import RequestContext
from app.core.enums import Role
from app.schemas.boq import BoqLineItemOut
from app.schemas.procurement import (
    MatchedVendorOut,
    ProcurementPackageCreate,
    ProcurementPackageItemsAdd,
    ProcurementPackageOut,
    RfqCreateRequest,
    RfqOut,
    RfqResendRequest,
)
from app.services import procurement as procurement_service

router = APIRouter(tags=["procurement"])

# Drafting (packages/items/RFQs) mirrors boq.py's _STRUCTURE_ROLES -- more
# senior than day-to-day estimating, matching migration 0015's RLS policy.
_STRUCTURE_ROLES = (Role.LEAD_ESTIMATOR.value, Role.PROCUREMENT_HEAD.value, Role.BD_DIRECTOR.value, Role.MANAGING_DIRECTOR.value)
# Dispatch/resend role + MFA step-up are enforced inside
# app/services/procurement.py::_require_dispatch_authority (same split as
# app/api/v1/routes/approvals.py's decide endpoint), not as a route
# Depends -- CurrentUser here so the 403/step-up-required error comes from
# one place regardless of call site.


@router.post("/projects/{project_id}/procurement-packages", response_model=ProcurementPackageOut, status_code=201)
async def create_package_endpoint(
    project_id: UUID,
    data: ProcurementPackageCreate,
    ctx: RequestContext = Depends(require_roles(*_STRUCTURE_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> ProcurementPackageOut:
    package = await procurement_service.create_package(session, ctx, project_id, data)
    return ProcurementPackageOut.model_validate(package)


@router.get("/projects/{project_id}/procurement-packages", response_model=list[ProcurementPackageOut])
async def list_packages_endpoint(
    project_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> list[ProcurementPackageOut]:
    packages = await procurement_service.list_packages(session, project_id)
    return [ProcurementPackageOut.model_validate(p) for p in packages]


@router.get("/procurement-packages/{package_id}", response_model=ProcurementPackageOut)
async def get_package_endpoint(
    package_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> ProcurementPackageOut:
    package = await procurement_service.get_package(session, package_id)
    return ProcurementPackageOut.model_validate(package)


@router.post("/procurement-packages/{package_id}/items", response_model=list[BoqLineItemOut], status_code=201)
async def add_package_items_endpoint(
    package_id: UUID,
    data: ProcurementPackageItemsAdd,
    ctx: RequestContext = Depends(require_roles(*_STRUCTURE_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> list[BoqLineItemOut]:
    await procurement_service.add_items(session, ctx, package_id, data.boq_line_item_ids)
    items = await procurement_service.list_package_boq_items(session, package_id)
    return [BoqLineItemOut.model_validate(i) for i in items]


@router.get("/procurement-packages/{package_id}/items", response_model=list[BoqLineItemOut])
async def list_package_items_endpoint(
    package_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> list[BoqLineItemOut]:
    items = await procurement_service.list_package_boq_items(session, package_id)
    return [BoqLineItemOut.model_validate(i) for i in items]


@router.get("/procurement-packages/{package_id}/matched-vendors", response_model=list[MatchedVendorOut])
async def matched_vendors_endpoint(
    package_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> list[MatchedVendorOut]:
    return await procurement_service.match_vendors(session, package_id)


@router.post("/procurement-packages/{package_id}/rfqs", response_model=list[RfqOut], status_code=201)
async def create_rfqs_endpoint(
    package_id: UUID,
    data: RfqCreateRequest,
    ctx: RequestContext = Depends(require_roles(*_STRUCTURE_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> list[RfqOut]:
    rfqs = await procurement_service.create_rfqs(session, ctx, package_id, data)
    return [RfqOut.model_validate(r) for r in rfqs]


@router.get("/procurement-packages/{package_id}/rfqs", response_model=list[RfqOut])
async def list_rfqs_endpoint(
    package_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> list[RfqOut]:
    rfqs = await procurement_service.list_rfqs(session, package_id)
    return [RfqOut.model_validate(r) for r in rfqs]


@router.get("/rfqs/{rfq_id}", response_model=RfqOut)
async def get_rfq_endpoint(
    rfq_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> RfqOut:
    rfq = await procurement_service.get_rfq(session, rfq_id)
    return RfqOut.model_validate(rfq)


@router.post("/rfqs/{rfq_id}/dispatch", response_model=RfqOut)
async def dispatch_rfq_endpoint(
    rfq_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> RfqOut:
    rfq = await procurement_service.dispatch_rfq(session, ctx, rfq_id)
    return RfqOut.model_validate(rfq)


@router.post("/rfqs/{rfq_id}/resend", response_model=RfqOut)
async def resend_rfq_endpoint(
    rfq_id: UUID,
    data: RfqResendRequest,
    ctx: RequestContext = CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> RfqOut:
    rfq = await procurement_service.resend_rfq(session, ctx, rfq_id, data.reason)
    return RfqOut.model_validate(rfq)
