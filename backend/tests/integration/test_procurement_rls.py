from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy import text

from app.core.context import RequestContext
from app.core.errors import ForbiddenError, ValidationAppError
from app.db.rls import set_rls_context
from app.models.vendors import VendorContact, VendorTrade
from app.schemas.boq import BoqLineItemCreate
from app.schemas.prequal import PrequalificationDecision
from app.schemas.procurement import ProcurementPackageCreate, RfqCreateRequest
from app.schemas.taxonomy import TradeNodeCreate
from app.schemas.vendors import VendorCreate
from app.services import boq as boq_service
from app.services import prequal as prequal_service
from app.services import procurement as procurement_service
from app.services import taxonomy as taxonomy_service
from app.services import vendors as vendors_service

pytestmark = pytest.mark.asyncio

TENANT = uuid.UUID("8f14e45f-ceea-4e97-8d0c-3d3b3f3c1a00")


def _ctx(roles: frozenset[str], *, is_system: bool = False, user_id: uuid.UUID | None = None, acr: str | None = None) -> RequestContext:
    user_id = user_id or uuid.uuid4()
    return RequestContext(tenant_id=TENANT, user_id=user_id, sub=str(user_id), roles=roles, is_system=is_system, acr=acr)


async def _seed_project_with_member(session, member_user_id: uuid.UUID) -> uuid.UUID:
    system_ctx = _ctx(frozenset(), is_system=True)
    await set_rls_context(session, system_ctx)
    project_id = (
        await session.execute(
            text("INSERT INTO projects (tenant_id, code, name) VALUES (:t, :c, 'A') RETURNING id"),
            {"t": str(TENANT), "c": f"PROC-{uuid.uuid4().hex[:8]}"},
        )
    ).scalar_one()
    await session.execute(
        text("INSERT INTO project_members (project_id, user_id, tenant_id, project_role) VALUES (:p, :u, :t, 'estimator')"),
        {"p": project_id, "u": str(member_user_id), "t": str(TENANT)},
    )
    return project_id


async def _seed_trade(session) -> uuid.UUID:
    lead_ctx = _ctx(frozenset({"lead_estimator"}))
    await set_rls_context(session, lead_ctx)
    node = await taxonomy_service.create_node(
        session, lead_ctx, TradeNodeCreate(code=f"EW-{uuid.uuid4().hex[:6]}", name="Earthworks")
    )
    return node.id


async def _seed_vendor(session, trade_node_id: uuid.UUID, *, prequalified: bool) -> uuid.UUID:
    lead_ctx = _ctx(frozenset({"lead_estimator"}))
    await set_rls_context(session, lead_ctx)
    vendor = await vendors_service.create_vendor(
        session, lead_ctx, VendorCreate(legal_name=f"Vendor {uuid.uuid4().hex[:6]}", primary_email="quotes@vendor.example")
    )
    # create_vendor leaves status="draft" (server_default) -- match_vendors
    # (app/services/procurement.py) only considers VendorStatus.ACTIVE.
    vendor.status = "active"
    session.add(VendorTrade(tenant_id=TENANT, vendor_id=vendor.id, trade_node_id=trade_node_id))
    session.add(
        VendorContact(tenant_id=TENANT, vendor_id=vendor.id, name="Primary", email="quotes@vendor.example", is_primary=True)
    )
    await session.flush()
    if prequalified:
        await prequal_service.decide_prequalification(
            session, lead_ctx, vendor.id,
            PrequalificationDecision(status="approved", effective_from=date(2020, 1, 1), scope_trade_node_id=trade_node_id),
        )
    return vendor.id


async def _seed_package_with_item(
    session, project_id: uuid.UUID, trade_node_id: uuid.UUID | None, *, member_user_id: uuid.UUID
) -> uuid.UUID:
    # Must be the same user_id added to project_members by
    # _seed_project_with_member -- lead_estimator does not bypass project
    # membership the way procurement_head/bd_director/managing_director do
    # (app.services.projects._PROJECT_VISIBLE_WITHOUT_MEMBERSHIP_ROLES).
    lead_ctx = _ctx(frozenset({"lead_estimator"}), user_id=member_user_id)
    await set_rls_context(session, lead_ctx)
    package = await procurement_service.create_package(
        session, lead_ctx, project_id, ProcurementPackageCreate(name="Earthworks Package A", trade_node_id=trade_node_id)
    )
    item = await boq_service.create_line_item(
        session, lead_ctx, project_id, BoqLineItemCreate(item_no="1.0", description="Excavation", uom="m3", boq_quantity=100.0)
    )
    await procurement_service.add_items(session, lead_ctx, package.id, [item.id])
    return package.id


# --------------------------------------------------------------------------
# package/item/RFQ drafting: lead_estimator+ only, estimator can read
# --------------------------------------------------------------------------


async def test_estimator_cannot_create_package_lead_estimator_can(rls_session):
    user_id = uuid.uuid4()
    project_id = await _seed_project_with_member(rls_session, user_id)

    estimator_ctx = _ctx(frozenset({"estimator"}), user_id=user_id)
    await set_rls_context(rls_session, estimator_ctx)
    with pytest.raises(Exception, match=r"(?i)row-level security"):
        async with rls_session.begin_nested():
            await procurement_service.create_package(
                rls_session, estimator_ctx, project_id, ProcurementPackageCreate(name="Should fail")
            )

    lead_ctx = _ctx(frozenset({"lead_estimator"}), user_id=user_id)
    await set_rls_context(rls_session, lead_ctx)
    package = await procurement_service.create_package(rls_session, lead_ctx, project_id, ProcurementPackageCreate(name="OK"))
    assert package.name == "OK"


