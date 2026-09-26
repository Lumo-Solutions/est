"""Module C2: reviewing quarantined/flagged inbound mail, resolving
currency/VAT, and the accept/reject human-in-the-loop workflow for extracted
quotation line items. Bid leveling reads only status=accepted line items.

Extraction itself (safety checks, deterministic parsing, LLM extraction) runs
entirely in Celery tasks (app/workers/tasks/quotation_ingestion.py) -- this
module is the interactive, RLS-scoped read/review/accept surface a FastAPI
route calls directly, the same split app/services/procurement.py uses for
RFQ dispatch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import RequestContext
from app.core.enums import (
    AuditAction,
    InboundEmailMatchStatus,
    QuotationLineItemStatus,
    QuotationStatus,
    RfqStatus,
    Role,
)
from app.core.errors import ConflictError, ForbiddenError, NotFoundError, ValidationAppError
from app.db.rls import set_rls_context
from app.models.procurement import Rfq
from app.models.quotation_ingestion import (
    InboundEmail,
    Quotation,
    QuotationAttachment,
    QuotationExclusionFlag,
    QuotationLineItem,
)
from app.services import audit

_REVIEW_ROLES = (Role.PROCUREMENT_HEAD.value, Role.BD_DIRECTOR.value, Role.MANAGING_DIRECTOR.value)
_PLATFORM_ADMIN_ROLE = (Role.PLATFORM_ADMIN.value,)


def _require_review_authority(ctx: RequestContext) -> None:
    if not ctx.has_role(*_REVIEW_ROLES):
        raise ForbiddenError(f"Requires one of roles: {', '.join(_REVIEW_ROLES)}")


def _require_platform_admin(ctx: RequestContext) -> None:
    if not ctx.has_role(*_PLATFORM_ADMIN_ROLE):
        raise ForbiddenError("Requires the platform_admin role")


# --------------------------------------------------------------------------
# inbound email review queue
# --------------------------------------------------------------------------


async def list_inbound_review_queue(session: AsyncSession) -> list[InboundEmail]:
    """RLS alone decides what this returns: a platform_admin sees only
    tenant_id IS NULL rows, everyone else sees only their own tenant's --
    see migration 0016's inbound_emails_read policy."""
    result = await session.execute(
        select(InboundEmail).where(InboundEmail.review_status == "open").order_by(InboundEmail.received_at)
    )
    return list(result.scalars().all())


async def get_inbound_email(session: AsyncSession, inbound_email_id: UUID) -> InboundEmail:
    result = await session.execute(select(InboundEmail).where(InboundEmail.id == inbound_email_id))
    row = result.scalar_one_or_none()
    if row is None:
        raise NotFoundError(f"Inbound email {inbound_email_id} not found")
    return row


