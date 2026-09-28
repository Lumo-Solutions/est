"""Module D1: bid settlement and margin simulation. See
docs/module-d1-plan.md for the design this exercises: percentage
resolution (line > trade > default), the rates-are-authoritative rounding
rule, the status lifecycle, the quantity-vs-live-BOQ check at submit,
segregation of duties, and role gating (lowest allowed role + a denied
role per permission, per the build brief's testing rule).
"""

from __future__ import annotations

import time
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import RequestContext
from app.core.enums import BidSettlementStatus, QuotationExtractionMethod, QuotationLineItemStatus, QuotationStatus
from app.core.errors import ConflictError, ForbiddenError, NotFoundError
from app.db.rls import set_rls_context
from app.models.quotation_ingestion import Quotation, QuotationLineItem
from app.models.taxonomy import TradeNode
from app.schemas.boq import BoqLineItemCreate
from app.schemas.settlement import (
    FxRateSet,
    LineCostUpdate,
    ScenarioCreate,
    SettlementDefaultsUpdate,
    SimulateRequest,
    TradeOverrideUpdate,
)
from app.services import boq as boq_service
from app.services import settlement as settlement_service

pytestmark = pytest.mark.asyncio


def _ctx(roles: frozenset[str], *, tenant_id: uuid.UUID, is_system: bool = False, user_id: uuid.UUID | None = None, acr: str | None = None) -> RequestContext:
    user_id = user_id or uuid.uuid4()
    # auth_time="just now" whenever acr is set -- has_recent_step_up
    # (app/security/deps.py, fix/keycloak-step-up) requires both acr AND a
    # recent auth_time, not acr alone, so a bare acr="silver" here would
    # otherwise 403 with StepUpRequiredError.
    auth_time = int(time.time()) if acr else None
    return RequestContext(tenant_id=tenant_id, user_id=user_id, sub=str(user_id), roles=roles, is_system=is_system, acr=acr, auth_time=auth_time)


async def _system_ctx(session: AsyncSession, tenant_id: uuid.UUID) -> RequestContext:
    ctx = _ctx(frozenset(), tenant_id=tenant_id, is_system=True)
    await set_rls_context(session, ctx)
    return ctx


# lead_estimator/estimator (unlike procurement_head+) are NOT covered by
# app_can_see_project()'s role bypass -- they need an actual project_members
# row. One fixed id, granted membership on every test's fresh project, used
# by every lead_estimator/estimator RequestContext below.
_MEMBER_USER_ID = uuid.UUID("00000000-0000-0000-0000-0000000000e1")


