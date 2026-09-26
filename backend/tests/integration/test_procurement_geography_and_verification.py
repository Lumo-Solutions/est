"""Module C Phase 6: vendor geography eligibility + override (mirroring the
existing prequalification override), project location, quotation-level
subtotal verification, bid-leveling FX normalization, and vendor
service-region CRUD. See docs/module-c-phase6-plan.md."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import RequestContext
from app.core.enums import QuotationExtractionMethod, QuotationStatus
from app.core.errors import ForbiddenError, ValidationAppError
from app.db.rls import set_rls_context
from app.models.procurement import Rfq
from app.models.quotation_ingestion import Quotation, QuotationLineItem
from app.models.vendors import VendorContact, VendorTrade
from app.schemas.boq import BoqLineItemCreate
from app.schemas.prequal import PrequalificationDecision
from app.schemas.procurement import ProcurementPackageCreate, RfqCreateRequest
from app.schemas.projects import ProjectLocationUpdate
from app.schemas.taxonomy import TradeNodeCreate
from app.schemas.vendors import VendorCreate
from app.services import boq as boq_service
from app.services import prequal as prequal_service
from app.services import procurement as procurement_service
from app.services import projects as projects_service
from app.services import quotation_ingestion as quotation_service
from app.services import taxonomy as taxonomy_service
from app.services import vendors as vendors_service

pytestmark = pytest.mark.asyncio


def _ctx(roles: frozenset[str], *, tenant_id: uuid.UUID, is_system: bool = False, user_id: uuid.UUID | None = None, acr: str | None = None) -> RequestContext:
    user_id = user_id or uuid.uuid4()
    return RequestContext(tenant_id=tenant_id, user_id=user_id, sub=str(user_id), roles=roles, is_system=is_system, acr=acr)


_MEMBER_USER_ID = uuid.UUID("00000000-0000-0000-0000-0000000000c6")


async def _seed_prequalified_vendor_and_package(
    session: AsyncSession, tenant_id: uuid.UUID, project_id: uuid.UUID, lead_ctx: RequestContext,
):
    """Active + prequalified (so the ONLY thing that can still make it
    ineligible is geography) -- isolates the geography axis from the
    pre-existing prequalification one."""
    trade = await taxonomy_service.create_node(session, lead_ctx, TradeNodeCreate(code=f"EW-{uuid.uuid4().hex[:6]}", name="Earthworks"))
    vendor = await vendors_service.create_vendor(
        session, lead_ctx, VendorCreate(legal_name=f"Vendor {uuid.uuid4().hex[:6]}", primary_email="quotes@vendor.example")
    )
    vendor.status = "active"
    session.add(VendorTrade(tenant_id=tenant_id, vendor_id=vendor.id, trade_node_id=trade.id))
    session.add(VendorContact(tenant_id=tenant_id, vendor_id=vendor.id, name="Primary", email="quotes@vendor.example", is_primary=True))
    await session.flush()
    await prequal_service.decide_prequalification(
        session, lead_ctx, vendor.id,
        PrequalificationDecision(status="approved", effective_from=date(2020, 1, 1), scope_trade_node_id=trade.id),
    )
    package = await procurement_service.create_package(
        session, lead_ctx, project_id, ProcurementPackageCreate(name="Earthworks Package A", trade_node_id=trade.id)
    )
    item = await boq_service.create_line_item(
        session, lead_ctx, project_id, BoqLineItemCreate(item_no="1.0", description="Excavation", uom="m3", boq_quantity=100.0)
    )
    await procurement_service.add_items(session, lead_ctx, package.id, [item.id])
    return vendor, package, item


async def _seed_project(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID, RequestContext]:
    tenant_id = uuid.uuid4()
    await session.execute(
        text("INSERT INTO tenants (id, slug, name) VALUES (:id, :slug, :name)"),
        {"id": str(tenant_id), "slug": f"acme-{uuid.uuid4().hex[:8]}", "name": "Acme"},
    )
    sys_ctx = _ctx(frozenset(), tenant_id=tenant_id, is_system=True)
    await set_rls_context(session, sys_ctx)
    project_id = (
        await session.execute(
            text("INSERT INTO projects (tenant_id, code, name) VALUES (:t, :c, 'A') RETURNING id"),
            {"t": str(tenant_id), "c": f"C6-{uuid.uuid4().hex[:8]}"},
        )
    ).scalar_one()
    await session.execute(
        text("INSERT INTO project_members (project_id, user_id, tenant_id, project_role) VALUES (:p, :u, :t, 'estimator')"),
        {"p": str(project_id), "u": str(_MEMBER_USER_ID), "t": str(tenant_id)},
    )
    lead_ctx = _ctx(frozenset({"lead_estimator"}), tenant_id=tenant_id, user_id=_MEMBER_USER_ID)
    await set_rls_context(session, lead_ctx)
    return tenant_id, project_id, lead_ctx


# --------------------------------------------------------------------------
# vendor service regions (CRUD)
# --------------------------------------------------------------------------


async def test_replace_and_list_service_regions(rls_session):
    tenant_id, project_id, lead_ctx = await _seed_project(rls_session)
    vendor, _package, _item = await _seed_prequalified_vendor_and_package(rls_session, tenant_id, project_id, lead_ctx)

    created = await vendors_service.replace_service_regions(rls_session, lead_ctx, vendor.id, ["Dubai", "Sharjah"])
    assert {r.emirate for r in created} == {"Dubai", "Sharjah"}

    listed = await vendors_service.list_service_regions(rls_session, vendor.id)
    assert {r.emirate for r in listed} == {"Dubai", "Sharjah"}

    replaced = await vendors_service.replace_service_regions(rls_session, lead_ctx, vendor.id, ["Abu Dhabi"])
    assert {r.emirate for r in replaced} == {"Abu Dhabi"}
    listed_again = await vendors_service.list_service_regions(rls_session, vendor.id)
    assert {r.emirate for r in listed_again} == {"Abu Dhabi"}


# --------------------------------------------------------------------------
# project location
# --------------------------------------------------------------------------


async def test_update_project_location(rls_session):
    tenant_id, project_id, _lead_ctx = await _seed_project(rls_session)
    md_ctx = _ctx(frozenset({"managing_director"}), tenant_id=tenant_id, is_system=True)
    await set_rls_context(rls_session, md_ctx)

    updated = await projects_service.update_location(
        rls_session, md_ctx, project_id, ProjectLocationUpdate(emirate="Dubai", area="Business Bay", latitude=25.18, longitude=55.26)
    )
    assert updated.emirate == "Dubai"
    assert updated.area == "Business Bay"
    assert float(updated.latitude) == pytest.approx(25.18)


# --------------------------------------------------------------------------
# geography eligibility + override (mirrors the prequalification override)
# --------------------------------------------------------------------------


async def test_match_vendors_reflects_geography_ineligibility_and_service_regions(rls_session):
    tenant_id, project_id, lead_ctx = await _seed_project(rls_session)
    vendor, package, _item = await _seed_prequalified_vendor_and_package(rls_session, tenant_id, project_id, lead_ctx)
    await vendors_service.replace_service_regions(rls_session, lead_ctx, vendor.id, ["Sharjah"])
    md_ctx = _ctx(frozenset({"managing_director"}), tenant_id=tenant_id, is_system=True)
    await set_rls_context(rls_session, md_ctx)
    await projects_service.update_location(rls_session, md_ctx, project_id, ProjectLocationUpdate(emirate="Dubai"))

    await set_rls_context(rls_session, lead_ctx)
    matches = await procurement_service.match_vendors(rls_session, package.id)
    match = next(m for m in matches if m.vendor_id == vendor.id)
    assert match.eligible is False
    assert "Dubai" in match.ineligible_reason
    assert match.service_regions == ["Sharjah"]


async def test_create_rfqs_denies_geography_ineligible_vendor_without_override(rls_session):
    tenant_id, project_id, lead_ctx = await _seed_project(rls_session)
    vendor, package, _item = await _seed_prequalified_vendor_and_package(rls_session, tenant_id, project_id, lead_ctx)
    await vendors_service.replace_service_regions(rls_session, lead_ctx, vendor.id, ["Sharjah"])
    md_ctx = _ctx(frozenset({"managing_director"}), tenant_id=tenant_id, is_system=True)
    await set_rls_context(rls_session, md_ctx)
    await projects_service.update_location(rls_session, md_ctx, project_id, ProjectLocationUpdate(emirate="Dubai"))

    await set_rls_context(rls_session, lead_ctx)
    with pytest.raises(ValidationAppError):
        await procurement_service.create_rfqs(rls_session, lead_ctx, package.id, RfqCreateRequest(vendor_ids=[vendor.id]))


async def test_create_rfqs_override_denied_for_lead_estimator_allowed_for_procurement_head(rls_session):
    """Same role gate as the existing prequalification override
    (_DISPATCH_ROLES = procurement_head+) -- lead_estimator (the lowest
    role that can otherwise create an RFQ at all) is denied the override
    specifically; procurement_head succeeds and it's audited."""
    tenant_id, project_id, lead_ctx = await _seed_project(rls_session)
    vendor, package, _item = await _seed_prequalified_vendor_and_package(rls_session, tenant_id, project_id, lead_ctx)
    await vendors_service.replace_service_regions(rls_session, lead_ctx, vendor.id, ["Sharjah"])
    md_ctx = _ctx(frozenset({"managing_director"}), tenant_id=tenant_id, is_system=True)
    await set_rls_context(rls_session, md_ctx)
    await projects_service.update_location(rls_session, md_ctx, project_id, ProjectLocationUpdate(emirate="Dubai"))

    await set_rls_context(rls_session, lead_ctx)
    with pytest.raises(ForbiddenError):
        await procurement_service.create_rfqs(
            rls_session, lead_ctx, package.id, RfqCreateRequest(vendor_ids=[vendor.id], override_reason="urgent, only bidder")
        )

    proc_head_ctx = _ctx(frozenset({"procurement_head"}), tenant_id=tenant_id, is_system=True)
    await set_rls_context(rls_session, proc_head_ctx)
    [rfq] = await procurement_service.create_rfqs(
        rls_session, proc_head_ctx, package.id, RfqCreateRequest(vendor_ids=[vendor.id], override_reason="urgent, only bidder")
    )
    assert rfq.is_override is True
    assert rfq.override_reason == "urgent, only bidder"