async def resolve_inbound_email_tenant(
    session: AsyncSession, ctx: RequestContext, inbound_email_id: UUID, tenant_id: UUID, note: str
) -> InboundEmail:
    """platform_admin-only: attaches a genuinely tenant-unresolved email
    (match_status=quarantined_unknown_tenant) to a tenant the operator has
    identified some other way. Does NOT itself match a reply token or
    trigger extraction -- that tenant's own procurement_head+ still reviews
    it from their own queue afterwards (attach_inbound_email_to_rfq).

    Authorization (_require_platform_admin) is checked first, against the
    caller's own ctx, before anything else touches the database. Only then
    does the UPDATE (and the target tenant's own audit insert, see below)
    run under a tenant-scoped elevated context instead of ctx: Postgres's
    RLS for UPDATE requires the *post-update* row to still pass the table's
    SELECT policy, not just the UPDATE policy's own WITH CHECK (undocumented
    clearly, but reproducibly true -- confirmed empirically while writing
    tests/integration/test_quotation_ingestion_review.py). Once tenant_id
    moves off NULL, a platform_admin's own SELECT-policy branches both go
    false (it's neither "tenant_id IS NULL" nor "tenant_id =
    app_tenant_id()" for their own unrelated tenant), so the write itself
    would violate RLS even though *authorization* was already correctly
    enforced above. The elevated context is scoped to that block via
    try/finally -- ctx is restored even if a statement inside raises -- and
    nothing besides those two writes runs while it's active.

    Two audit events are recorded, in two different tenants' own trails,
    both with ctx.user_id/sub/roles as the actor -- never "system":
    the actor's own tenant (after ctx is restored, below) and the *target*
    tenant's (while still elevated, above -- a reviewer in that tenant
    should be able to see how this email came to belong to them without
    needing platform_admin visibility themselves)."""
    _require_platform_admin(ctx)
    email = await get_inbound_email(session, inbound_email_id)
    if email.tenant_id is not None:
        raise ConflictError(f"Inbound email {inbound_email_id} already has a resolved tenant")

    now = datetime.now(timezone.utc)
    new_match_status = InboundEmailMatchStatus.QUARANTINED_NO_TOKEN.value
    # Carries ctx's real identity (not an anonymous "system" actor) so the
    # target-tenant audit insert below attributes correctly, while is_system
    # bypasses that tenant's RLS for both writes.
    target_tenant_ctx = RequestContext(tenant_id=tenant_id, user_id=ctx.user_id, sub=ctx.sub, roles=ctx.roles, is_system=True)
    await set_rls_context(session, target_tenant_ctx)
    try:
        await session.execute(
            sa_update(InboundEmail)
            .where(InboundEmail.id == email.id)
            .values(tenant_id=tenant_id, match_status=new_match_status, review_note=note, reviewed_by=ctx.user_id, reviewed_at=now)
        )
        await audit.record(
            session, target_tenant_ctx, action=AuditAction.UPDATE, entity_type="inbound_email", entity_id=email.id,
            payload={"resolved_by_platform_admin": str(ctx.user_id), "note": note, "source": "platform_admin_resolution"},
        )
    finally:
        await set_rls_context(session, ctx)

    session.expunge(email)
    email.tenant_id = tenant_id
    email.match_status = new_match_status
    email.review_note = note
    email.reviewed_by = ctx.user_id
    email.reviewed_at = now

    await audit.record(
        session, ctx, action=AuditAction.UPDATE, entity_type="inbound_email", entity_id=email.id,
        payload={"resolved_tenant_id": str(tenant_id), "note": note},
    )
    return email


async def dismiss_inbound_email(session: AsyncSession, ctx: RequestContext, inbound_email_id: UUID, note: str) -> InboundEmail:
    """Marks quarantined/flagged mail as reviewed-and-ignored (spam,
    misdirected, not procurement-relevant) -- available to whichever role
    can already see the row (RLS: platform_admin for an unresolved tenant,
    procurement_head+ for a resolved one)."""
    email = await get_inbound_email(session, inbound_email_id)
    if email.tenant_id is None:
        _require_platform_admin(ctx)
    else:
        _require_review_authority(ctx)

    email.review_status = "dismissed"
    email.review_note = note
    email.reviewed_by = ctx.user_id
    email.reviewed_at = datetime.now(timezone.utc)
    await session.flush()
    return email


async def attach_inbound_email_to_rfq(
    session: AsyncSession, ctx: RequestContext, inbound_email_id: UUID, rfq_id: UUID, reason: str
) -> InboundEmail:
    """Explicit human override for a flagged/quarantined-but-tenant-known
    email (domain mismatch, auth failure, stale/unknown token) -- requires a
    reason, is audited, and only then triggers attachment processing.
    Mirrors the is_override/override_reason pattern
    app/services/procurement.py::create_rfqs uses for vendor-matching
    overrides. Never usable for a still tenant-unresolved email -- resolve
    the tenant first (resolve_inbound_email_tenant)."""
    _require_review_authority(ctx)
    email = await get_inbound_email(session, inbound_email_id)
    if email.tenant_id is None:
        raise ConflictError("Cannot attach an email with no resolved tenant -- resolve its tenant first")

    rfq = (await session.execute(select(Rfq).where(Rfq.id == rfq_id, Rfq.tenant_id == email.tenant_id))).scalar_one_or_none()
    if rfq is None:
        raise NotFoundError(f"RFQ {rfq_id} not found for this tenant")

    email.rfq_id = rfq.id
    email.match_status = InboundEmailMatchStatus.MATCHED.value
    email.needs_review = False
    email.review_status = "attached"
    email.review_note = reason
    email.reviewed_by = ctx.user_id
    email.reviewed_at = datetime.now(timezone.utc)
    if rfq.status == RfqStatus.SENT.value:
        rfq.status = RfqStatus.RESPONDED.value
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.UPDATE, entity_type="inbound_email", entity_id=email.id, project_id=rfq.project_id,
        payload={"attached_to_rfq_id": str(rfq_id), "reason": reason},
    )

    from app.workers.tasks.quotation_ingestion import process_inbound_email_task

    process_inbound_email_task.delay(str(email.id), str(email.tenant_id))

    return email


