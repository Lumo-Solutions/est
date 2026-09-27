"""Module C1: procurement packages, vendor matching, and RFQ drafting.

RFQ *dispatch* (actually rendering content and sending an email) is
deliberately NOT in this module -- it runs inside a Celery task
(app/workers/tasks/procurement.py::dispatch_rfq) so a slow/unreachable SMTP
relay never blocks an API request. This module only validates the request,
transitions the Rfq row to `queued`, and enqueues that task -- the same
split app/services/takeoff.py::trigger_ingest uses for index_sheets.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import RequestContext
from app.core.enums import (
    AuditAction,
    PrequalificationStatus,
    ProcurementPackageStatus,
    RfqStatus,
    VendorStatus,
)
from app.core.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    StepUpRequiredError,
    ValidationAppError,
)
from app.core.config import get_settings
from app.models.boq import BoqLineItem
from app.models.procurement import ProcurementPackage, ProcurementPackageItem, Rfq
from app.models.tenancy import Project
from app.models.vendors import Vendor, VendorContact, VendorTrade
from app.schemas.procurement import MatchedVendorOut, ProcurementPackageCreate, RfqCreateRequest
from app.security.deps import has_recent_step_up
from app.services import audit
from app.services import prequal as prequal_service
from app.services import vendors as vendors_service
from app.services.projects import assert_can_see_project

_ELIGIBLE_PREQUAL_STATUSES = {PrequalificationStatus.APPROVED.value, PrequalificationStatus.CONDITIONAL.value}
_DISPATCH_ROLES = ("procurement_head", "bd_director", "managing_director")


# --------------------------------------------------------------------------
# packages
# --------------------------------------------------------------------------


async def create_package(
    session: AsyncSession, ctx: RequestContext, project_id: UUID, data: ProcurementPackageCreate
) -> ProcurementPackage:
    await assert_can_see_project(session, ctx, project_id)
    package = ProcurementPackage(
        tenant_id=ctx.tenant_id,
        project_id=project_id,
        trade_node_id=data.trade_node_id,
        name=data.name,
        status=ProcurementPackageStatus.DRAFT.value,
        due_at=data.due_at,
        notes=data.notes,
    )
    session.add(package)
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.CREATE, entity_type="procurement_package", entity_id=package.id,
        project_id=project_id, payload={"name": data.name, "trade_node_id": str(data.trade_node_id) if data.trade_node_id else None},
    )
    return package


async def get_package(session: AsyncSession, package_id: UUID) -> ProcurementPackage:
    result = await session.execute(select(ProcurementPackage).where(ProcurementPackage.id == package_id))
    package = result.scalar_one_or_none()
    if package is None:
        raise NotFoundError(f"Procurement package {package_id} not found")
    return package


async def list_packages(session: AsyncSession, project_id: UUID) -> list[ProcurementPackage]:
    result = await session.execute(
        select(ProcurementPackage)
        .where(ProcurementPackage.project_id == project_id)
        .order_by(ProcurementPackage.created_at.desc())
    )
    return list(result.scalars().all())


async def add_items(
    session: AsyncSession, ctx: RequestContext, package_id: UUID, boq_line_item_ids: list[UUID]
) -> list[ProcurementPackageItem]:
    package = await get_package(session, package_id)
    result = await session.execute(
        select(BoqLineItem).where(BoqLineItem.id.in_(boq_line_item_ids), BoqLineItem.project_id == package.project_id)
    )
    found = {item.id for item in result.scalars().all()}
    missing = set(boq_line_item_ids) - found
    if missing:
        raise ValidationAppError(f"BOQ line items not found in project {package.project_id}: {sorted(missing)}")

    created: list[ProcurementPackageItem] = []
    for boq_line_item_id in boq_line_item_ids:
        row = ProcurementPackageItem(
            tenant_id=ctx.tenant_id, package_id=package.id, boq_line_item_id=boq_line_item_id, project_id=package.project_id,
        )
        session.add(row)
        created.append(row)
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.UPDATE, entity_type="procurement_package", entity_id=package.id,
        project_id=package.project_id, payload={"added_boq_line_item_ids": [str(i) for i in boq_line_item_ids]},
    )
    return created


async def list_package_items(session: AsyncSession, package_id: UUID) -> list[ProcurementPackageItem]:
    result = await session.execute(
        select(ProcurementPackageItem).where(ProcurementPackageItem.package_id == package_id)
    )
    return list(result.scalars().all())


async def list_package_boq_items(session: AsyncSession, package_id: UUID) -> list[BoqLineItem]:
    result = await session.execute(
        select(BoqLineItem)
        .join(ProcurementPackageItem, ProcurementPackageItem.boq_line_item_id == BoqLineItem.id)
        .where(ProcurementPackageItem.package_id == package_id)
        .order_by(BoqLineItem.sort_order)
    )
    return list(result.scalars().all())


# --------------------------------------------------------------------------
# vendor matching (trade + active prequalification; SRS defaults #1, #2, #6)
# --------------------------------------------------------------------------


def _resolve_geography_eligibility(project_emirate: str | None, served_regions: set[str]) -> tuple[bool, str | None]:
    """Pure decision (Module C Phase 6), split out from
    _vendor_geography_eligible below for unit testing with no DB at all.
    Geography is only ever evaluated when there's something real to
    compare: a project with no emirate set, or a vendor with zero declared
    service_regions, means "nothing to filter on" and this returns
    eligible -- never "assume available everywhere" (a silent guess) and
    never "assume unavailable" (which would wrongly exclude every vendor
    until every one of them is configured). Only an actual project-emirate
    vs vendor-regions mismatch excludes."""
    if project_emirate is None or not served_regions:
        return True, None
    if project_emirate in served_regions:
        return True, None
    return False, f"vendor does not serve {project_emirate!r} (serves: {sorted(served_regions)})"


async def _vendor_geography_eligible(session: AsyncSession, vendor: Vendor, project_id: UUID) -> tuple[bool, str | None]:
    project = (await session.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    project_emirate = project.emirate if project is not None else None
    regions = await vendors_service.list_service_regions(session, vendor.id)
    return _resolve_geography_eligibility(project_emirate, {r.emirate for r in regions})


async def _vendor_eligibility(
    session: AsyncSession, vendor: Vendor, trade_node_id: UUID, project_id: UUID
) -> tuple[bool, str | None]:
    """A vendor is eligible when it is ACTIVE (SRS default #2), has an
    APPROVED/CONDITIONAL prequalification effective today (scoped either to
    this exact trade or to "all trades" -- scope_trade_node_id IS NULL, a
    blanket prequalification), AND (Module C Phase 6) is geography-eligible
    for the project -- see _vendor_geography_eligible. Anything else --
    not active, no prequalification row, an expired one, one in
    pending/suspended/rejected/blacklisted, or a project/vendor-region
    mismatch -- excludes the vendor by default (SRS default #6: "excludes
    vendors whose prequalification for the trade is expired or missing",
    extended the same way to geography). Checked here (not just filtered
    out of match_vendors' query) so create_rfqs enforces the exact same
    rule for a vendor_id supplied directly, not only one picked from that
    listing. Returns the first failing reason -- one override_reason still
    covers whichever check(s) failed (create_rfqs's existing single-reason
    design, unchanged)."""
    if vendor.status != VendorStatus.ACTIVE.value:
        return False, f"vendor status is {vendor.status!r}, not active"

    today = datetime.now(timezone.utc).date()
    prequal_ok = False
    prequal_reason: str | None = None
    trade_scoped = await prequal_service.get_prequalification_as_of(session, vendor.id, today, trade_node_id)
    if trade_scoped is not None and trade_scoped.status in _ELIGIBLE_PREQUAL_STATUSES:
        prequal_ok = True
    else:
        blanket = await prequal_service.get_prequalification_as_of(session, vendor.id, today, None)
        if blanket is not None and blanket.status in _ELIGIBLE_PREQUAL_STATUSES:
            prequal_ok = True
        elif trade_scoped is not None or blanket is not None:
            prequal_reason = "prequalification for this trade is not currently approved"
        else:
            prequal_reason = "no effective prequalification for this trade"
    if not prequal_ok:
        return False, prequal_reason

    return await _vendor_geography_eligible(session, vendor, project_id)


async def match_vendors(session: AsyncSession, package_id: UUID) -> list[MatchedVendorOut]:
    package = await get_package(session, package_id)
    if package.trade_node_id is None:
        raise ValidationAppError("Vendor matching requires the package to have a trade_node_id set")

    result = await session.execute(
        select(Vendor)
        .join(VendorTrade, VendorTrade.vendor_id == Vendor.id)
        .where(VendorTrade.trade_node_id == package.trade_node_id, Vendor.status == VendorStatus.ACTIVE.value)
        .order_by(Vendor.legal_name)
    )
    vendors = list(result.scalars().all())

    matches: list[MatchedVendorOut] = []
    for vendor in vendors:
        eligible, reason = await _vendor_eligibility(session, vendor, package.trade_node_id, package.project_id)
        regions = await vendors_service.list_service_regions(session, vendor.id)
        matches.append(
            MatchedVendorOut(
                vendor_id=vendor.id, legal_name=vendor.legal_name, primary_email=vendor.primary_email,
                emirate=vendor.emirate, country=vendor.country, eligible=eligible, ineligible_reason=reason,
                service_regions=[r.emirate for r in regions],
            )
        )
    return matches


# --------------------------------------------------------------------------
# RFQ drafting
# --------------------------------------------------------------------------


async def _primary_contact(session: AsyncSession, vendor_id: UUID) -> VendorContact | None:
    result = await session.execute(
        select(VendorContact)
        .where(VendorContact.vendor_id == vendor_id, VendorContact.is_primary.is_(True))
        .order_by(VendorContact.created_at)
    )
    return result.scalars().first()


async def create_rfqs(
    session: AsyncSession, ctx: RequestContext, package_id: UUID, data: RfqCreateRequest
) -> list[Rfq]:
    package = await get_package(session, package_id)
    items = await list_package_items(session, package_id)
    if not items:
        raise ConflictError(f"Procurement package {package_id} has no BOQ line items to quote")

    created: list[Rfq] = []
    for vendor_id in data.vendor_ids:
        vendor = await vendors_service.get_vendor(session, ctx.tenant_id, vendor_id)
        is_override = False
        if package.trade_node_id is not None:
            eligible, reason = await _vendor_eligibility(session, vendor, package.trade_node_id, package.project_id)
            if not eligible:
                if not data.override_reason:
                    raise ValidationAppError(
                        f"Vendor {vendor_id} is not eligible ({reason}); resubmit with override_reason to include it anyway"
                    )
                if not ctx.has_role(*_DISPATCH_ROLES):
                    raise ForbiddenError("Overriding vendor eligibility requires procurement_head or above")
                is_override = True

        contact = await _primary_contact(session, vendor.id)
        if not (contact and contact.email) and not vendor.primary_email:
            raise ValidationAppError(f"Vendor {vendor_id} has no contactable email (no primary contact/email on file)")

        rfq = Rfq(
            tenant_id=ctx.tenant_id, package_id=package.id, project_id=package.project_id, vendor_id=vendor.id,
            vendor_contact_id=contact.id if contact else None, status=RfqStatus.DRAFT.value,
            due_at=data.due_at or package.due_at, is_override=is_override,
            override_reason=data.override_reason if is_override else None,
            reply_token=secrets.token_urlsafe(32),
        )
        session.add(rfq)
        await session.flush()
        await session.refresh(rfq, attribute_names=["rfq_ref"])  # set by rfqs_assign_ref_trg
        await audit.record(
            session, ctx, action=AuditAction.CREATE, entity_type="rfq", entity_id=rfq.id, project_id=package.project_id,
            payload={
                "package_id": str(package.id), "vendor_id": str(vendor.id), "rfq_ref": rfq.rfq_ref,
                "is_override": is_override, "override_reason": data.override_reason if is_override else None,
            },
        )
        created.append(rfq)
    return created


async def get_rfq(session: AsyncSession, rfq_id: UUID) -> Rfq:
    result = await session.execute(select(Rfq).where(Rfq.id == rfq_id))
    rfq = result.scalar_one_or_none()
    if rfq is None:
        raise NotFoundError(f"RFQ {rfq_id} not found")
    return rfq


async def list_rfqs(session: AsyncSession, package_id: UUID) -> list[Rfq]:
    result = await session.execute(
        select(Rfq).where(Rfq.package_id == package_id).order_by(Rfq.created_at)
    )
    return list(result.scalars().all())


# --------------------------------------------------------------------------
# dispatch / resend authorization + enqueue
# --------------------------------------------------------------------------


def _require_dispatch_authority(ctx: RequestContext) -> None:
    if not ctx.has_role(*_DISPATCH_ROLES):
        raise ForbiddenError(f"Requires one of roles: {', '.join(_DISPATCH_ROLES)}")
    # has_recent_step_up (app/security/deps.py), shared with
    # approvals.py::decide() -- same acr-AND-auth_time-recency check, not a
    # separate copy that could drift. See fix/keycloak-step-up.
    if not has_recent_step_up(ctx, get_settings()):
        raise StepUpRequiredError("Dispatching an RFQ requires a recent MFA step-up authentication")


async def dispatch_rfq(session: AsyncSession, ctx: RequestContext, rfq_id: UUID) -> Rfq:
    """First send (draft) or an immediate retry after a failed send. An
    already-sent or already-queued RFQ must go through resend_rfq instead --
    see that function's docstring for why this isn't just an ORM state
    check."""
    _require_dispatch_authority(ctx)
    rfq = await get_rfq(session, rfq_id)
    if rfq.status not in (RfqStatus.DRAFT.value, RfqStatus.FAILED.value):
        raise ConflictError(f"RFQ {rfq_id} is {rfq.status}; use the resend endpoint instead")
    return await _queue(session, ctx, rfq, resend=False, reason=None)


async def resend_rfq(session: AsyncSession, ctx: RequestContext, rfq_id: UUID, reason: str) -> Rfq:
    """Explicit re-dispatch of an RFQ that may already have been delivered
    (SRS default: "an RFQ already sent isn't re-sent unless an explicit
    resend endpoint is called") -- also the escape hatch for an RFQ stuck
    in `queued` (e.g. its Celery task was lost). Always audited with the
    caller's reason, on top of the same role+step-up gate as a first
    dispatch."""
    _require_dispatch_authority(ctx)
    rfq = await get_rfq(session, rfq_id)
    if rfq.status == RfqStatus.DRAFT.value:
        raise ConflictError(f"RFQ {rfq_id} was never sent; use the dispatch endpoint instead")
    return await _queue(session, ctx, rfq, resend=True, reason=reason)


async def _queue(session: AsyncSession, ctx: RequestContext, rfq: Rfq, *, resend: bool, reason: str | None) -> Rfq:
    from app.workers.tasks.procurement import dispatch_rfq_task

    rfq.status = RfqStatus.QUEUED.value
    rfq.queued_at = datetime.now(timezone.utc)
    rfq.dispatch_error = None
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.UPDATE, entity_type="rfq", entity_id=rfq.id, project_id=rfq.project_id,
        payload={"status": "queued", "resend": resend, "reason": reason},
    )
    task = dispatch_rfq_task.delay(
        str(rfq.id), str(ctx.tenant_id), str(ctx.user_id) if ctx.user_id else None, list(ctx.roles)
    )
    rfq.celery_task_id = task.id
    await session.flush()
    return rfq
