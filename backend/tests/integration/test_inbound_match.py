"""Module C2 requirement #1 and change #5: sender/RFQ matching for one
polled inbound email. See app/procurement/inbound_match.py."""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.context import RequestContext
from app.core.enums import InboundEmailMatchStatus, RfqStatus
from app.db.rls import set_rls_context
from app.models.vendors import VendorContact, VendorTrade
from app.procurement.email_auth import AuthResults
from app.procurement.inbound_address import build_reply_address
from app.procurement.inbound_match import match_inbound_email
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

_PASS = AuthResults(spf="pass", dkim="pass", dmarc="pass")


def _settings() -> Settings:
    return Settings(
        APP_DATABASE_URL="postgresql://x/y", MIGRATOR_DATABASE_URL="postgresql://x/y",
        S3_ENDPOINT="http://s3.invalid", VLLM_API_BASE="http://vllm.invalid/v1",
        EMAIL_REPLY_TO_LOCAL_PART="rfq", EMAIL_REPLY_TO_DOMAIN="installtec.local",
    )


def _ctx(roles: frozenset[str], *, tenant_id: uuid.UUID, is_system: bool = False, user_id: uuid.UUID | None = None) -> RequestContext:
    user_id = user_id or uuid.uuid4()
    return RequestContext(tenant_id=tenant_id, user_id=user_id, sub=str(user_id), roles=roles, is_system=is_system)


async def _seed_tenant(session: AsyncSession, *, slug: str) -> uuid.UUID:
    tenant_id = uuid.uuid4()
    await session.execute(
        text("INSERT INTO tenants (id, slug, name) VALUES (:id, :slug, :name)"),
        {"id": str(tenant_id), "slug": slug, "name": f"Tenant {slug}"},
    )
    return tenant_id


async def _seed_open_rfq(session: AsyncSession, tenant_id: uuid.UUID, *, vendor_email: str, vendor_email_domain: str | None) -> tuple:
    """Returns (rfq, vendor). RFQ status is SENT (open)."""
    member_user_id = uuid.uuid4()
    system_ctx = _ctx(frozenset(), tenant_id=tenant_id, is_system=True)
    await set_rls_context(session, system_ctx)
    project_id = (
        await session.execute(
            text("INSERT INTO projects (tenant_id, code, name) VALUES (:t, :c, 'A') RETURNING id"),
            {"t": str(tenant_id), "c": f"C2-{uuid.uuid4().hex[:8]}"},
        )
    ).scalar_one()
    await session.execute(
        text("INSERT INTO project_members (project_id, user_id, tenant_id, project_role) VALUES (:p, :u, :t, 'estimator')"),
        {"p": project_id, "u": str(member_user_id), "t": str(tenant_id)},
    )

    lead_ctx = _ctx(frozenset({"lead_estimator"}), tenant_id=tenant_id, user_id=member_user_id)
    await set_rls_context(session, lead_ctx)
    trade = await taxonomy_service.create_node(session, lead_ctx, TradeNodeCreate(code=f"EW-{uuid.uuid4().hex[:6]}", name="Earthworks"))
    vendor = await vendors_service.create_vendor(
        session, lead_ctx, VendorCreate(legal_name=f"Vendor {uuid.uuid4().hex[:6]}", primary_email=vendor_email)
    )
    vendor.status = "active"
    if vendor_email_domain:
        vendor.email_domain = vendor_email_domain
    session.add(VendorTrade(tenant_id=tenant_id, vendor_id=vendor.id, trade_node_id=trade.id))
    session.add(VendorContact(tenant_id=tenant_id, vendor_id=vendor.id, name="Primary", email=vendor_email, is_primary=True))
    await session.flush()
    await prequal_service.decide_prequalification(
        session, lead_ctx, vendor.id,
        PrequalificationDecision(status="approved", effective_from=date(2020, 1, 1), scope_trade_node_id=trade.id),
    )
    package = await procurement_service.create_package(
        session, lead_ctx, project_id, ProcurementPackageCreate(name="Earthworks A", trade_node_id=trade.id)
    )
    item = await boq_service.create_line_item(
        session, lead_ctx, project_id, BoqLineItemCreate(item_no="1.0", description="Excavation", uom="m3", boq_quantity=100.0)
    )
    await procurement_service.add_items(session, lead_ctx, package.id, [item.id])
    [rfq] = await procurement_service.create_rfqs(session, lead_ctx, package.id, RfqCreateRequest(vendor_ids=[vendor.id]))
    rfq.status = RfqStatus.SENT.value
    await session.flush()
    return rfq, vendor