# --------------------------------------------------------------------------
# quotations / line items
# --------------------------------------------------------------------------


async def list_quotations_for_rfq(session: AsyncSession, rfq_id: UUID) -> list[Quotation]:
    result = await session.execute(
        select(Quotation).where(Quotation.rfq_id == rfq_id).order_by(Quotation.vendor_id, Quotation.version_no)
    )
    return list(result.scalars().all())


async def get_quotation(session: AsyncSession, quotation_id: UUID) -> Quotation:
    result = await session.execute(select(Quotation).where(Quotation.id == quotation_id))
    row = result.scalar_one_or_none()
    if row is None:
        raise NotFoundError(f"Quotation {quotation_id} not found")
    return row


async def list_quotation_line_items(session: AsyncSession, quotation_id: UUID) -> list[QuotationLineItem]:
    result = await session.execute(
        select(QuotationLineItem).where(QuotationLineItem.quotation_id == quotation_id).order_by(QuotationLineItem.created_at)
    )
    return list(result.scalars().all())


async def list_quotation_attachments(session: AsyncSession, quotation_id: UUID) -> list[QuotationAttachment]:
    """Every attachment from the inbound email this quotation came from --
    the primary extraction source (is_primary=true) plus any supporting
    documents (SRS: attachments on one email are one submission, never
    separately-extracted competing quotes)."""
    result = await session.execute(
        select(QuotationAttachment)
        .where(QuotationAttachment.quotation_id == quotation_id)
        .order_by(QuotationAttachment.is_primary.desc(), QuotationAttachment.created_at)
    )
    return list(result.scalars().all())


async def resolve_currency_and_vat(
    session: AsyncSession, ctx: RequestContext, quotation_id: UUID, currency: str, vat_inclusive: bool
) -> Quotation:
    """SRS change #4: a reviewer resolving what the extractor could not
    determine. Required before any line item on this quotation can be
    accepted (see accept_line_item)."""
    _require_review_authority(ctx)
    quotation = await get_quotation(session, quotation_id)
    quotation.currency = currency.upper()
    quotation.vat_inclusive = vat_inclusive
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.UPDATE, entity_type="quotation", entity_id=quotation.id, project_id=quotation.project_id,
        payload={"currency": quotation.currency, "vat_inclusive": vat_inclusive, "resolved_by_reviewer": True},
    )
    return quotation


async def reject_quotation(session: AsyncSession, ctx: RequestContext, quotation_id: UUID, reason: str) -> Quotation:
    _require_review_authority(ctx)
    quotation = await get_quotation(session, quotation_id)
    quotation.status = QuotationStatus.REJECTED.value
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.REJECT, entity_type="quotation", entity_id=quotation.id, project_id=quotation.project_id,
        payload={"reason": reason},
    )
    return quotation


