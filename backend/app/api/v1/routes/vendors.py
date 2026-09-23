from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_session, require_roles
from app.core.context import RequestContext
from app.core.enums import Role
from app.schemas.common import Page
from app.schemas.vendors import (
    DuplicateCandidateOut,
    DuplicateCandidatePreview,
    DuplicateCheckResult,
    DuplicateResolveRequest,
    VendorCreate,
    VendorOut,
)
from app.services import vendors as vendors_service

router = APIRouter(prefix="/vendors", tags=["vendors"])

_WRITE_ROLES = (
    Role.LEAD_ESTIMATOR.value,
    Role.PROCUREMENT_HEAD.value,
    Role.BD_DIRECTOR.value,
    Role.MANAGING_DIRECTOR.value,
)


@router.get("", response_model=Page)
async def list_vendors_endpoint(
    status: str | None = None,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    ctx: RequestContext = CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> Page:
    rows, total = await vendors_service.list_vendors(session, ctx.tenant_id, status=status, limit=limit, offset=offset)
    return Page(items=[VendorOut.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("", response_model=VendorOut, status_code=201)
async def create_vendor_endpoint(
    data: VendorCreate,
    force: bool = False,
    ctx: RequestContext = Depends(require_roles(*_WRITE_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> VendorOut:
    vendor = await vendors_service.create_vendor(session, ctx, data, force=force)
    return VendorOut.model_validate(vendor)


@router.post(":check-duplicates", response_model=DuplicateCheckResult)
async def check_duplicates_endpoint(
    data: VendorCreate,
    ctx: RequestContext = CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> DuplicateCheckResult:
    candidate_vendor = vendors_service.build_vendor(ctx.tenant_id, data)
    scored = await vendors_service.check_duplicates(session, ctx.tenant_id, candidate_vendor)
    highest = max((s for _, s, _ in scored), default=0.0)
    return DuplicateCheckResult(
        candidates=[
            DuplicateCandidatePreview(
                existing_vendor_id=c.id, existing_vendor_name=c.legal_name, score=s, signals=sig
            )
            for c, s, sig in scored
        ],
        highest_score=highest,
    )


@router.get("/duplicates/list", response_model=list[DuplicateCandidateOut])
async def list_duplicates_endpoint(
    status: str | None = "open",
    ctx: RequestContext = CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> list[DuplicateCandidateOut]:
    rows = await vendors_service.list_duplicate_candidates(session, ctx.tenant_id, status=status)
    return [DuplicateCandidateOut.model_validate(r) for r in rows]


@router.post("/duplicates/{candidate_id}/resolve", response_model=DuplicateCandidateOut)
async def resolve_duplicate_endpoint(
    candidate_id: UUID,
    data: DuplicateResolveRequest,
    ctx: RequestContext = Depends(require_roles(*_WRITE_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> DuplicateCandidateOut:
    row = await vendors_service.resolve_duplicate(session, ctx, candidate_id, data.resolution, data.resolution_note)
    return DuplicateCandidateOut.model_validate(row)


@router.get("/{vendor_id}", response_model=VendorOut)
async def get_vendor_endpoint(
    vendor_id: UUID,
    ctx: RequestContext = CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> VendorOut:
    vendor = await vendors_service.get_vendor(session, ctx.tenant_id, vendor_id)
    return VendorOut.model_validate(vendor)


@router.post("/{vendor_id}/duplicate-scan", response_model=list[DuplicateCandidateOut])
async def scan_duplicates_endpoint(
    vendor_id: UUID,
    ctx: RequestContext = Depends(require_roles(*_WRITE_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> list[DuplicateCandidateOut]:
    rows = await vendors_service.scan_duplicates(session, ctx, vendor_id)
    return [DuplicateCandidateOut.model_validate(r) for r in rows]