async def test_estimator_can_view_package_and_rfqs_but_not_draft_one(rls_session):
    user_id = uuid.uuid4()
    project_id = await _seed_project_with_member(rls_session, user_id)
    trade_id = await _seed_trade(rls_session)
    vendor_id = await _seed_vendor(rls_session, trade_id, prequalified=True)
    package_id = await _seed_package_with_item(rls_session, project_id, trade_id, member_user_id=user_id)

    estimator_ctx = _ctx(frozenset({"estimator"}), user_id=user_id)
    await set_rls_context(rls_session, estimator_ctx)
    # estimator+ can view (SRS change #8)
    seen = await procurement_service.get_package(rls_session, package_id)
    assert seen.id == package_id
    assert await procurement_service.list_rfqs(rls_session, package_id) == []

    with pytest.raises(Exception, match=r"(?i)row-level security"):
        async with rls_session.begin_nested():
            await procurement_service.create_rfqs(
                rls_session, estimator_ctx, package_id, RfqCreateRequest(vendor_ids=[vendor_id])
            )


# --------------------------------------------------------------------------
# vendor matching: trade + active prequalification (SRS change #6)
# --------------------------------------------------------------------------


async def test_vendor_matching_excludes_expired_or_missing_prequalification(rls_session):
    user_id = uuid.uuid4()
    project_id = await _seed_project_with_member(rls_session, user_id)
    trade_id = await _seed_trade(rls_session)
    qualified_id = await _seed_vendor(rls_session, trade_id, prequalified=True)
    unqualified_id = await _seed_vendor(rls_session, trade_id, prequalified=False)
    package_id = await _seed_package_with_item(rls_session, project_id, trade_id, member_user_id=user_id)

    # estimator+ (lowest allowed role) can read the matched-vendor list --
    # it is not gated by _STRUCTURE_ROLES.
    estimator_ctx = _ctx(frozenset({"estimator"}), user_id=user_id)
    await set_rls_context(rls_session, estimator_ctx)
    matches = {m.vendor_id: m for m in await procurement_service.match_vendors(rls_session, package_id)}

    assert matches[qualified_id].eligible is True
    assert matches[qualified_id].ineligible_reason is None
    assert matches[unqualified_id].eligible is False
    assert matches[unqualified_id].ineligible_reason


async def test_override_requires_procurement_head_and_a_reason(rls_session):
    user_id = uuid.uuid4()
    project_id = await _seed_project_with_member(rls_session, user_id)
    trade_id = await _seed_trade(rls_session)
    unqualified_id = await _seed_vendor(rls_session, trade_id, prequalified=False)
    package_id = await _seed_package_with_item(rls_session, project_id, trade_id, member_user_id=user_id)

    lead_ctx = _ctx(frozenset({"lead_estimator"}), user_id=user_id)
    await set_rls_context(rls_session, lead_ctx)

    # no override_reason at all -> rejected outright
    with pytest.raises(ValidationAppError):
        await procurement_service.create_rfqs(rls_session, lead_ctx, package_id, RfqCreateRequest(vendor_ids=[unqualified_id]))

    # override_reason given, but lead_estimator is not senior enough to use it
    with pytest.raises(ForbiddenError):
        await procurement_service.create_rfqs(
            rls_session, lead_ctx, package_id,
            RfqCreateRequest(vendor_ids=[unqualified_id], override_reason="client explicitly requested this vendor"),
        )

    # procurement_head can override, and the reason is captured on the row
    ph_ctx = _ctx(frozenset({"procurement_head"}))
    await set_rls_context(rls_session, ph_ctx)
    [rfq] = await procurement_service.create_rfqs(
        rls_session, ph_ctx, package_id,
        RfqCreateRequest(vendor_ids=[unqualified_id], override_reason="client explicitly requested this vendor"),
    )
    assert rfq.is_override is True
    assert rfq.override_reason == "client explicitly requested this vendor"
    assert rfq.rfq_ref and rfq.rfq_ref.startswith("RFQ-")


async def test_vendor_matching_requires_a_trade_node_on_the_package(rls_session):
    user_id = uuid.uuid4()
    project_id = await _seed_project_with_member(rls_session, user_id)
    package_id = await _seed_package_with_item(rls_session, project_id, None, member_user_id=user_id)

    lead_ctx = _ctx(frozenset({"lead_estimator"}), user_id=user_id)
    await set_rls_context(rls_session, lead_ctx)
    with pytest.raises(ValidationAppError):
        await procurement_service.match_vendors(rls_session, package_id)


async def test_cannot_add_a_boq_item_from_a_different_project(rls_session):
    user_id = uuid.uuid4()
    project_a = await _seed_project_with_member(rls_session, user_id)
    project_b = await _seed_project_with_member(rls_session, uuid.uuid4())

    lead_ctx = _ctx(frozenset({"lead_estimator"}), user_id=user_id)
    await set_rls_context(rls_session, lead_ctx)
    package = await procurement_service.create_package(rls_session, lead_ctx, project_a, ProcurementPackageCreate(name="A"))

    system_ctx = _ctx(frozenset(), is_system=True)
    await set_rls_context(rls_session, system_ctx)
    other_item = await boq_service.create_line_item(
        rls_session, system_ctx, project_b,
        BoqLineItemCreate(item_no="9.0", description="In project B", uom="m", boq_quantity=1.0),
    )

    await set_rls_context(rls_session, lead_ctx)
    with pytest.raises(ValidationAppError):
        await procurement_service.add_items(rls_session, lead_ctx, package.id, [other_item.id])
