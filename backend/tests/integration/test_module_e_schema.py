"""Module E Phase 1: schema readiness -- RLS isolation for every new table,
contracts.settlement_id uniqueness, revision lineage, and the read
endpoints' underlying service functions. No business-logic tests --
this phase adds none (schema and RLS only, no workflows). See
docs/module-e-schema-design.md."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import RequestContext
from app.db.rls import set_rls_context
from app.models.module_e import (
    BoqRevision,
    Contract,
    ContractRevision,
    ExclusionRegisterEntry,
    OutturnCostObservation,
)
from app.models.quotation_ingestion import QuotationExclusionFlag
from app.models.settlement import BidSettlement
from app.services import module_e as module_e_service

pytestmark = pytest.mark.asyncio

_MEMBER_USER_ID = uuid.UUID("00000000-0000-0000-0000-0000000000e7")
_NON_MEMBER_USER_ID = uuid.UUID("00000000-0000-0000-0000-0000000000e8")


def _ctx(roles: frozenset[str], *, tenant_id: uuid.UUID, is_system: bool = False, user_id: uuid.UUID | None = None) -> RequestContext:
    user_id = user_id or uuid.uuid4()
    return RequestContext(tenant_id=tenant_id, user_id=user_id, sub=str(user_id), roles=roles, is_system=is_system)


async def _seed_project_and_settlement(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Returns (tenant_id, project_id, settlement_id). Membership granted
    to _MEMBER_USER_ID only -- lead_estimator (this phase's WRITE_ROLES
    floor) isn't covered by app_can_see_project()'s senior-role bypass."""
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
            {"t": str(tenant_id), "c": f"E7-{uuid.uuid4().hex[:8]}"},
        )
    ).scalar_one()
    await session.execute(
        text("INSERT INTO project_members (project_id, user_id, tenant_id) VALUES (:p, :u, :t)"),
        {"p": str(project_id), "u": str(_MEMBER_USER_ID), "t": str(tenant_id)},
    )
    settlement = BidSettlement(tenant_id=tenant_id, project_id=project_id)
    session.add(settlement)
    await session.flush()
    return tenant_id, project_id, settlement.id


LEAD = frozenset({"lead_estimator"})


# --------------------------------------------------------------------------
# contracts: RLS visibility + settlement_id uniqueness
# --------------------------------------------------------------------------


async def test_contract_visible_to_member_invisible_to_non_member(rls_session):
    tenant_id, project_id, settlement_id = await _seed_project_and_settlement(rls_session)
    sys_ctx = _ctx(frozenset(), tenant_id=tenant_id, is_system=True)
    await set_rls_context(rls_session, sys_ctx)
    contract = Contract(tenant_id=tenant_id, project_id=project_id, settlement_id=settlement_id, status="active")
    rls_session.add(contract)
    await rls_session.flush()

    member_ctx = _ctx(LEAD, tenant_id=tenant_id, user_id=_MEMBER_USER_ID)
    await set_rls_context(rls_session, member_ctx)
    visible = await module_e_service.list_contracts(rls_session, project_id)
    assert [c.id for c in visible] == [contract.id]
    fetched = await module_e_service.get_contract(rls_session, contract.id)
    assert fetched.id == contract.id

    non_member_ctx = _ctx(LEAD, tenant_id=tenant_id, user_id=_NON_MEMBER_USER_ID)
    await set_rls_context(rls_session, non_member_ctx)
    assert await module_e_service.list_contracts(rls_session, project_id) == []
    from app.core.errors import NotFoundError

    with pytest.raises(NotFoundError):
        await module_e_service.get_contract(rls_session, contract.id)


async def test_contract_settlement_id_is_unique(rls_session):
    tenant_id, project_id, settlement_id = await _seed_project_and_settlement(rls_session)
    sys_ctx = _ctx(frozenset(), tenant_id=tenant_id, is_system=True)
    await set_rls_context(rls_session, sys_ctx)
    rls_session.add(Contract(tenant_id=tenant_id, project_id=project_id, settlement_id=settlement_id))
    await rls_session.flush()

    rls_session.add(Contract(tenant_id=tenant_id, project_id=project_id, settlement_id=settlement_id))
    with pytest.raises(IntegrityError):
        await rls_session.flush()