async def _seed_bid_submission_policy(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Same shape as app/cli.py::seed's default bid_submission policy --
    tests don't run the CLI seed, so each test's fresh tenant needs its own
    copy for submit_settlement() to route against."""
    from app.models.approvals import ApprovalPolicy, ApprovalPolicyTier

    policy = ApprovalPolicy(
        tenant_id=tenant_id, entity_type="bid_submission", name="Test bid-settlement approval policy",
        version=1, mode="highest_tier_only", is_active=True,
    )
    session.add(policy)
    await session.flush()
    session.add_all(
        [
            ApprovalPolicyTier(tenant_id=tenant_id, policy_id=policy.id, seq=1, min_amount=0, max_amount=2_000_000.00, required_role="bd_director"),
            ApprovalPolicyTier(tenant_id=tenant_id, policy_id=policy.id, seq=2, min_amount=2_000_000.01, max_amount=None, max_margin_pct=8, required_role="managing_director"),
        ]
    )
    await session.flush()


async def _seed_project(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    tenant_id = uuid.uuid4()
    await session.execute(
        text("INSERT INTO tenants (id, slug, name) VALUES (:id, :slug, :name)"),
        {"id": str(tenant_id), "slug": f"acme-{uuid.uuid4().hex[:8]}", "name": "Acme"},
    )
    await _system_ctx(session, tenant_id)
    project_id = (
        await session.execute(
            text("INSERT INTO projects (tenant_id, code, name) VALUES (:t, :c, 'A') RETURNING id"),
            {"t": str(tenant_id), "c": f"D1-{uuid.uuid4().hex[:8]}"},
        )
    ).scalar_one()
    await session.execute(
        text("INSERT INTO project_members (project_id, user_id, tenant_id) VALUES (:p, :u, :t)"),
        {"p": str(project_id), "u": str(_MEMBER_USER_ID), "t": str(tenant_id)},
    )
    await _seed_bid_submission_policy(session, tenant_id)
    return tenant_id, project_id


async def _add_boq_item(session, ctx, project_id, item_no, qty, *, trade_node_id=None, uom="m3"):
    return await boq_service.create_line_item(
        session, ctx, project_id,
        BoqLineItemCreate(item_no=item_no, description=f"Item {item_no}", uom=uom, boq_quantity=qty, trade_node_id=trade_node_id),
    )


async def _seed_accepted_quotation_line(session, ctx, *, project_id, boq_item, unit_price: str, currency="AED") -> QuotationLineItem:
    """A minimal Quotation/QuotationLineItem pair with status=accepted --
    settlement tests need this to exercise cost_source=quotation_line, but
    don't need a real RFQ/vendor/package (Quotation just needs valid FKs)."""
    vendor_id = (
        await session.execute(
            text(
                "INSERT INTO vendors (tenant_id, legal_name, normalized_name, status, primary_email) "
                "VALUES (:t, 'V', 'v', 'active', 'v@example.com') RETURNING id"
            ),
            {"t": str(ctx.tenant_id)},
        )
    ).scalar_one()
    package_id = (
        await session.execute(
            text("INSERT INTO procurement_packages (tenant_id, project_id, name, status) VALUES (:t, :p, 'Pkg', 'sent') RETURNING id"),
            {"t": str(ctx.tenant_id), "p": str(project_id)},
        )
    ).scalar_one()
    rfq_id = (
        await session.execute(
            text(
                "INSERT INTO rfqs (tenant_id, package_id, project_id, vendor_id, status, reply_token) "
                "VALUES (:t, :pkg, :p, :v, 'sent', :tok) RETURNING id"
            ),
            {"t": str(ctx.tenant_id), "pkg": str(package_id), "p": str(project_id), "v": str(vendor_id), "tok": f"tok-{uuid.uuid4().hex}"},
        )
    ).scalar_one()

    quotation = Quotation(
        tenant_id=ctx.tenant_id, rfq_id=rfq_id, vendor_id=vendor_id, package_id=package_id, project_id=project_id,
        extraction_method=QuotationExtractionMethod.DETERMINISTIC_XLSX.value, version_no=1, is_current=True,
        currency=currency, vat_inclusive=True, submitted_at=datetime.now(timezone.utc), status=QuotationStatus.PROPOSED.value,
    )
    session.add(quotation)
    await session.flush()
    line_item = QuotationLineItem(
        tenant_id=ctx.tenant_id, quotation_id=quotation.id, project_id=project_id, boq_line_item_id=boq_item.id,
        unit_price=Decimal(unit_price), quantity=Decimal(str(boq_item.boq_quantity)), confidence=Decimal("1.0"),
        source="deterministic", status=QuotationLineItemStatus.ACCEPTED.value, accepted_at=datetime.now(timezone.utc),
    )
    session.add(line_item)
    await session.flush()
    return line_item


LEAD = frozenset({"lead_estimator"})
ESTIMATOR = frozenset({"estimator"})
BD = frozenset({"bd_director"})
MD = frozenset({"managing_director"})


# --------------------------------------------------------------------------
# build draft: auto-resolution, role gating
# --------------------------------------------------------------------------


async def test_build_draft_auto_resolves_uniquely_accepted_line_and_leaves_others_unresolved(rls_session):
    tenant_id, project_id = await _seed_project(rls_session)
    sys_ctx = await _system_ctx(rls_session, tenant_id)
    resolved_item = await _add_boq_item(rls_session, sys_ctx, project_id, "1.0", 500)
    unresolved_item = await _add_boq_item(rls_session, sys_ctx, project_id, "2.0", 10)
    await _seed_accepted_quotation_line(rls_session, sys_ctx, project_id=project_id, boq_item=resolved_item, unit_price="45.00")

    lead_ctx = _ctx(LEAD, tenant_id=tenant_id, user_id=_MEMBER_USER_ID)
    await set_rls_context(rls_session, lead_ctx)
    settlement = await settlement_service.build_settlement_draft(rls_session, lead_ctx, project_id)
    assert settlement.version_no == 1
    assert settlement.is_current is True
    assert settlement.status == BidSettlementStatus.DRAFT.value

    lines = await settlement_service.list_settlement_lines(rls_session, settlement.id)
    by_item = {line.boq_line_item_id: line for line in lines}
    assert by_item[resolved_item.id].direct_unit_cost == Decimal("45.00")
    assert by_item[resolved_item.id].cost_source == "quotation_line"
    assert by_item[unresolved_item.id].direct_unit_cost is None


async def test_build_draft_leaves_line_unresolved_when_multiple_vendors_accepted(rls_session):
    """Never silently averages/auto-picks between competing accepted bids."""
    tenant_id, project_id = await _seed_project(rls_session)
    sys_ctx = await _system_ctx(rls_session, tenant_id)
    item = await _add_boq_item(rls_session, sys_ctx, project_id, "1.0", 100)
    await _seed_accepted_quotation_line(rls_session, sys_ctx, project_id=project_id, boq_item=item, unit_price="10.00")
    await _seed_accepted_quotation_line(rls_session, sys_ctx, project_id=project_id, boq_item=item, unit_price="12.00")

    lead_ctx = _ctx(LEAD, tenant_id=tenant_id, user_id=_MEMBER_USER_ID)
    await set_rls_context(rls_session, lead_ctx)
    settlement = await settlement_service.build_settlement_draft(rls_session, lead_ctx, project_id)
    lines = await settlement_service.list_settlement_lines(rls_session, settlement.id)
    assert lines[0].direct_unit_cost is None


async def test_build_draft_denies_estimator_role(rls_session):
    tenant_id, project_id = await _seed_project(rls_session)
    estimator_ctx = _ctx(ESTIMATOR, tenant_id=tenant_id, user_id=_MEMBER_USER_ID)
    await set_rls_context(rls_session, estimator_ctx)
    with pytest.raises(ForbiddenError):
        await settlement_service.build_settlement_draft(rls_session, estimator_ctx, project_id)


# --------------------------------------------------------------------------
# percentage resolution cascade (line > trade > default)
# --------------------------------------------------------------------------


async def test_percentage_resolution_cascade(rls_session):
    tenant_id, project_id = await _seed_project(rls_session)
    sys_ctx = await _system_ctx(rls_session, tenant_id)
    trade = TradeNode(tenant_id=tenant_id, parent_id=None, code="EARTH", name="Earthworks", path="earth")
    rls_session.add(trade)
    await rls_session.flush()

    item_default = await _add_boq_item(rls_session, sys_ctx, project_id, "1.0", 100)  # no trade -- can never see the trade override
    item_trade = await _add_boq_item(rls_session, sys_ctx, project_id, "2.0", 100, trade_node_id=trade.id)
    item_line_override = await _add_boq_item(rls_session, sys_ctx, project_id, "3.0", 100, trade_node_id=trade.id)
    await _seed_accepted_quotation_line(rls_session, sys_ctx, project_id=project_id, boq_item=item_default, unit_price="10.00")
    await _seed_accepted_quotation_line(rls_session, sys_ctx, project_id=project_id, boq_item=item_trade, unit_price="10.00")
    await _seed_accepted_quotation_line(rls_session, sys_ctx, project_id=project_id, boq_item=item_line_override, unit_price="10.00")

    lead_ctx = _ctx(LEAD, tenant_id=tenant_id, user_id=_MEMBER_USER_ID)
    await set_rls_context(rls_session, lead_ctx)
    settlement = await settlement_service.build_settlement_draft(rls_session, lead_ctx, project_id)
    await settlement_service.set_defaults(rls_session, lead_ctx, settlement.id, SettlementDefaultsUpdate(default_markup_pct=10))
    await settlement_service.set_trade_override(rls_session, lead_ctx, settlement.id, trade.id, TradeOverrideUpdate(markup_pct=20))

    lines = await settlement_service.list_settlement_lines(rls_session, settlement.id)
    line_override_row = next(line for line in lines if line.boq_line_item_id == item_line_override.id)
    estimator_ctx = _ctx(ESTIMATOR, tenant_id=tenant_id, user_id=_MEMBER_USER_ID)
    await set_rls_context(rls_session, estimator_ctx)
    await settlement_service.set_line_cost(
        rls_session, estimator_ctx, settlement.id, line_override_row.id, LineCostUpdate(markup_pct_override=30)
    )

    result = await settlement_service.simulate(rls_session, estimator_ctx, settlement.id, SimulateRequest())
    by_item = {r.boq_line_item_id: r for r in result.lines}
    assert by_item[item_default.id].markup_pct == Decimal("10")  # no trade -- falls through to project default
    assert by_item[item_trade.id].markup_pct == Decimal("20")  # trade override wins over the project default
    assert by_item[item_line_override.id].markup_pct == Decimal("30")  # line override wins over trade (20) and default (10)


# --------------------------------------------------------------------------
# submit: unresolved lines, FX, quantity staleness, rounding, SoD
# --------------------------------------------------------------------------


async def _draft_with_one_resolved_line(rls_session, *, unit_price="45.00", qty=500) -> tuple[uuid.UUID, uuid.UUID, object]:
    tenant_id, project_id = await _seed_project(rls_session)
    sys_ctx = await _system_ctx(rls_session, tenant_id)
    item = await _add_boq_item(rls_session, sys_ctx, project_id, "1.0", qty)
    await _seed_accepted_quotation_line(rls_session, sys_ctx, project_id=project_id, boq_item=item, unit_price=unit_price)
    lead_ctx = _ctx(LEAD, tenant_id=tenant_id, user_id=_MEMBER_USER_ID)
    await set_rls_context(rls_session, lead_ctx)
    settlement = await settlement_service.build_settlement_draft(rls_session, lead_ctx, project_id)
    # A healthy default markup so margin-on-sell clears the 8% MD-escalation
    # floor -- callers that specifically want to exercise that escalation
    # (e.g. test_large_settlement_routes_to_managing_director_end_to_end)
    # set their own defaults afterwards, overriding this.
    await settlement_service.set_defaults(rls_session, lead_ctx, settlement.id, SettlementDefaultsUpdate(default_markup_pct=10))
    return tenant_id, project_id, settlement


async def test_submit_blocked_by_unresolved_line(rls_session):
    tenant_id, project_id = await _seed_project(rls_session)
    sys_ctx = await _system_ctx(rls_session, tenant_id)
    await _add_boq_item(rls_session, sys_ctx, project_id, "1.0", 100)  # no accepted quote -- stays unresolved
    lead_ctx = _ctx(LEAD, tenant_id=tenant_id, user_id=_MEMBER_USER_ID)
    await set_rls_context(rls_session, lead_ctx)
    settlement = await settlement_service.build_settlement_draft(rls_session, lead_ctx, project_id)

    bd_ctx = _ctx(BD, tenant_id=tenant_id, acr="silver")
    await set_rls_context(rls_session, bd_ctx)
    with pytest.raises(ConflictError):
        await settlement_service.submit_settlement(rls_session, bd_ctx, settlement.id)


async def test_submit_blocked_by_missing_fx_rate_then_unblocked(rls_session):
    tenant_id, project_id = await _seed_project(rls_session)
    sys_ctx = await _system_ctx(rls_session, tenant_id)
    item = await _add_boq_item(rls_session, sys_ctx, project_id, "1.0", 100)
    await _seed_accepted_quotation_line(rls_session, sys_ctx, project_id=project_id, boq_item=item, unit_price="10.00", currency="USD")

    lead_ctx = _ctx(LEAD, tenant_id=tenant_id, user_id=_MEMBER_USER_ID)
    await set_rls_context(rls_session, lead_ctx)
    settlement = await settlement_service.build_settlement_draft(rls_session, lead_ctx, project_id)
    lines = await settlement_service.list_settlement_lines(rls_session, settlement.id)
    line = lines[0]
    assert line.source_currency == "USD"
    assert settlement.currency == "AED"

    bd_ctx = _ctx(BD, tenant_id=tenant_id, acr="silver")
    await set_rls_context(rls_session, bd_ctx)
    with pytest.raises(ConflictError):
        await settlement_service.submit_settlement(rls_session, bd_ctx, settlement.id)

    await set_rls_context(rls_session, lead_ctx)
    await settlement_service.set_line_fx_rate(
        rls_session, lead_ctx, settlement.id, line.id, FxRateSet(fx_rate=Decimal("3.67"), fx_rate_date=date.today())
    )

    await set_rls_context(rls_session, bd_ctx)
    submitted = await settlement_service.submit_settlement(rls_session, bd_ctx, settlement.id)
    assert submitted.status == BidSettlementStatus.SUBMITTED.value


async def test_submit_blocked_by_stale_quantity_then_unblocked_by_refresh(rls_session):
    tenant_id, project_id, settlement = await _draft_with_one_resolved_line(rls_session, qty=500)
    lead_ctx = _ctx(LEAD, tenant_id=tenant_id, user_id=_MEMBER_USER_ID)
    await set_rls_context(rls_session, lead_ctx)

    lines = await settlement_service.list_settlement_lines(rls_session, settlement.id)
    boq_item_id = lines[0].boq_line_item_id
    await rls_session.execute(
        text("UPDATE boq_line_items SET boq_quantity = 600 WHERE id = :id"), {"id": str(boq_item_id)}
    )

    bd_ctx = _ctx(BD, tenant_id=tenant_id, acr="silver")
    await set_rls_context(rls_session, bd_ctx)
    with pytest.raises(ConflictError):
        await settlement_service.submit_settlement(rls_session, bd_ctx, settlement.id)

    await set_rls_context(rls_session, lead_ctx)
    await settlement_service.refresh_quantities(rls_session, lead_ctx, settlement.id)
    refreshed = await settlement_service.list_settlement_lines(rls_session, settlement.id)
    assert refreshed[0].quantity == Decimal("600.0000") or refreshed[0].quantity == Decimal("600")
    assert refreshed[0].quantity_at_build == Decimal("500.0000") or refreshed[0].quantity_at_build == Decimal("500")
    # direct_unit_cost/source untouched by the refresh (§5c)
    assert refreshed[0].direct_unit_cost == Decimal("45.00")
    assert refreshed[0].cost_source == "quotation_line"

    await set_rls_context(rls_session, bd_ctx)
    submitted = await settlement_service.submit_settlement(rls_session, bd_ctx, settlement.id)
    assert submitted.status == BidSettlementStatus.SUBMITTED.value


async def test_submit_denies_lead_estimator_role(rls_session):
    tenant_id, project_id, settlement = await _draft_with_one_resolved_line(rls_session)
    lead_ctx = _ctx(LEAD, tenant_id=tenant_id, user_id=_MEMBER_USER_ID)
    await set_rls_context(rls_session, lead_ctx)
    with pytest.raises(ForbiddenError):
        await settlement_service.submit_settlement(rls_session, lead_ctx, settlement.id)


async def test_submit_computes_rates_authoritative_totals_matching_worked_example(rls_session):
    """End-to-end reproduction of docs/module-d1-plan.md §5 through the
    real service/DB path (three lines, a trade override, a line-level
    markup override)."""
    tenant_id, project_id = await _seed_project(rls_session)
    sys_ctx = await _system_ctx(rls_session, tenant_id)
    trade = TradeNode(tenant_id=tenant_id, parent_id=None, code="EARTH", name="Earthworks", path="earth")
    rls_session.add(trade)
    await rls_session.flush()

    l1 = await _add_boq_item(rls_session, sys_ctx, project_id, "1.0", 500, trade_node_id=trade.id)
    l2 = await _add_boq_item(rls_session, sys_ctx, project_id, "2.0", 200)
    l3 = await _add_boq_item(rls_session, sys_ctx, project_id, "3.0", 15000, uom="kg")
    await _seed_accepted_quotation_line(rls_session, sys_ctx, project_id=project_id, boq_item=l1, unit_price="45.00")
    await _seed_accepted_quotation_line(rls_session, sys_ctx, project_id=project_id, boq_item=l2, unit_price="380.00")
    await _seed_accepted_quotation_line(rls_session, sys_ctx, project_id=project_id, boq_item=l3, unit_price="3.85")

    lead_ctx = _ctx(LEAD, tenant_id=tenant_id, user_id=_MEMBER_USER_ID)
    await set_rls_context(rls_session, lead_ctx)
    settlement = await settlement_service.build_settlement_draft(rls_session, lead_ctx, project_id)
    await settlement_service.set_defaults(
        rls_session, lead_ctx, settlement.id,
        SettlementDefaultsUpdate(default_plant_pct=2, default_overhead_pct=5, default_volatility_pct=3, default_markup_pct=10),
    )
    await settlement_service.set_trade_override(rls_session, lead_ctx, settlement.id, trade.id, TradeOverrideUpdate(volatility_pct=6))

    lines = await settlement_service.list_settlement_lines(rls_session, settlement.id)
    l3_line = next(line for line in lines if line.boq_line_item_id == l3.id)
    estimator_ctx = _ctx(ESTIMATOR, tenant_id=tenant_id, user_id=_MEMBER_USER_ID)
    await set_rls_context(rls_session, estimator_ctx)
    await settlement_service.set_line_cost(rls_session, estimator_ctx, settlement.id, l3_line.id, LineCostUpdate(markup_pct_override=15))

    bd_ctx = _ctx(BD, tenant_id=tenant_id, acr="silver")
    await set_rls_context(rls_session, bd_ctx)
    submitted = await settlement_service.submit_settlement(rls_session, bd_ctx, settlement.id)

    assert submitted.tender_total == Decimal("193406.00")
    assert submitted.rounding_difference == Decimal("5.77")
    assert submitted.margin_on_sell_pct == Decimal("10.586")

    final_lines = await settlement_service.list_settlement_lines(rls_session, settlement.id)
    rates = {line.boq_line_item_id: line.unit_sell_rate for line in final_lines}
    assert rates[l1.id] == Decimal("56.14")
    assert rates[l2.id] == Decimal("460.68")
    assert rates[l3.id] == Decimal("4.88")
    amounts = {line.boq_line_item_id: line.line_amount for line in final_lines}
    assert sum(amounts.values()) == submitted.tender_total  # line amounts foot to the settled total exactly


async def test_lines_immutable_after_submit(rls_session):
    tenant_id, project_id, settlement = await _draft_with_one_resolved_line(rls_session)
    bd_ctx = _ctx(BD, tenant_id=tenant_id, acr="silver")
    await set_rls_context(rls_session, bd_ctx)
    await settlement_service.submit_settlement(rls_session, bd_ctx, settlement.id)

    lead_ctx = _ctx(LEAD, tenant_id=tenant_id, user_id=_MEMBER_USER_ID)
    await set_rls_context(rls_session, lead_ctx)
    with pytest.raises(ConflictError):
        await settlement_service.set_defaults(rls_session, lead_ctx, settlement.id, SettlementDefaultsUpdate(default_markup_pct=99))


# --------------------------------------------------------------------------
# segregation of duties + decide()
# --------------------------------------------------------------------------


async def test_submitter_cannot_decide_own_request_but_a_different_bd_director_can(rls_session):
    tenant_id, project_id, settlement = await _draft_with_one_resolved_line(rls_session)
    submitter_id = uuid.uuid4()
    bd_submitter = _ctx(BD, tenant_id=tenant_id, user_id=submitter_id, acr="silver")
    await set_rls_context(rls_session, bd_submitter)
    await settlement_service.submit_settlement(rls_session, bd_submitter, settlement.id)

    with pytest.raises(ForbiddenError):
        await settlement_service.decide_settlement(rls_session, bd_submitter, settlement.id, approve=True, note=None)

    bd_other = _ctx(BD, tenant_id=tenant_id, user_id=uuid.uuid4(), acr="silver")
    await set_rls_context(rls_session, bd_other)
    decided = await settlement_service.decide_settlement(rls_session, bd_other, settlement.id, approve=True, note="ok")
    assert decided.status == BidSettlementStatus.APPROVED.value
    assert decided.decided_by == bd_other.user_id


async def test_rejected_settlement_allows_a_new_version(rls_session):
    tenant_id, project_id, settlement = await _draft_with_one_resolved_line(rls_session)
    bd_ctx = _ctx(BD, tenant_id=tenant_id, acr="silver")
    await set_rls_context(rls_session, bd_ctx)
    await settlement_service.submit_settlement(rls_session, bd_ctx, settlement.id)

    other_bd = _ctx(BD, tenant_id=tenant_id, acr="silver")
    await set_rls_context(rls_session, other_bd)
    rejected = await settlement_service.decide_settlement(rls_session, other_bd, settlement.id, approve=False, note="too thin")
    assert rejected.status == BidSettlementStatus.REJECTED.value

    lead_ctx = _ctx(LEAD, tenant_id=tenant_id, user_id=_MEMBER_USER_ID)
    await set_rls_context(rls_session, lead_ctx)
    v2 = await settlement_service.build_settlement_draft(rls_session, lead_ctx, project_id)
    assert v2.version_no == 2
    assert v2.is_current is True

    await rls_session.refresh(rejected)
    assert rejected.is_current is False

    # Phase 8e: list_settlements() -- the settlement screen's version/
    # win-loss history browser needs this; no such listing existed
    # anywhere before (only build [creates] and get-by-id [needs an
    # already-known id]).
    listed = await settlement_service.list_settlements(rls_session, project_id)
    assert [s.version_no for s in listed] == [1, 2]
    assert [s.is_current for s in listed] == [False, True]


async def test_list_settlements_invisible_to_non_member(rls_session):
    tenant_id, project_id, settlement = await _draft_with_one_resolved_line(rls_session)

    non_member_ctx = _ctx(ESTIMATOR, tenant_id=tenant_id, user_id=uuid.uuid4())
    await set_rls_context(rls_session, non_member_ctx)
    assert await settlement_service.list_settlements(rls_session, project_id) == []


async def test_save_and_list_scenarios(rls_session):
    tenant_id, project_id, settlement = await _draft_with_one_resolved_line(rls_session)
    estimator_ctx = _ctx(ESTIMATOR, tenant_id=tenant_id, user_id=_MEMBER_USER_ID)
    await set_rls_context(rls_session, estimator_ctx)

    saved = await settlement_service.save_scenario(
        rls_session, estimator_ctx, settlement.id,
        ScenarioCreate(label="Aggressive markup", inputs=SimulateRequest(default_markup_pct=20)),
    )
    assert saved.label == "Aggressive markup"
    assert saved.result["tender_total"] is not None

    scenarios = await settlement_service.list_scenarios(rls_session, settlement.id)
    assert [s.label for s in scenarios] == ["Aggressive markup"]


async def test_delete_scenario(rls_session):
    """Phase 3 gap-fill (docs/ui-qa-brief.md): scenarios had no delete at
    all before -- confirmed no endpoint existed. Same _LINE_ROLES as
    saving one (every one of the 5 business roles), scoped to the
    settlement it was actually saved under."""
    tenant_id, project_id, settlement = await _draft_with_one_resolved_line(rls_session)
    estimator_ctx = _ctx(ESTIMATOR, tenant_id=tenant_id, user_id=_MEMBER_USER_ID)
    await set_rls_context(rls_session, estimator_ctx)
    scenario = await settlement_service.save_scenario(
        rls_session, estimator_ctx, settlement.id,
        ScenarioCreate(label="To be deleted", inputs=SimulateRequest(default_markup_pct=15)),
    )

    await settlement_service.delete_scenario(rls_session, estimator_ctx, settlement.id, scenario.id)

    assert await settlement_service.list_scenarios(rls_session, settlement.id) == []


async def test_delete_scenario_denied_for_a_role_outside_line_roles(rls_session):
    """_LINE_ROLES already covers every one of the 5 business roles, so
    the only real "denied" case is a role that isn't a project-scoped
    business role at all -- platform_admin, per its own narrow scope
    (docs/ui-qa/coverage.md's role glossary)."""
    tenant_id, project_id, settlement = await _draft_with_one_resolved_line(rls_session)
    estimator_ctx = _ctx(ESTIMATOR, tenant_id=tenant_id, user_id=_MEMBER_USER_ID)
    await set_rls_context(rls_session, estimator_ctx)
    scenario = await settlement_service.save_scenario(
        rls_session, estimator_ctx, settlement.id,
        ScenarioCreate(label="Should survive", inputs=SimulateRequest(default_markup_pct=15)),
    )

    admin_ctx = _ctx(frozenset({"platform_admin"}), tenant_id=tenant_id, user_id=uuid.uuid4())
    await set_rls_context(rls_session, admin_ctx)
    with pytest.raises(ForbiddenError):
        await settlement_service.delete_scenario(rls_session, admin_ctx, settlement.id, scenario.id)


async def test_delete_scenario_from_a_different_settlement_404s(rls_session):
    tenant_id, project_id, settlement = await _draft_with_one_resolved_line(rls_session)
    estimator_ctx = _ctx(ESTIMATOR, tenant_id=tenant_id, user_id=_MEMBER_USER_ID)
    await set_rls_context(rls_session, estimator_ctx)
    scenario = await settlement_service.save_scenario(
        rls_session, estimator_ctx, settlement.id,
        ScenarioCreate(label="Belongs elsewhere", inputs=SimulateRequest(default_markup_pct=15)),
    )

    with pytest.raises(NotFoundError):
        await settlement_service.delete_scenario(rls_session, estimator_ctx, uuid.uuid4(), scenario.id)


# --------------------------------------------------------------------------
# approval routing wired end-to-end (unit tests cover the six boundary
# cases exhaustively -- this proves submit() actually uses tender_total/
# margin_on_sell_pct for real, against a real seeded policy).
# --------------------------------------------------------------------------


async def test_large_settlement_routes_to_managing_director_end_to_end(rls_session):
    # _seed_project (via _draft_with_one_resolved_line) already seeded the
    # standard bid_submission policy (AED 2,000,000 / 8%, see
    # _seed_bid_submission_policy) -- this proves submit() actually uses
    # tender_total/margin_on_sell_pct against it for real; the six boundary
    # cases themselves are covered exhaustively at the unit level
    # (tests/unit/test_approval_routing.py).
    tenant_id, project_id, settlement = await _draft_with_one_resolved_line(rls_session, unit_price="5000", qty=1000)

    lead_ctx = _ctx(LEAD, tenant_id=tenant_id, user_id=_MEMBER_USER_ID)
    await set_rls_context(rls_session, lead_ctx)
    await settlement_service.set_defaults(rls_session, lead_ctx, settlement.id, SettlementDefaultsUpdate(default_markup_pct=10))

    bd_ctx = _ctx(BD, tenant_id=tenant_id, acr="silver")
    await set_rls_context(rls_session, bd_ctx)
    submitted = await settlement_service.submit_settlement(rls_session, bd_ctx, settlement.id)
    assert submitted.tender_total > Decimal("2000000")

    from app.models.approvals import ApprovalRequest

    approval_request = (
        await rls_session.execute(select(ApprovalRequest).where(ApprovalRequest.id == submitted.approval_request_id))
    ).scalar_one()
    assert approval_request.amount == submitted.tender_total
    assert approval_request.entity_type == "bid_submission"

    with pytest.raises(ForbiddenError):
        await settlement_service.decide_settlement(rls_session, bd_ctx, settlement.id, approve=True, note=None)

    md_ctx = _ctx(MD, tenant_id=tenant_id, acr="silver")
    await set_rls_context(rls_session, md_ctx)
    decided = await settlement_service.decide_settlement(rls_session, md_ctx, settlement.id, approve=True, note="ok")
    assert decided.status == BidSettlementStatus.APPROVED.value