async def promote_quotation_version(session: AsyncSession, ctx: RequestContext, quotation_id: UUID) -> Quotation:
    """The only way a version becomes is_current when
    app/workers/tasks/quotation_ingestion.py::_create_quotation_version
    itself declined to (an empty/failed extraction, or an existing current
    version that already has an accepted line item) -- SRS: a new version
    never silently replaces an accepted one; a reviewer chooses explicitly,
    and it's audited."""
    _require_review_authority(ctx)
    quotation = await get_quotation(session, quotation_id)
    if quotation.is_current:
        raise ConflictError(f"Quotation {quotation_id} is already the current version")

    previous_current = (
        await session.execute(
            select(Quotation).where(Quotation.rfq_id == quotation.rfq_id, Quotation.vendor_id == quotation.vendor_id, Quotation.is_current.is_(True))
        )
    ).scalar_one_or_none()
    if previous_current is not None:
        previous_current.is_current = False
        # Flushed separately from setting the new one True below: the
        # partial unique index (uq_quotations_current_per_rfq_vendor) checks
        # each row immediately, and SQLAlchemy may batch same-table UPDATEs
        # from a single flush() into one executemany() whose per-row order
        # isn't guaranteed -- letting both rows briefly read is_current=true
        # in the same statement violates the index. Same reason
        # _create_quotation_version flushes the old row's flip before adding
        # the new one.
        await session.flush()
    quotation.is_current = True
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.UPDATE, entity_type="quotation", entity_id=quotation.id, project_id=quotation.project_id,
        payload={"promoted_to_current": True, "previous_current_quotation_id": str(previous_current.id) if previous_current else None},
    )
    return quotation


async def _get_line_item(session: AsyncSession, line_item_id: UUID) -> QuotationLineItem:
    result = await session.execute(select(QuotationLineItem).where(QuotationLineItem.id == line_item_id))
    row = result.scalar_one_or_none()
    if row is None:
        raise NotFoundError(f"Quotation line item {line_item_id} not found")
    return row


async def get_line_item(session: AsyncSession, line_item_id: UUID) -> QuotationLineItem:
    """Public alias of _get_line_item -- Module B/C Phase 5's suggestion
    endpoint needs a read-only fetch with no review-authority check
    (unlike accept_line_item/reject_line_item, both request-authorized
    actions), so it calls this rather than a private, module-internal name."""
    return await _get_line_item(session, line_item_id)


async def accept_line_item(session: AsyncSession, ctx: RequestContext, line_item_id: UUID) -> QuotationLineItem:
    _require_review_authority(ctx)
    line_item = await _get_line_item(session, line_item_id)
    quotation = await get_quotation(session, line_item.quotation_id)
    if quotation.currency is None or quotation.vat_inclusive is None:
        raise ValidationAppError(
            "This quotation's currency/VAT-inclusive status must be resolved before any line item can be accepted "
            "(see resolve_currency_and_vat)."
        )
    line_item.status = QuotationLineItemStatus.ACCEPTED.value
    line_item.accepted_by = ctx.user_id
    line_item.accepted_at = datetime.now(timezone.utc)
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.APPROVE, entity_type="quotation_line_item", entity_id=line_item.id, project_id=line_item.project_id,
        payload={"quotation_id": str(quotation.id), "boq_line_item_id": str(line_item.boq_line_item_id) if line_item.boq_line_item_id else None},
    )
    return line_item


async def reject_line_item(session: AsyncSession, ctx: RequestContext, line_item_id: UUID) -> QuotationLineItem:
    _require_review_authority(ctx)
    line_item = await _get_line_item(session, line_item_id)
    line_item.status = QuotationLineItemStatus.REJECTED.value
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.REJECT, entity_type="quotation_line_item", entity_id=line_item.id, project_id=line_item.project_id,
        payload={"quotation_id": str(line_item.quotation_id)},
    )
    return line_item


async def list_exclusion_flags(session: AsyncSession, quotation_id: UUID) -> list[QuotationExclusionFlag]:
    result = await session.execute(
        select(QuotationExclusionFlag)
        .where(QuotationExclusionFlag.quotation_id == quotation_id)
        .order_by(QuotationExclusionFlag.created_at)
    )
    return list(result.scalars().all())


async def acknowledge_exclusion_flag(session: AsyncSession, ctx: RequestContext, flag_id: UUID) -> QuotationExclusionFlag:
    _require_review_authority(ctx)
    result = await session.execute(select(QuotationExclusionFlag).where(QuotationExclusionFlag.id == flag_id))
    flag = result.scalar_one_or_none()
    if flag is None:
        raise NotFoundError(f"Exclusion flag {flag_id} not found")
    flag.status = "acknowledged"
    flag.reviewed_by = ctx.user_id
    flag.reviewed_at = datetime.now(timezone.utc)
    await session.flush()
    return flag