# --------------------------------------------------------------------------
# lineage: revision parent chain
# --------------------------------------------------------------------------


async def test_boq_revision_lineage_resolves(rls_session):
    tenant_id, project_id, _settlement_id = await _seed_project_and_settlement(rls_session)
    sys_ctx = _ctx(frozenset(), tenant_id=tenant_id, is_system=True)
    await set_rls_context(rls_session, sys_ctx)

    rev1 = BoqRevision(tenant_id=tenant_id, project_id=project_id, revision_no=1, reason="Initial tender BOQ")
    rls_session.add(rev1)
    await rls_session.flush()
    rev2 = BoqRevision(tenant_id=tenant_id, project_id=project_id, revision_no=2, parent_revision_id=rev1.id, reason="Client reissue")
    rls_session.add(rev2)
    await rls_session.flush()

    member_ctx = _ctx(LEAD, tenant_id=tenant_id, user_id=_MEMBER_USER_ID)
    await set_rls_context(rls_session, member_ctx)
    revisions = await module_e_service.list_boq_revisions(rls_session, project_id)
    assert [r.revision_no for r in revisions] == [1, 2]
    by_no = {r.revision_no: r for r in revisions}
    assert by_no[2].parent_revision_id == by_no[1].id
    assert by_no[1].parent_revision_id is None


async def test_contract_revision_lineage_and_variation_listing(rls_session):
    tenant_id, project_id, settlement_id = await _seed_project_and_settlement(rls_session)
    sys_ctx = _ctx(frozenset(), tenant_id=tenant_id, is_system=True)
    await set_rls_context(rls_session, sys_ctx)
    contract = Contract(tenant_id=tenant_id, project_id=project_id, settlement_id=settlement_id, status="active")
    rls_session.add(contract)
    await rls_session.flush()

    rev1 = ContractRevision(tenant_id=tenant_id, project_id=project_id, contract_id=contract.id, revision_no=1)
    rls_session.add(rev1)
    await rls_session.flush()
    rev2 = ContractRevision(
        tenant_id=tenant_id, project_id=project_id, contract_id=contract.id, revision_no=2,
        parent_revision_id=rev1.id, reason="Scope variation agreed",
    )
    rls_session.add(rev2)
    await rls_session.flush()

    from app.models.module_e import ContractVariation

    variation = ContractVariation(
        tenant_id=tenant_id, project_id=project_id, contract_id=contract.id, revision_id=rev2.id,
        description="Add 2no additional manholes", delta_amount=15000.00, status="approved",
    )
    rls_session.add(variation)
    await rls_session.flush()

    member_ctx = _ctx(LEAD, tenant_id=tenant_id, user_id=_MEMBER_USER_ID)
    await set_rls_context(rls_session, member_ctx)
    revisions = await module_e_service.list_contract_revisions(rls_session, contract.id)
    assert [r.revision_no for r in revisions] == [1, 2]
    assert revisions[1].parent_revision_id == revisions[0].id

    variations = await module_e_service.list_contract_variations(rls_session, contract.id)
    assert len(variations) == 1
    assert variations[0].revision_id == rev2.id
    assert float(variations[0].delta_amount) == 15000.00


# --------------------------------------------------------------------------
# exclusion register: seeded from a quotation_exclusion_flags row
# --------------------------------------------------------------------------


