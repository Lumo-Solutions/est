from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_session, require_roles
from app.core.context import RequestContext
from app.core.enums import Role
from app.core.errors import NotFoundError
from app.schemas.prequal import (
    AuthorityOut,
    CertificateTypeOut,
    PrequalificationDecision,
    VendorCertificateCreate,
    VendorCertificateOut,
    VendorPrequalificationOut,
)
from app.services import prequal as prequal_service

router = APIRouter(tags=["prequalification"])

_WRITE_ROLES = (Role.PROCUREMENT_HEAD.value, Role.LEAD_ESTIMATOR.value, Role.MANAGING_DIRECTOR.value)


@router.get("/authorities", response_model=list[AuthorityOut])
async def list_authorities_endpoint(
    ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> list[AuthorityOut]:
    return [AuthorityOut.model_validate(a) for a in await prequal_service.list_authorities(session)]


@router.get("/certificate-types", response_model=list[CertificateTypeOut])
async def list_certificate_types_endpoint(
    ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> list[CertificateTypeOut]:
    return [CertificateTypeOut.model_validate(c) for c in await prequal_service.list_certificate_types(session)]


@router.post("/vendor-certificates", response_model=VendorCertificateOut, status_code=201)
async def add_certificate_endpoint(
    data: VendorCertificateCreate,
    ctx: RequestContext = Depends(require_roles(*_WRITE_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> VendorCertificateOut:
    cert = await prequal_service.add_certificate(session, ctx, data)
    return VendorCertificateOut.model_validate(cert)


@router.post("/vendor-certificates/{certificate_id}/verify", response_model=VendorCertificateOut)
async def verify_certificate_endpoint(
    certificate_id: UUID,
    ctx: RequestContext = Depends(require_roles(*_WRITE_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> VendorCertificateOut:
    cert = await prequal_service.verify_certificate(session, ctx, certificate_id)
    return VendorCertificateOut.model_validate(cert)


@router.get("/vendors/{vendor_id}/prequalification", response_model=VendorPrequalificationOut)
async def get_prequalification_endpoint(
    vendor_id: UUID,
    as_of: date = Query(default_factory=date.today),
    scope_trade_node_id: UUID | None = None,
    ctx: RequestContext = CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> VendorPrequalificationOut:
    row = await prequal_service.get_prequalification_as_of(session, vendor_id, as_of, scope_trade_node_id)
    if row is None:
        raise NotFoundError(f"No prequalification decision covers {vendor_id} as of {as_of}")
    return VendorPrequalificationOut.model_validate(row)


@router.post("/vendors/{vendor_id}/prequalification", response_model=VendorPrequalificationOut, status_code=201)
async def decide_prequalification_endpoint(
    vendor_id: UUID,
    data: PrequalificationDecision,
    ctx: RequestContext = Depends(require_roles(*_WRITE_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> VendorPrequalificationOut:
    row = await prequal_service.decide_prequalification(session, ctx, vendor_id, data)
    return VendorPrequalificationOut.model_validate(row)