async def test_matched_with_corporate_domain_match(rls_session):
    tenant_id = await _seed_tenant(rls_session, slug=f"acme-{uuid.uuid4().hex[:8]}")
    rfq, vendor = await _seed_open_rfq(rls_session, tenant_id, vendor_email="quotes@vendor.example", vendor_email_domain="vendor.example")
    tenant = (await rls_session.execute(text("SELECT slug FROM tenants WHERE id = :i"), {"i": str(tenant_id)})).scalar_one()

    to_address = build_reply_address(tenant_slug=tenant, reply_token=rfq.reply_token, settings=_settings())
    outcome = await match_inbound_email(
        rls_session, from_address="quotes@vendor.example", to_address=to_address, auth_results=_PASS, settings=_settings()
    )
    assert outcome.match_status == InboundEmailMatchStatus.MATCHED.value
    assert not outcome.needs_review
    assert outcome.tenant_id == tenant_id
    assert outcome.rfq_id == rfq.id


async def test_unknown_tenant_slug_is_quarantined(rls_session):
    outcome = await match_inbound_email(
        rls_session, from_address="quotes@vendor.example",
        to_address=build_reply_address(tenant_slug="no-such-tenant", reply_token="whatever", settings=_settings()),
        auth_results=_PASS, settings=_settings(),
    )
    assert outcome.match_status == InboundEmailMatchStatus.QUARANTINED_UNKNOWN_TENANT.value
    assert outcome.tenant_id is None
    assert outcome.needs_review


async def test_malformed_recipient_address_is_quarantined(rls_session):
    outcome = await match_inbound_email(
        rls_session, from_address="quotes@vendor.example", to_address="not-our-format@somewhere.else",
        auth_results=_PASS, settings=_settings(),
    )
    assert outcome.match_status == InboundEmailMatchStatus.QUARANTINED_UNKNOWN_TENANT.value


async def test_unknown_reply_token_within_a_known_tenant(rls_session):
    tenant_id = await _seed_tenant(rls_session, slug=f"acme-{uuid.uuid4().hex[:8]}")
    tenant = (await rls_session.execute(text("SELECT slug FROM tenants WHERE id = :i"), {"i": str(tenant_id)})).scalar_one()

    outcome = await match_inbound_email(
        rls_session, from_address="quotes@vendor.example",
        to_address=build_reply_address(tenant_slug=tenant, reply_token="stale-token", settings=_settings()),
        auth_results=_PASS, settings=_settings(),
    )
    assert outcome.match_status == InboundEmailMatchStatus.QUARANTINED_NO_TOKEN.value
    assert outcome.tenant_id == tenant_id
    assert outcome.needs_review


async def test_reply_token_matches_a_closed_rfq(rls_session):
    tenant_id = await _seed_tenant(rls_session, slug=f"acme-{uuid.uuid4().hex[:8]}")
    rfq, _vendor = await _seed_open_rfq(rls_session, tenant_id, vendor_email="quotes@vendor.example", vendor_email_domain="vendor.example")
    rfq.status = RfqStatus.DRAFT.value
    await rls_session.flush()
    tenant = (await rls_session.execute(text("SELECT slug FROM tenants WHERE id = :i"), {"i": str(tenant_id)})).scalar_one()

    outcome = await match_inbound_email(
        rls_session, from_address="quotes@vendor.example",
        to_address=build_reply_address(tenant_slug=tenant, reply_token=rfq.reply_token, settings=_settings()),
        auth_results=_PASS, settings=_settings(),
    )
    assert outcome.match_status == InboundEmailMatchStatus.QUARANTINED_TOKEN_CLOSED.value