async def test_exclusion_register_seeded_from_flag_and_status_filter(rls_session):
    tenant_id, project_id, settlement_id = await _seed_project_and_settlement(rls_session)
    sys_ctx = _ctx(frozenset(), tenant_id=tenant_id, is_system=True)
    await set_rls_context(rls_session, sys_ctx)
    contract = Contract(tenant_id=tenant_id, project_id=project_id, settlement_id=settlement_id, status="active")
    rls_session.add(contract)
    await rls_session.flush()

    vendor_id = (
        await rls_session.execute(
            text(
                "INSERT INTO vendors (tenant_id, legal_name, normalized_name, status, primary_email) "
                "VALUES (:t, 'V', 'v', 'active', 'v@example.com') RETURNING id"
            ),
            {"t": str(tenant_id)},
        )
    ).scalar_one()
    package_id = (
        await rls_session.execute(
            text("INSERT INTO procurement_packages (tenant_id, project_id, name, status) VALUES (:t, :p, 'Pkg', 'sent') RETURNING id"),
            {"t": str(tenant_id), "p": str(project_id)},
        )
    ).scalar_one()
    rfq_id = (
        await rls_session.execute(
            text(
                "INSERT INTO rfqs (tenant_id, package_id, project_id, vendor_id, status, reply_token) "
                "VALUES (:t, :pkg, :p, :v, 'sent', :tok) RETURNING id"
            ),
            {"t": str(tenant_id), "pkg": str(package_id), "p": str(project_id), "v": str(vendor_id), "tok": f"tok-{uuid.uuid4().hex}"},
        )
    ).scalar_one()
    quotation_id = (
        await rls_session.execute(
            text(
                "INSERT INTO quotations (tenant_id, rfq_id, vendor_id, package_id, project_id, extraction_method, "
                "version_no, is_current, currency, vat_inclusive, submitted_at, status) "
                "VALUES (:t, :r, :v, :pkg, :p, 'deterministic_xlsx', 1, true, 'AED', true, :now, 'proposed') RETURNING id"
            ),
            {"t": str(tenant_id), "r": str(rfq_id), "v": str(vendor_id), "pkg": str(package_id), "p": str(project_id), "now": datetime.now(UTC)},
        )
    ).scalar_one()
    flag = QuotationExclusionFlag(
        tenant_id=tenant_id, quotation_id=quotation_id, project_id=project_id,
        flag_text="Excludes dewatering", source_quote_text="Excludes dewatering and groundwater control.",
    )
    rls_session.add(flag)
    await rls_session.flush()

    open_entry = ExclusionRegisterEntry(
        tenant_id=tenant_id, project_id=project_id, contract_id=contract.id, source_exclusion_flag_id=flag.id,
        description="Dewatering excluded by vendor -- needs separate provisional sum", status="open",
    )
    resolved_entry = ExclusionRegisterEntry(
        tenant_id=tenant_id, project_id=project_id, contract_id=contract.id,
        description="Manually added scope gap", status="resolved", resolution_note="Covered under variation #1",
    )
    rls_session.add_all([open_entry, resolved_entry])
    await rls_session.flush()

    member_ctx = _ctx(LEAD, tenant_id=tenant_id, user_id=_MEMBER_USER_ID)
    await set_rls_context(rls_session, member_ctx)
    all_entries = await module_e_service.list_exclusion_register(rls_session, project_id)
    assert {e.id for e in all_entries} == {open_entry.id, resolved_entry.id}

    open_only = await module_e_service.list_exclusion_register(rls_session, project_id, status="open")
    assert [e.id for e in open_only] == [open_entry.id]
    assert open_only[0].source_exclusion_flag_id == flag.id


# --------------------------------------------------------------------------
# outturn cost observations
# --------------------------------------------------------------------------


async def test_outturn_cost_observations_list(rls_session):
    tenant_id, project_id, settlement_id = await _seed_project_and_settlement(rls_session)
    sys_ctx = _ctx(frozenset(), tenant_id=tenant_id, is_system=True)
    await set_rls_context(rls_session, sys_ctx)
    contract = Contract(tenant_id=tenant_id, project_id=project_id, settlement_id=settlement_id, status="active")
    rls_session.add(contract)
    await rls_session.flush()

    observation = OutturnCostObservation(
        tenant_id=tenant_id, project_id=project_id, contract_id=contract.id,
        observed_unit_cost=52.75, currency="AED", observed_at=date(2026, 3, 1),
        source_note="Final account, item 1.0",
    )
    rls_session.add(observation)
    await rls_session.flush()

    member_ctx = _ctx(LEAD, tenant_id=tenant_id, user_id=_MEMBER_USER_ID)
    await set_rls_context(rls_session, member_ctx)
    observations = await module_e_service.list_outturn_cost_observations(rls_session, project_id)
    assert len(observations) == 1
    assert float(observations[0].observed_unit_cost) == 52.75
    assert observations[0].written_back_rate_id is None  # no write-back workflow exists yet (this phase's own scope)
