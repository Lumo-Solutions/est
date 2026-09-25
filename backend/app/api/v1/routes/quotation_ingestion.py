from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_session, require_roles
from app.core.context import RequestContext
from app.core.enums import Role
from app.schemas.quotation_ingestion import (
    AttachInboundEmailRequest,
    BidLevelingRowOut,
    DismissInboundEmailRequest,
    InboundEmailOut,
    QuotationAttachmentOut,
    QuotationExclusionFlagOut,
    QuotationLineItemOut,
    QuotationOut,
    RejectQuotationRequest,
    ResolveCurrencyVatRequest,
    ResolveInboundTenantRequest,
)
from app.services import quotation_ingestion as quotation_service

router = APIRouter(tags=["quotation-ingestion"])

_REVIEW_ROLES = (Role.PROCUREMENT_HEAD.value, Role.BD_DIRECTOR.value, Role.MANAGING_DIRECTOR.value)
# Role checks for the quarantine-review endpoints are enforced inside the
# service layer (visibility for a tenant-unresolved row differs from a
# resolved one -- see app/services/quotation_ingestion.py), so these routes
# use CurrentUser rather than a Depends(require_roles(...)) that can't see
# the row yet.


@router.get("/quotation-inbound-review", response_model=list[InboundEmailOut])
async def list_inbound_review_queue_endpoint(
    ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> list[InboundEmailOut]:
    rows = await quotation_service.list_inbound_review_queue(session)
    return [InboundEmailOut.model_validate(r) for r in rows]


@router.post("/quotation-inbound-review/{inbound_email_id}/resolve-tenant", response_model=InboundEmailOut)
async def resolve_inbound_email_tenant_endpoint(
    inbound_email_id: UUID,
    data: ResolveInboundTenantRequest,
    ctx: RequestContext = Depends(require_roles(Role.PLATFORM_ADMIN.value)),
    session: AsyncSession = Depends(get_session),
) -> InboundEmailOut:
    row = await quotation_service.resolve_inbound_email_tenant(session, ctx, inbound_email_id, data.tenant_id, data.note)
    return InboundEmailOut.model_validate(row)


@router.post("/quotation-inbound-review/{inbound_email_id}/dismiss", response_model=InboundEmailOut)
async def dismiss_inbound_email_endpoint(
    inbound_email_id: UUID,
    data: DismissInboundEmailRequest,
    ctx: RequestContext = CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> InboundEmailOut:
    row = await quotation_service.dismiss_inbound_email(session, ctx, inbound_email_id, data.note)
    return InboundEmailOut.model_validate(row)


@router.post("/quotation-inbound-review/{inbound_email_id}/attach", response_model=InboundEmailOut)
async def attach_inbound_email_endpoint(
    inbound_email_id: UUID,
    data: AttachInboundEmailRequest,
    ctx: RequestContext = Depends(require_roles(*_REVIEW_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> InboundEmailOut:
    row = await quotation_service.attach_inbound_email_to_rfq(session, ctx, inbound_email_id, data.rfq_id, data.reason)
    return InboundEmailOut.model_validate(row)


@router.get("/rfqs/{rfq_id}/quotations", response_model=list[QuotationOut])
async def list_quotations_for_rfq_endpoint(
    rfq_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> list[QuotationOut]:
    rows = await quotation_service.list_quotations_for_rfq(session, rfq_id)
    return [QuotationOut.model_validate(r) for r in rows]


@router.get("/quotations/{quotation_id}", response_model=QuotationOut)
async def get_quotation_endpoint(
    quotation_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> QuotationOut:
    row = await quotation_service.get_quotation(session, quotation_id)
    return QuotationOut.model_validate(row)


@router.get("/quotations/{quotation_id}/line-items", response_model=list[QuotationLineItemOut])
async def list_quotation_line_items_endpoint(
    quotation_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> list[QuotationLineItemOut]:
    rows = await quotation_service.list_quotation_line_items(session, quotation_id)
    return [QuotationLineItemOut.model_validate(r) for r in rows]


@router.get("/quotations/{quotation_id}/attachments", response_model=list[QuotationAttachmentOut])
async def list_quotation_attachments_endpoint(
    quotation_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> list[QuotationAttachmentOut]:
    rows = await quotation_service.list_quotation_attachments(session, quotation_id)
    return [QuotationAttachmentOut.model_validate(r) for r in rows]


@router.post("/quotations/{quotation_id}/promote", response_model=QuotationOut)
async def promote_quotation_version_endpoint(
    quotation_id: UUID,
    ctx: RequestContext = Depends(require_roles(*_REVIEW_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> QuotationOut:
    row = await quotation_service.promote_quotation_version(session, ctx, quotation_id)
    return QuotationOut.model_validate(row)


@router.post("/quotations/{quotation_id}/resolve-currency-vat", response_model=QuotationOut)
async def resolve_currency_vat_endpoint(
    quotation_id: UUID,
    data: ResolveCurrencyVatRequest,
    ctx: RequestContext = Depends(require_roles(*_REVIEW_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> QuotationOut:
    row = await quotation_service.resolve_currency_and_vat(session, ctx, quotation_id, data.currency, data.vat_inclusive)
    return QuotationOut.model_validate(row)


@router.post("/quotations/{quotation_id}/reject", response_model=QuotationOut)
async def reject_quotation_endpoint(
    quotation_id: UUID,
    data: RejectQuotationRequest,
    ctx: RequestContext = Depends(require_roles(*_REVIEW_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> QuotationOut:
    row = await quotation_service.reject_quotation(session, ctx, quotation_id, data.reason)
    return QuotationOut.model_validate(row)


@router.post("/quotation-line-items/{line_item_id}/accept", response_model=QuotationLineItemOut)
async def accept_line_item_endpoint(
    line_item_id: UUID,
    ctx: RequestContext = Depends(require_roles(*_REVIEW_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> QuotationLineItemOut:
    row = await quotation_service.accept_line_item(session, ctx, line_item_id)
    return QuotationLineItemOut.model_validate(row)


@router.post("/quotation-line-items/{line_item_id}/reject", response_model=QuotationLineItemOut)
async def reject_line_item_endpoint(
    line_item_id: UUID,
    ctx: RequestContext = Depends(require_roles(*_REVIEW_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> QuotationLineItemOut:
    row = await quotation_service.reject_line_item(session, ctx, line_item_id)
    return QuotationLineItemOut.model_validate(row)


@router.post("/quotation-exclusion-flags/{flag_id}/acknowledge", response_model=QuotationExclusionFlagOut)
async def acknowledge_exclusion_flag_endpoint(
    flag_id: UUID,
    ctx: RequestContext = Depends(require_roles(*_REVIEW_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> QuotationExclusionFlagOut:
    row = await quotation_service.acknowledge_exclusion_flag(session, ctx, flag_id)
    return QuotationExclusionFlagOut.model_validate(row)


@router.get("/procurement-packages/{package_id}/bid-leveling", response_model=list[BidLevelingRowOut])
async def bid_leveling_endpoint(
    package_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> list[BidLevelingRowOut]:
    rows = await quotation_service.get_bid_leveling_matrix(session, package_id)
    return [BidLevelingRowOut.model_validate(r) for r in rows]