async def test_geography_not_evaluated_when_project_has_no_emirate(rls_session):
    tenant_id, project_id, lead_ctx = await _seed_project(rls_session)
    vendor, package, _item = await _seed_prequalified_vendor_and_package(rls_session, tenant_id, project_id, lead_ctx)
    await vendors_service.replace_service_regions(rls_session, lead_ctx, vendor.id, ["Sharjah"])
    # No project location set at all.

    [rfq] = await procurement_service.create_rfqs(rls_session, lead_ctx, package.id, RfqCreateRequest(vendor_ids=[vendor.id]))
    assert rfq.is_override is False


# --------------------------------------------------------------------------
# subtotal verification + bid-leveling FX normalization
# --------------------------------------------------------------------------


async def _seed_quotation(
    session: AsyncSession, *, tenant_id: uuid.UUID, rfq: Rfq, unit_price: str, currency: str = "AED",
    stated_total: Decimal | None = None, total_mismatch: bool = False,
    boq_line_item_id: uuid.UUID | None = None,
) -> Quotation:
    quotation = Quotation(
        tenant_id=tenant_id, rfq_id=rfq.id, vendor_id=rfq.vendor_id, package_id=rfq.package_id, project_id=rfq.project_id,
        extraction_method=QuotationExtractionMethod.DETERMINISTIC_XLSX.value, currency=currency, vat_inclusive=True,
        submitted_at=datetime.now(timezone.utc), status=QuotationStatus.PROPOSED.value,
        stated_total=stated_total, total_mismatch=total_mismatch,
    )
    session.add(quotation)
    await session.flush()
    line_item = QuotationLineItem(
        tenant_id=tenant_id, quotation_id=quotation.id, project_id=rfq.project_id, boq_line_item_id=boq_line_item_id,
        unit_price=Decimal(unit_price), source="deterministic", status="accepted",
    )
    session.add(line_item)
    await session.flush()
    return quotation