# --------------------------------------------------------------------------
# bid leveling (SRS requirement #8): accepted line items only, never mixing
# currency/VAT bases -- shown separately, no automatic FX conversion.
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BidLevelingCell:
    quotation_id: UUID
    vendor_id: UUID
    unit_price: Decimal
    currency: str
    vat_inclusive: bool
    confidence: float
    arithmetic_mismatch: bool
    quantity_mismatch: bool
    # Module C Phase 6: additive -- normalized_unit_price is unit_price *
    # the quotation's own recorded fx_rate_to_base, shown ALONGSIDE
    # unit_price/currency above, never replacing them (no auto-conversion
    # without a recorded rate -- see set_quotation_fx_rate). None when no
    # rate has been recorded.
    normalized_unit_price: Decimal | None
    uom_mismatch: bool


@dataclass(frozen=True, slots=True)
class BidLevelingRow:
    boq_line_item_id: UUID
    cells: list[BidLevelingCell] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class QuotationTotal:
    quotation_id: UUID
    vendor_id: UUID
    stated_total: Decimal | None
    total_mismatch: bool


async def get_bid_leveling_matrix(session: AsyncSession, package_id: UUID) -> list[BidLevelingRow]:
    result = await session.execute(
        select(QuotationLineItem, Quotation)
        .join(Quotation, Quotation.id == QuotationLineItem.quotation_id)
        .where(
            Quotation.package_id == package_id,
            QuotationLineItem.status == QuotationLineItemStatus.ACCEPTED.value,
            QuotationLineItem.boq_line_item_id.is_not(None),
        )
    )
    rows: dict[UUID, BidLevelingRow] = {}
    for line_item, quotation in result.all():
        row = rows.setdefault(line_item.boq_line_item_id, BidLevelingRow(boq_line_item_id=line_item.boq_line_item_id))
        normalized = (
            line_item.unit_price * quotation.fx_rate_to_base if quotation.fx_rate_to_base is not None else None
        )
        row.cells.append(
            BidLevelingCell(
                quotation_id=quotation.id,
                vendor_id=quotation.vendor_id,
                unit_price=line_item.unit_price,
                currency=quotation.currency,
                vat_inclusive=quotation.vat_inclusive,
                confidence=float(line_item.confidence),
                arithmetic_mismatch=line_item.arithmetic_mismatch,
                quantity_mismatch=line_item.quantity_mismatch,
                normalized_unit_price=normalized,
                uom_mismatch=line_item.uom_mismatch,
            )
        )
    return list(rows.values())


async def get_quotation_totals(session: AsyncSession, package_id: UUID) -> list[QuotationTotal]:
    """Module C Phase 6: quotation-level (not per-BOQ-line) subtotal
    verification, surfaced as its own endpoint rather than folded into
    get_bid_leveling_matrix's existing response shape -- additive, not a
    breaking change to an established API response."""
    result = await session.execute(
        select(Quotation).where(Quotation.package_id == package_id, Quotation.status != QuotationStatus.REJECTED.value)
    )
    return [
        QuotationTotal(
            quotation_id=q.id, vendor_id=q.vendor_id, stated_total=q.stated_total, total_mismatch=q.total_mismatch,
        )
        for q in result.scalars().all()
    ]


async def set_quotation_fx_rate(
    session: AsyncSession, ctx: RequestContext, quotation_id: UUID, fx_rate_to_base: Decimal, fx_rate_date: date
) -> Quotation:
    """Bid-leveling-stage FX (Module C Phase 6) -- deliberately separate
    from BidSettlementLineItem.fx_rate/fx_rate_date's own acceptance-stage
    rate (Module D1, migration 0019). Never inferred -- a human records
    it, same rule as that D1 field. Same review-authority role tier as
    resolve_currency_and_vat (this is the same kind of "the extractor
    couldn't determine this, a reviewer resolves it" correction)."""
    _require_review_authority(ctx)
    quotation = await get_quotation(session, quotation_id)
    quotation.fx_rate_to_base = fx_rate_to_base
    quotation.fx_rate_date = fx_rate_date
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.UPDATE, entity_type="quotation", entity_id=quotation.id,
        project_id=quotation.project_id,
        payload={"fx_rate_to_base": str(fx_rate_to_base), "fx_rate_date": fx_rate_date.isoformat()},
    )
    return quotation
