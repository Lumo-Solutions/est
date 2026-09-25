"""Module C2: quarantine/flag review RBAC+RLS (requirement #1, tenancy
default), currency/VAT accept-gating (change #4), quote-version integrity
(change #3), and bid leveling never mixing currency/VAT bases (change #4 /
requirement #8). See app/services/quotation_ingestion.py."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import RequestContext
from app.core.enums import QuotationLineItemStatus
from app.core.errors import ConflictError, ForbiddenError, NotFoundError, ValidationAppError
from app.db.rls import set_rls_context
from app.models.procurement import ProcurementPackage, Rfq
from app.models.quotation_ingestion import InboundEmail, Quotation, QuotationAttachment, QuotationLineItem
from app.models.vendors import Vendor
from app.schemas.boq import BoqLineItemCreate
from app.services import boq as boq_service
from app.services import quotation_ingestion as quotation_service

pytestmark = pytest.mark.asyncio


def _ctx(roles: frozenset[str], *, tenant_id: uuid.UUID, is_system: bool = False, user_id: uuid.UUID | None = None) -> RequestContext:
    user_id = user_id or uuid.uuid4()
    return RequestContext(tenant_id=tenant_id, user_id=user_id, sub=str(user_id), roles=roles, is_system=is_system)


async def _system_ctx(session: AsyncSession, tenant_id: uuid.UUID) -> RequestContext:
    ctx = _ctx(frozenset(), tenant_id=tenant_id, is_system=True)
    await set_rls_context(session, ctx)
    return ctx


async def _seed_tenant_project_rfq(session: AsyncSession) -> tuple[uuid.UUID, Rfq]:
    """Minimal tenant + project + package + vendor + RFQ, all inserted
    directly under a system context (this file tests the review/accept
    service layer, not vendor matching/dispatch -- see test_inbound_match.py
    and test_procurement_dispatch.py for those)."""
    tenant_id = uuid.uuid4()
    await session.execute(
        text("INSERT INTO tenants (id, slug, name) VALUES (:id, :slug, :name)"),
        {"id": str(tenant_id), "slug": f"acme-{uuid.uuid4().hex[:8]}", "name": "Acme"},
    )
    await _system_ctx(session, tenant_id)
    project_id = (
        await session.execute(
            text("INSERT INTO projects (tenant_id, code, name) VALUES (:t, :c, 'A') RETURNING id"),
            {"t": str(tenant_id), "c": f"C2-{uuid.uuid4().hex[:8]}"},
        )
    ).scalar_one()
    vendor = Vendor(tenant_id=tenant_id, legal_name="Vendor X", normalized_name="vendor x", status="active", primary_email="v@vendor.example")
    session.add(vendor)
    await session.flush()
    package = ProcurementPackage(tenant_id=tenant_id, project_id=project_id, name="Package A", status="sent")
    session.add(package)
    await session.flush()
    rfq = Rfq(
        tenant_id=tenant_id, package_id=package.id, project_id=project_id, vendor_id=vendor.id,
        status="sent", reply_token=f"tok-{uuid.uuid4().hex}",
    )
    session.add(rfq)
    await session.flush()
    return tenant_id, rfq


async def _seed_inbound_email(session: AsyncSession, *, tenant_id: uuid.UUID | None, rfq_id: uuid.UUID | None, needs_review: bool) -> InboundEmail:
    email = InboundEmail(
        tenant_id=tenant_id, rfq_id=rfq_id, imap_uid_validity="1", imap_uid=str(uuid.uuid4().int)[:10],
        from_address="vendor@example.com", from_domain="example.com", to_address="rfq+x.y@installtec.local",
        received_at=datetime.now(timezone.utc), match_status="matched" if rfq_id else "quarantined_unknown_tenant",
        needs_review=needs_review, raw_object_key="inbound/1/1.eml", raw_sha256="0" * 64,
    )
    session.add(email)
    await session.flush()
    return email


async def _seed_quotation_with_line_item(
    session: AsyncSession, *, tenant_id: uuid.UUID, rfq: Rfq, currency: str | None, vat_inclusive: bool | None, unit_price: str = "100.0",
) -> tuple[Quotation, QuotationLineItem]:
    quotation = Quotation(
        tenant_id=tenant_id, rfq_id=rfq.id, vendor_id=rfq.vendor_id, package_id=rfq.package_id, project_id=rfq.project_id,
        extraction_method="deterministic_xlsx", currency=currency, vat_inclusive=vat_inclusive,
        submitted_at=datetime.now(timezone.utc), status="proposed",
    )
    session.add(quotation)
    await session.flush()
    line_item = QuotationLineItem(
        tenant_id=tenant_id, quotation_id=quotation.id, project_id=rfq.project_id,
        boq_line_item_id=None, unit_price=Decimal(unit_price), source="deterministic", status="proposed",
    )
    session.add(line_item)
    await session.flush()
    return quotation, line_item


# --------------------------------------------------------------------------
# RLS: quarantine visibility
# --------------------------------------------------------------------------


async def test_platform_admin_sees_only_unresolved_tenant_emails(rls_session):
    tenant_id, rfq = await _seed_tenant_project_rfq(rls_session)
    unresolved = await _seed_inbound_email(rls_session, tenant_id=None, rfq_id=None, needs_review=True)
    flagged = await _seed_inbound_email(rls_session, tenant_id=tenant_id, rfq_id=rfq.id, needs_review=True)

    admin_ctx = _ctx(frozenset({"platform_admin"}), tenant_id=uuid.uuid4())
    await set_rls_context(rls_session, admin_ctx)
    admin_rows = await quotation_service.list_inbound_review_queue(rls_session)
    admin_ids = {r.id for r in admin_rows}
    assert unresolved.id in admin_ids
    assert flagged.id not in admin_ids

    ph_ctx = _ctx(frozenset({"procurement_head"}), tenant_id=tenant_id)
    await set_rls_context(rls_session, ph_ctx)
    tenant_rows = await quotation_service.list_inbound_review_queue(rls_session)
    tenant_ids = {r.id for r in tenant_rows}
    assert flagged.id in tenant_ids
    assert unresolved.id not in tenant_ids

    other_tenant_ctx = _ctx(frozenset({"procurement_head"}), tenant_id=uuid.uuid4())
    await set_rls_context(rls_session, other_tenant_ctx)
    other_rows = await quotation_service.list_inbound_review_queue(rls_session)
    assert flagged.id not in {r.id for r in other_rows}
    assert unresolved.id not in {r.id for r in other_rows}


async def test_resolve_inbound_email_tenant_is_platform_admin_only(rls_session):
    tenant_id, _rfq = await _seed_tenant_project_rfq(rls_session)
    unresolved = await _seed_inbound_email(rls_session, tenant_id=None, rfq_id=None, needs_review=True)

    ph_ctx = _ctx(frozenset({"procurement_head"}), tenant_id=tenant_id)
    await set_rls_context(rls_session, ph_ctx)
    with pytest.raises(ForbiddenError):
        await quotation_service.resolve_inbound_email_tenant(rls_session, ph_ctx, unresolved.id, tenant_id, "looks like acme")

    admin_ctx = _ctx(frozenset({"platform_admin"}), tenant_id=uuid.uuid4())
    await set_rls_context(rls_session, admin_ctx)
    resolved = await quotation_service.resolve_inbound_email_tenant(rls_session, admin_ctx, unresolved.id, tenant_id, "looks like acme")
    assert resolved.tenant_id == tenant_id

    # The audit event records the platform_admin *user* as actor, not
    # "system" -- even though the write itself ran under an elevated,
    # unattributed system RLS context (see the function's docstring).
    admin_readable_ctx = _ctx(frozenset({"managing_director"}), tenant_id=admin_ctx.tenant_id)
    await set_rls_context(rls_session, admin_readable_ctx)
    audit_row = (
        await rls_session.execute(
            text("SELECT actor_sub, actor_roles, action FROM audit_events WHERE entity_type = 'inbound_email' AND entity_id = :e"),
            {"e": str(unresolved.id)},
        )
    ).one()
    assert audit_row[0] == admin_ctx.sub
    assert list(audit_row[1]) == ["platform_admin"]
    assert audit_row[2] == "update"

    # A second audit event is recorded in the *target* tenant's own trail --
    # a reviewer there should be able to see how this email came to belong
    # to them, without needing platform_admin visibility themselves. Same
    # actor (the real platform_admin), not "system".
    target_tenant_readable_ctx = _ctx(frozenset({"managing_director"}), tenant_id=tenant_id)
    await set_rls_context(rls_session, target_tenant_readable_ctx)
    target_audit_row = (
        await rls_session.execute(
            text("SELECT actor_sub, actor_roles, action, payload FROM audit_events WHERE entity_type = 'inbound_email' AND entity_id = :e"),
            {"e": str(unresolved.id)},
        )
    ).one()
    assert target_audit_row[0] == admin_ctx.sub
    assert list(target_audit_row[1]) == ["platform_admin"]
    assert target_audit_row[2] == "update"
    target_payload = target_audit_row[3] if isinstance(target_audit_row[3], dict) else json.loads(target_audit_row[3])
    assert target_payload["resolved_by_platform_admin"] == str(admin_ctx.user_id)

    # Restore admin_ctx's own (unrelated) tenant before the next check --
    # the reads above deliberately left the session's RLS GUC pointed at
    # other contexts.
    await set_rls_context(rls_session, admin_ctx)

    # Once resolved, this admin (whose own tenant_id is unrelated) can no
    # longer even SELECT the row at all -- inbound_emails_read's RLS policy
    # only grants a platform_admin visibility into tenant_id IS NULL rows,
    # by design (the tenancy default this module implements: quarantine
    # stays tenant-scoped once a tenant is known).
    with pytest.raises(NotFoundError):
        await quotation_service.resolve_inbound_email_tenant(rls_session, admin_ctx, unresolved.id, tenant_id, "again")

    # A platform_admin who *also* happens to belong to the now-resolved
    # tenant can still see it (tenant_id = app_tenant_id()) -- and hits the
    # real conflict path.
    same_tenant_admin_ctx = _ctx(frozenset({"platform_admin"}), tenant_id=tenant_id)
    await set_rls_context(rls_session, same_tenant_admin_ctx)
    with pytest.raises(ConflictError):
        await quotation_service.resolve_inbound_email_tenant(rls_session, same_tenant_admin_ctx, unresolved.id, tenant_id, "again")


async def test_exception_during_elevated_write_still_restores_callers_context(rls_session, monkeypatch):
    """If the single UPDATE inside resolve_inbound_email_tenant's elevated
    block raises, the `finally` must still restore the caller's RLS context
    -- never leave a later statement on this session running as
    app_is_system()."""
    from sqlalchemy.sql.dml import Update

    tenant_id, _rfq = await _seed_tenant_project_rfq(rls_session)
    unresolved = await _seed_inbound_email(rls_session, tenant_id=None, rfq_id=None, needs_review=True)

    admin_ctx = _ctx(frozenset({"platform_admin"}), tenant_id=uuid.uuid4())
    await set_rls_context(rls_session, admin_ctx)

    original_execute = rls_session.execute

    async def _boom(statement, *args, **kwargs):
        if isinstance(statement, Update):
            raise RuntimeError("simulated failure inside the elevated block")
        return await original_execute(statement, *args, **kwargs)

    monkeypatch.setattr(rls_session, "execute", _boom)
    with pytest.raises(RuntimeError, match="simulated failure"):
        await quotation_service.resolve_inbound_email_tenant(rls_session, admin_ctx, unresolved.id, tenant_id, "note")
    monkeypatch.setattr(rls_session, "execute", original_execute)

    row = (
        await rls_session.execute(text("SELECT current_setting('app.is_system', true), current_setting('app.tenant_id', true)"))
    ).one()
    assert row[0] == "off"
    assert row[1] == str(admin_ctx.tenant_id)

    # The row itself is untouched (still tenant_id IS NULL) and still
    # visible/resolvable by a platform_admin, proving the failed write left
    # no partial state behind.
    still_unresolved = await quotation_service.get_inbound_email(rls_session, unresolved.id)
    assert still_unresolved.tenant_id is None


async def test_attach_inbound_email_denied_for_estimator_allowed_for_procurement_head(rls_session):
    tenant_id, rfq = await _seed_tenant_project_rfq(rls_session)
    flagged = await _seed_inbound_email(rls_session, tenant_id=tenant_id, rfq_id=rfq.id, needs_review=True)

    estimator_ctx = _ctx(frozenset({"estimator"}), tenant_id=tenant_id)
    await set_rls_context(rls_session, estimator_ctx)
    with pytest.raises(ForbiddenError):
        await quotation_service.attach_inbound_email_to_rfq(rls_session, estimator_ctx, flagged.id, rfq.id, "confirmed legit")

    lead_ctx = _ctx(frozenset({"lead_estimator"}), tenant_id=tenant_id)
    await set_rls_context(rls_session, lead_ctx)
    with pytest.raises(ForbiddenError):
        await quotation_service.attach_inbound_email_to_rfq(rls_session, lead_ctx, flagged.id, rfq.id, "confirmed legit")

    ph_ctx = _ctx(frozenset({"procurement_head"}), tenant_id=tenant_id)
    await set_rls_context(rls_session, ph_ctx)
    attached = await quotation_service.attach_inbound_email_to_rfq(rls_session, ph_ctx, flagged.id, rfq.id, "confirmed legit")
    assert attached.needs_review is False
    assert attached.review_status == "attached"


# --------------------------------------------------------------------------
# currency/VAT accept-gating (SRS change #4)
# --------------------------------------------------------------------------


async def test_accept_line_item_blocked_until_currency_and_vat_resolved(rls_session):
    tenant_id, rfq = await _seed_tenant_project_rfq(rls_session)
    await _system_ctx(rls_session, tenant_id)
    _quotation, line_item = await _seed_quotation_with_line_item(rls_session, tenant_id=tenant_id, rfq=rfq, currency=None, vat_inclusive=None)

    ph_ctx = _ctx(frozenset({"procurement_head"}), tenant_id=tenant_id)
    await set_rls_context(rls_session, ph_ctx)
    with pytest.raises(ValidationAppError):
        await quotation_service.accept_line_item(rls_session, ph_ctx, line_item.id)

    quotation = await quotation_service.get_quotation(rls_session, line_item.quotation_id)
    await quotation_service.resolve_currency_and_vat(rls_session, ph_ctx, quotation.id, "aed", True)
    accepted = await quotation_service.accept_line_item(rls_session, ph_ctx, line_item.id)
    assert accepted.status == QuotationLineItemStatus.ACCEPTED.value


async def test_accept_reject_role_matrix(rls_session):
    tenant_id, rfq = await _seed_tenant_project_rfq(rls_session)
    await _system_ctx(rls_session, tenant_id)
    _quotation, line_item = await _seed_quotation_with_line_item(rls_session, tenant_id=tenant_id, rfq=rfq, currency="AED", vat_inclusive=True)

    lead_ctx = _ctx(frozenset({"lead_estimator"}), tenant_id=tenant_id)
    await set_rls_context(rls_session, lead_ctx)
    with pytest.raises(ForbiddenError):
        await quotation_service.accept_line_item(rls_session, lead_ctx, line_item.id)

    ph_ctx = _ctx(frozenset({"procurement_head"}), tenant_id=tenant_id)
    await set_rls_context(rls_session, ph_ctx)
    accepted = await quotation_service.accept_line_item(rls_session, ph_ctx, line_item.id)
    assert accepted.status == QuotationLineItemStatus.ACCEPTED.value


# --------------------------------------------------------------------------
# quote versioning (SRS change #3)
# --------------------------------------------------------------------------


async def test_new_version_never_overwrites_an_accepted_line_item(rls_session):
    from app.workers.tasks.quotation_ingestion import _create_quotation_version

    tenant_id, rfq = await _seed_tenant_project_rfq(rls_session)
    await _system_ctx(rls_session, tenant_id)
    quotation_v1, line_item_v1 = await _seed_quotation_with_line_item(rls_session, tenant_id=tenant_id, rfq=rfq, currency="AED", vat_inclusive=True)

    ph_ctx = _ctx(frozenset({"procurement_head"}), tenant_id=tenant_id)
    await set_rls_context(rls_session, ph_ctx)
    await quotation_service.accept_line_item(rls_session, ph_ctx, line_item_v1.id)

    await _system_ctx(rls_session, tenant_id)
    inbound_email_v2 = await _seed_inbound_email(rls_session, tenant_id=tenant_id, rfq_id=rfq.id, needs_review=False)
    attachment_v2 = QuotationAttachment(
        tenant_id=tenant_id, inbound_email_id=inbound_email_v2.id, filename="quote-v2.xlsx",
        size_bytes=1, raw_object_key="inbound/1/v2.xlsx", raw_sha256="0" * 64, safety_status="accepted",
    )
    rls_session.add(attachment_v2)
    await rls_session.flush()
    quotation_v2 = await _create_quotation_version(
        rls_session, rfq=rfq, inbound_email=inbound_email_v2, attachment=attachment_v2,
        extraction_method="deterministic_xlsx", currency="AED", vat_inclusive=True, status="proposed",
    )

    await rls_session.refresh(quotation_v1)
    assert quotation_v1.is_current is False
    assert quotation_v2.is_current is True
    assert quotation_v2.version_no == quotation_v1.version_no + 1

    await rls_session.refresh(line_item_v1)
    assert line_item_v1.status == QuotationLineItemStatus.ACCEPTED.value
    assert line_item_v1.quotation_id == quotation_v1.id

    v1_items = await quotation_service.list_quotation_line_items(rls_session, quotation_v1.id)
    assert len(v1_items) == 1
    assert v1_items[0].status == QuotationLineItemStatus.ACCEPTED.value


# --------------------------------------------------------------------------
# bid leveling (SRS requirement #8 / change #4)
# --------------------------------------------------------------------------


async def test_bid_leveling_shows_accepted_only_and_never_mixes_currencies(rls_session):
    tenant_id, rfq_a = await _seed_tenant_project_rfq(rls_session)
    system_ctx = await _system_ctx(rls_session, tenant_id)
    package_id = rfq_a.package_id
    boq_item = await boq_service.create_line_item(
        rls_session, system_ctx, rfq_a.project_id, BoqLineItemCreate(item_no="1.0", description="Excavation", uom="m3", boq_quantity=100.0)
    )
    boq_line_item_id = boq_item.id

    # Second vendor/RFQ against the SAME package/boq line item, priced in a
    # different currency.
    vendor_b = Vendor(tenant_id=tenant_id, legal_name="Vendor B", normalized_name="vendor b", status="active", primary_email="b@vendor.example")
    rls_session.add(vendor_b)
    await rls_session.flush()
    rfq_b = Rfq(tenant_id=tenant_id, package_id=package_id, project_id=rfq_a.project_id, vendor_id=vendor_b.id, status="sent", reply_token=f"tok-{uuid.uuid4().hex}")
    rls_session.add(rfq_b)
    await rls_session.flush()

    # A third vendor/RFQ whose line item is never accepted, to prove it's
    # excluded from the matrix.
    vendor_c = Vendor(tenant_id=tenant_id, legal_name="Vendor C", normalized_name="vendor c", status="active", primary_email="c@vendor.example")
    rls_session.add(vendor_c)
    await rls_session.flush()
    rfq_c = Rfq(tenant_id=tenant_id, package_id=package_id, project_id=rfq_a.project_id, vendor_id=vendor_c.id, status="sent", reply_token=f"tok-{uuid.uuid4().hex}")
    rls_session.add(rfq_c)
    await rls_session.flush()

    quotation_a, line_a = await _seed_quotation_with_line_item(rls_session, tenant_id=tenant_id, rfq=rfq_a, currency="AED", vat_inclusive=True, unit_price="100.0")
    line_a.boq_line_item_id = boq_line_item_id
    quotation_b, line_b = await _seed_quotation_with_line_item(rls_session, tenant_id=tenant_id, rfq=rfq_b, currency="USD", vat_inclusive=False, unit_price="30.0")
    line_b.boq_line_item_id = boq_line_item_id
    # Unaccepted line item on the same BOQ item -- must be excluded.
    quotation_c, line_c = await _seed_quotation_with_line_item(rls_session, tenant_id=tenant_id, rfq=rfq_c, currency="AED", vat_inclusive=True, unit_price="999.0")
    line_c.boq_line_item_id = boq_line_item_id
    await rls_session.flush()

    ph_ctx = _ctx(frozenset({"procurement_head"}), tenant_id=tenant_id)
    await set_rls_context(rls_session, ph_ctx)
    await quotation_service.accept_line_item(rls_session, ph_ctx, line_a.id)
    await quotation_service.accept_line_item(rls_session, ph_ctx, line_b.id)
    # line_c deliberately left as "proposed" -- never accepted.

    rows = await quotation_service.get_bid_leveling_matrix(rls_session, package_id)
    assert len(rows) == 1
    row = rows[0]
    assert row.boq_line_item_id == boq_line_item_id
    assert len(row.cells) == 2  # line_c excluded
    by_currency = {cell.currency: cell for cell in row.cells}
    assert by_currency["AED"].unit_price == Decimal("100.0")
    assert by_currency["AED"].vat_inclusive is True
    assert by_currency["USD"].unit_price == Decimal("30.0")
    assert by_currency["USD"].vat_inclusive is False