async def test_get_quotation_totals_surfaces_stated_total_and_mismatch(rls_session):
    tenant_id, project_id, lead_ctx = await _seed_project(rls_session)
    vendor, package, _item = await _seed_prequalified_vendor_and_package(rls_session, tenant_id, project_id, lead_ctx)
    [rfq] = await procurement_service.create_rfqs(rls_session, lead_ctx, package.id, RfqCreateRequest(vendor_ids=[vendor.id]))

    # quotations/quotation_line_items are procurement_head+ (normally
    # written by the system-actor ingestion pipeline) -- seed as a system
    # actor, same as every other quotation-ingestion integration test.
    sys_ctx = _ctx(frozenset(), tenant_id=tenant_id, is_system=True)
    await set_rls_context(rls_session, sys_ctx)
    await _seed_quotation(rls_session, tenant_id=tenant_id, rfq=rfq, unit_price="100.0", stated_total=Decimal("350.00"), total_mismatch=True)

    await set_rls_context(rls_session, lead_ctx)
    totals = await quotation_service.get_quotation_totals(rls_session, package.id)
    assert len(totals) == 1
    assert totals[0].stated_total == Decimal("350.00")
    assert totals[0].total_mismatch is True


async def test_set_quotation_fx_rate_role_gating_and_bid_leveling_normalization(rls_session):
    tenant_id, project_id, lead_ctx = await _seed_project(rls_session)
    vendor, package, boq_item = await _seed_prequalified_vendor_and_package(rls_session, tenant_id, project_id, lead_ctx)
    [rfq] = await procurement_service.create_rfqs(rls_session, lead_ctx, package.id, RfqCreateRequest(vendor_ids=[vendor.id]))

    sys_ctx = _ctx(frozenset(), tenant_id=tenant_id, is_system=True)
    await set_rls_context(rls_session, sys_ctx)
    quotation = await _seed_quotation(
        rls_session, tenant_id=tenant_id, rfq=rfq, unit_price="100.0", currency="USD", boq_line_item_id=boq_item.id,
    )

    # lead_estimator (the lowest role that can otherwise touch this
    # package) is denied -- fx-rate recording is procurement_head+, same
    # tier as resolve_currency_and_vat.
    await set_rls_context(rls_session, lead_ctx)
    with pytest.raises(ForbiddenError):
        await quotation_service.set_quotation_fx_rate(rls_session, lead_ctx, quotation.id, Decimal("3.6725"), date(2026, 1, 1))

    before = await quotation_service.get_bid_leveling_matrix(rls_session, package.id)
    assert before[0].cells[0].normalized_unit_price is None

    proc_head_ctx = _ctx(frozenset({"procurement_head"}), tenant_id=tenant_id, is_system=True)
    await set_rls_context(rls_session, proc_head_ctx)
    updated = await quotation_service.set_quotation_fx_rate(rls_session, proc_head_ctx, quotation.id, Decimal("3.6725"), date(2026, 1, 1))
    assert updated.fx_rate_to_base == Decimal("3.6725")

    after = await quotation_service.get_bid_leveling_matrix(rls_session, package.id)
    cell = after[0].cells[0]
    assert cell.unit_price == Decimal("100.0")  # raw figure untouched
    assert cell.currency == "USD"  # raw currency untouched
    assert cell.normalized_unit_price == Decimal("100.0") * Decimal("3.6725")