async def test_corporate_domain_mismatch_is_flagged_not_rejected(rls_session):
    tenant_id = await _seed_tenant(rls_session, slug=f"acme-{uuid.uuid4().hex[:8]}")
    rfq, _vendor = await _seed_open_rfq(rls_session, tenant_id, vendor_email="quotes@vendor.example", vendor_email_domain="vendor.example")
    tenant = (await rls_session.execute(text("SELECT slug FROM tenants WHERE id = :i"), {"i": str(tenant_id)})).scalar_one()

    outcome = await match_inbound_email(
        rls_session, from_address="quotes@totally-different-domain.example",
        to_address=build_reply_address(tenant_slug=tenant, reply_token=rfq.reply_token, settings=_settings()),
        auth_results=_PASS, settings=_settings(),
    )
    assert outcome.match_status == InboundEmailMatchStatus.MATCHED.value
    assert outcome.needs_review
    assert "sender_domain_does_not_match_vendor" in outcome.review_reasons


async def test_free_mail_sender_must_match_exact_contact_not_just_domain(rls_session):
    tenant_id = await _seed_tenant(rls_session, slug=f"acme-{uuid.uuid4().hex[:8]}")
    rfq, _vendor = await _seed_open_rfq(rls_session, tenant_id, vendor_email="realvendor@gmail.com", vendor_email_domain=None)
    tenant = (await rls_session.execute(text("SELECT slug FROM tenants WHERE id = :i"), {"i": str(tenant_id)})).scalar_one()

    # Same free-mail domain, but NOT the exact known contact address.
    outcome = await match_inbound_email(
        rls_session, from_address="impersonator@gmail.com",
        to_address=build_reply_address(tenant_slug=tenant, reply_token=rfq.reply_token, settings=_settings()),
        auth_results=_PASS, settings=_settings(),
    )
    assert outcome.match_status == InboundEmailMatchStatus.MATCHED.value
    assert outcome.needs_review
    assert "free_mail_sender_not_an_exact_known_contact" in outcome.review_reasons

    # The exact known contact address on the same free-mail domain passes.
    outcome_ok = await match_inbound_email(
        rls_session, from_address="realvendor@gmail.com",
        to_address=build_reply_address(tenant_slug=tenant, reply_token=rfq.reply_token, settings=_settings()),
        auth_results=_PASS, settings=_settings(),
    )
    assert not outcome_ok.needs_review


async def test_spf_dkim_dmarc_failure_is_flagged(rls_session):
    tenant_id = await _seed_tenant(rls_session, slug=f"acme-{uuid.uuid4().hex[:8]}")
    rfq, _vendor = await _seed_open_rfq(rls_session, tenant_id, vendor_email="quotes@vendor.example", vendor_email_domain="vendor.example")
    tenant = (await rls_session.execute(text("SELECT slug FROM tenants WHERE id = :i"), {"i": str(tenant_id)})).scalar_one()

    failing_auth = AuthResults(spf="fail", dkim="pass", dmarc="pass")
    outcome = await match_inbound_email(
        rls_session, from_address="quotes@vendor.example",
        to_address=build_reply_address(tenant_slug=tenant, reply_token=rfq.reply_token, settings=_settings()),
        auth_results=failing_auth, settings=_settings(),
    )
    assert outcome.match_status == InboundEmailMatchStatus.MATCHED.value
    assert outcome.needs_review
    assert "spf_dkim_or_dmarc_failed" in outcome.review_reasons