# --------------------------------------------------------------------------
# end-to-end LLM ingestion wiring: subtotal, unit conversion, citation
# (the real _extract_quotation_body function, extract_quotation()
# monkeypatched to a controlled result -- real vLLM output quality can't
# be relied on deterministically, see docs/build-log.md's Phase 6 section,
# so this proves the actual code path this phase changed, not just the
# pure helper functions already covered in tests/unit/test_quotation_verification.py)
# --------------------------------------------------------------------------


async def test_extract_quotation_body_wires_subtotal_unit_and_citation_verification(rls_session, monkeypatch):
    from app.models.quotation_ingestion import InboundEmail, QuotationAttachment, QuotationExclusionFlag
    from app.procurement.quotation_extraction import ExtractedExclusion, ExtractedLineItem, QuotationExtractionResult
    from app.workers.tasks import quotation_ingestion as worker_module

    tenant_id, project_id, lead_ctx = await _seed_project(rls_session)
    vendor, package, boq_item = await _seed_prequalified_vendor_and_package(rls_session, tenant_id, project_id, lead_ctx)
    [rfq] = await procurement_service.create_rfqs(rls_session, lead_ctx, package.id, RfqCreateRequest(vendor_ids=[vendor.id]))

    sys_ctx = _ctx(frozenset(), tenant_id=tenant_id, is_system=True)
    await set_rls_context(rls_session, sys_ctx)
    inbound_email = InboundEmail(
        tenant_id=tenant_id, rfq_id=rfq.id, imap_uid_validity="1", imap_uid="1",
        from_address="vendor@example.com", from_domain="example.com", to_address="rfq+x.y@installtec.local",
        received_at=datetime.now(timezone.utc), match_status="matched", needs_review=False,
        raw_object_key="inbound/1/1.eml", raw_sha256="0" * 64,
    )
    rls_session.add(inbound_email)
    await rls_session.flush()
    attachment = QuotationAttachment(
        tenant_id=tenant_id, inbound_email_id=inbound_email.id, filename="quote.csv",
        size_bytes=10, raw_object_key="fake-key", raw_sha256="1" * 64,
    )
    rls_session.add(attachment)
    await rls_session.flush()

    source_text = "Item 1.0 Excavation. Excludes dewatering and groundwater control. Grand Total: AED 15000.00"

    async def _fake_get_object_bytes(*_args, **_kwargs):
        return source_text.encode("utf-8")

    async def _fake_extract_quotation(**_kwargs):
        return QuotationExtractionResult(
            currency="AED", vat_inclusive=True,
            line_items=[
                ExtractedLineItem(
                    vendor_description_text=boq_item.description, unit_price=48.0, quantity=100.0,
                    # convertible with boq_item.uom="m3" (same volume unit, different notation) and
                    # numerically equal to the BOQ's own boq_quantity=100.0 once converted -- isolates
                    # the unit-conversion path from a genuine quantity discrepancy.
                    vendor_uom="CUM",
                ),
            ],
            stated_total=15000.0,  # 48.0 * 100.0 = 4800.0 -- deliberately mismatched
            exclusions=[
                ExtractedExclusion(
                    flag_text="Excludes dewatering", source_quote_text="Excludes dewatering and groundwater control.",
                    source_location="row1",
                ),
            ],
            confidence=0.9,
        )

    monkeypatch.setattr(worker_module, "get_object_bytes", _fake_get_object_bytes)
    monkeypatch.setattr(worker_module, "extract_quotation", _fake_extract_quotation)

    await worker_module._extract_quotation_body(rls_session, str(attachment.id), QuotationExtractionMethod.VLM_CSV.value)

    quotation = (
        await rls_session.execute(select(Quotation).where(Quotation.inbound_email_id == inbound_email.id))
    ).scalar_one()
    assert float(quotation.stated_total) == 15000.0
    assert quotation.total_mismatch is True

    line_item = (
        await rls_session.execute(select(QuotationLineItem).where(QuotationLineItem.quotation_id == quotation.id))
    ).scalar_one()
    assert line_item.vendor_uom == "CUM"
    assert line_item.uom_mismatch is False  # convertible (same volume unit), never flagged as a category error
    assert line_item.quantity_mismatch is False  # 100 CUM converts to 100 m3, matching the BOQ's own boq_quantity

    flag = (
        await rls_session.execute(select(QuotationExclusionFlag).where(QuotationExclusionFlag.quotation_id == quotation.id))
    ).scalar_one()
    assert flag.source_location == "row1"
    assert flag.citation_verified is True  # the citation is a verbatim substring of source_text

    # Phase 8d: list_exclusion_flags() -- the read the bid-leveling
    # screen's exclusion-flag/citation panel needs; no such listing
    # existed anywhere before (only acknowledge, which needs a
    # caller-supplied flag_id).
    listed = await quotation_service.list_exclusion_flags(rls_session, quotation.id)
    assert [f.id for f in listed] == [flag.id]
