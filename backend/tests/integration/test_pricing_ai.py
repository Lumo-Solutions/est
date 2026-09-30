"""AI pricing assistant against Postgres (RLS on): real candidates (accepted quote, cost-library rate as of the
tender date, historical median), flags in code, AI vs rules choice, decisions applied through the existing
settlement service (rates stay authoritative), bulk accept, no-source lines, and advisory markup computed by
the existing engine. Lowest allowed / denied roles are covered at the HTTP layer in tests/api."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select, text

from app.ai.errors import AIDisabledForTenant
from app.ai.gateway import AIGateway
from app.ai.providers.mock import MockProvider, clear_mock_handlers, register_mock_handler
from app.ai.store import MemoryStore
from app.core.config import Settings
from app.core.errors import ConflictError, ValidationAppError
from app.db.rls import set_rls_context
from app.models.pricing_ai import SettlementAiProposal
from app.models.settlement import BidSettlement, BidSettlementLineItem
from app.schemas.boq import BoqLineItemCreate
from app.schemas.costlib import CostItemCreate, CostRateComponentIn, RecordRateRequest
from app.services import boq as boq_service
from app.services import costlib as costlib_service
from app.services import pricing_ai as svc
from app.services import settlement as settlement_service
from tests.integration.test_bid_settlement import (
    LEAD,
    _MEMBER_USER_ID,
    _add_boq_item,
    _ctx,
    _seed_accepted_quotation_line,
    _seed_project,
    _system_ctx,
)

pytestmark = pytest.mark.asyncio

SETTINGS = Settings(APP_DATABASE_URL="postgresql://x/y", MIGRATOR_DATABASE_URL="postgresql://x/y", S3_ENDPOINT="http://s3",
                    VLLM_API_BASE="http://vllm.internal/v1", AI_PROVIDER="mock", AI_STALE_RATE_MONTHS=12)
TENDER = date(2026, 6, 1)


@pytest.fixture(autouse=True)
def _clean():
    yield
    clear_mock_handlers()


def _gateway(ctx, *, external_allowed: bool | None = None) -> tuple[AIGateway, MockProvider]:
    p = MockProvider()
    if external_allowed is not None:
        p.external = True
    return AIGateway(settings=SETTINGS, store=MemoryStore(external_allowed=bool(external_allowed)), provider=p, ctx=ctx), p


async def _noprogress(*_a):
    return None


async def _lib_item(session, ctx, code, desc, uom, rate, valid_from):
    item = await costlib_service.create_cost_item(session, ctx, CostItemCreate(code=code, description=desc, uom=uom))
    await costlib_service.record_rate(
        session, ctx, item.id,
        RecordRateRequest(valid_from=valid_from, components=[CostRateComponentIn(component_type="material", description=desc, unit_cost=rate)]),
    )
    return item


async def _scenario(session):
    """A: quote + library (+ history)   B: stale library only   C: nothing   D: two competing quotes."""
    tenant_id, project_id = await _seed_project(session)
    sys_ctx = await _system_ctx(session, tenant_id)
    await session.execute(text("UPDATE projects SET submission_due_at=:d WHERE id=:p"), {"d": datetime(2026, 6, 1, tzinfo=timezone.utc), "p": str(project_id)})
    a = await boq_service.create_line_item(session, sys_ctx, project_id, BoqLineItemCreate(item_no="1.1", description="Supply and lay 300mm uPVC SN8 sewer pipe", uom="m", boq_quantity=245))
    b = await boq_service.create_line_item(session, sys_ctx, project_id, BoqLineItemCreate(item_no="1.2", description="Precast concrete manhole 1200mm internal diameter", uom="nr", boq_quantity=12))
    c = await boq_service.create_line_item(session, sys_ctx, project_id, BoqLineItemCreate(item_no="1.3", description="Street lighting column 8m complete with bracket", uom="nr", boq_quantity=8))
    d = await boq_service.create_line_item(session, sys_ctx, project_id, BoqLineItemCreate(item_no="1.4", description="Excavate in all types of soil and dispose off site", uom="m3", boq_quantity=1000))
    await _seed_accepted_quotation_line(session, sys_ctx, project_id=project_id, boq_item=a, unit_price="95.00")
    await _seed_accepted_quotation_line(session, sys_ctx, project_id=project_id, boq_item=d, unit_price="12.00")
    await _seed_accepted_quotation_line(session, sys_ctx, project_id=project_id, boq_item=d, unit_price="10.00")
    await _lib_item(session, sys_ctx, "PIPE-300", "uPVC SN8 sewer pipe 300mm supply and lay", "m", 92.0, date(2026, 3, 1))
    await _lib_item(session, sys_ctx, "MH-1200", "Precast concrete manhole 1200mm internal diameter", "nr", 4100.0, date(2023, 1, 1))  # stale
    # history: a past project's SUBMITTED settlement priced the pipe at 90 and the excavation at 11
    other = (await session.execute(text("INSERT INTO projects (tenant_id, code, name) VALUES (:t, :c, 'Past') RETURNING id"), {"t": str(tenant_id), "c": f"PAST-{uuid.uuid4().hex[:6]}"})).scalar_one()
    # history is read under the caller's RLS: a lead only sees past projects they belong to
    await session.execute(text("INSERT INTO project_members (project_id, user_id, tenant_id) VALUES (:p, :u, :t)"), {"p": str(other), "u": str(_MEMBER_USER_ID), "t": str(tenant_id)})
    past = BidSettlement(tenant_id=tenant_id, project_id=other, version_no=1, is_current=True, status="submitted", margin_on_sell_pct=Decimal("7.5"),
                         outcome="won", outcome_our_price=Decimal("1000000"), outcome_winning_price=Decimal("1000000"))
    session.add(past)
    await session.flush()
    for no, desc, uom, qty, rate in [("9.1", "Supply and lay 300mm uPVC SN8 sewer pipe", "m", 100, "90.00"), ("9.2", "Excavate in all types of soil and dispose off site", "m3", 500, "11.00")]:
        pb = await boq_service.create_line_item(session, sys_ctx, other, BoqLineItemCreate(item_no=no, description=desc, uom=uom, boq_quantity=qty))
        session.add(BidSettlementLineItem(tenant_id=tenant_id, settlement_id=past.id, boq_line_item_id=pb.id, project_id=other, quantity=qty, quantity_at_build=qty,
                                          direct_unit_cost=Decimal(rate)))
    await session.flush()
    lead = _ctx(LEAD, tenant_id=tenant_id, user_id=_MEMBER_USER_ID)
    await set_rls_context(session, lead)
    settlement = await settlement_service.build_settlement_draft(session, lead, project_id)
    return {"tenant": tenant_id, "project": project_id, "lead": lead, "settlement": settlement, "items": {"A": a, "B": b, "C": c, "D": d}}


def _ai_choose(req):
    """Picks: A -> its quote, B -> its (stale) library rate, D -> the cheaper quote. Adds junk the gateway must strip."""
    out = []
    for block in req.user.split("<<<LINE id=")[1:]:
        lid = block.split("\n", 1)[0].strip()
        cands = []
        for line in block.splitlines():
            if line.startswith("- ref="):
                ref = line[len("- ref="):].split(" |")[0]
                rate = float(line.split("|")[3].strip().split()[0].replace(",", ""))
                cands.append((ref, line, rate))
        if not cands:
            continue
        quotes = [c for c in cands if c[0].startswith("q:")]
        pick = min(quotes, key=lambda c: c[2]) if quotes else cands[0]
        out.append({"id": lid, "overall": "", "ranked": [
            {"ref": r, "score": 0.95 if r == pick[0] else 0.4, "selected": r == pick[0], "rationale": "scope matches" if r == pick[0] else "different scope", "rate": 1.0}
            for r, _l, _rt in cands]})
    return {"lines": out}


async def _propose(session, sc, *, use_ai=True, gateway=None):
    run = await svc.create_run(session, sc["lead"], sc["settlement"].id, kind="costs", use_ai=use_ai)
    gw = gateway or _gateway(sc["lead"])[0]
    await svc.run_cost_proposals(session, sc["lead"], run.id, _noprogress, gateway=gw)
    return run


async def _by_item(session, sc):
    rows, _ = await svc.list_proposals(session, sc["settlement"].id, limit=100)
    return {sc_item: next(p for p in rows if p.boq_line_item_id == it.id) for sc_item, it in sc["items"].items()}


async def test_candidates_flags_and_ai_choice_use_real_sources_only(rls_session):
    sc = await _scenario(rls_session)
    register_mock_handler("cost_choose", _ai_choose)
    run = await _propose(rls_session, sc)
    await rls_session.refresh(run)
    assert run.status == "ready" or run.progress_done == run.progress_total
    p = await _by_item(rls_session, sc)

    a = p["A"]
    assert a.source == "ai" and a.chosen["ref"].startswith("q:") and Decimal(a.chosen["rate"]) == Decimal("95.0000")
    kinds = {c["type"] for c in a.candidates}
    assert kinds == {"quote", "library", "historical"}
    hist = next(c for c in a.candidates if c["type"] == "historical")
    assert Decimal(hist["rate"]) == Decimal("90.0000") and hist["samples"] == 1
    assert a.status == "proposed" and float(a.confidence) >= 0.85 and "stale_rate" not in a.flags

    b = p["B"]
    assert b.chosen["type"] == "library" and "stale_rate" in b.flags and float(b.confidence) < 0.85  # blocked -> low confidence

    c = p["C"]
    assert c.chosen is None and c.source == "none" and "No cost source" in c.rationale and float(c.confidence) == 0.0

    d = p["D"]
    assert Decimal(d.chosen["rate"]) == Decimal("10.0000") and d.source == "ai"   # the cheaper of two accepted quotes
    assert any(x["type"] == "historical" for x in d.candidates)

    run_row = await svc.get_run(rls_session, run.id)
    assert run_row.counts["no_source"] == 1 and run_row.counts["with_source"] == 3 and run_row.counts["blocked"] == 1
    assert any("no cost source" in w.lower() for w in run_row.warnings)


async def test_accept_applies_through_set_line_cost_and_rates_stay_authoritative(rls_session):
    sc = await _scenario(rls_session)
    register_mock_handler("cost_choose", _ai_choose)
    await _propose(rls_session, sc)
    p = await _by_item(rls_session, sc)
    # D was left unresolved by build_settlement_draft (two competing accepted quotes): accepting the AI pick resolves it
    line_d = (await rls_session.execute(select(BidSettlementLineItem).where(BidSettlementLineItem.boq_line_item_id == sc["items"]["D"].id))).scalar_one()
    assert line_d.direct_unit_cost is None
    decided = await svc.decide(rls_session, sc["lead"], p["D"].id, action="accept")
    assert decided.status == "accepted" and decided.decided_by == _MEMBER_USER_ID and decided.applied["cost_source"] == "quotation_line"
    await rls_session.refresh(line_d)
    assert line_d.direct_unit_cost == Decimal("10.0000") and line_d.cost_source == "quotation_line" and "AI proposal" in (line_d.source_note or "")
    with pytest.raises(ConflictError):
        await svc.decide(rls_session, sc["lead"], p["D"].id, action="accept")  # decided once

    # library rate: applied as cost_library_rate with the tender date
    line_b = (await rls_session.execute(select(BidSettlementLineItem).where(BidSettlementLineItem.boq_line_item_id == sc["items"]["B"].id))).scalar_one()
    await svc.decide(rls_session, sc["lead"], p["B"].id, action="accept")
    await rls_session.refresh(line_b)
    assert line_b.cost_source == "cost_library_rate" and line_b.direct_unit_cost == Decimal("4100.0000") and line_b.source_rate_as_of_date == TENDER


async def test_choose_another_candidate_manual_override_reject_and_no_source(rls_session):
    sc = await _scenario(rls_session)
    register_mock_handler("cost_choose", _ai_choose)
    await _propose(rls_session, sc)
    p = await _by_item(rls_session, sc)
    lib_ref = next(c["ref"] for c in p["A"].candidates if c["type"] == "library")
    hist_ref = next(c["ref"] for c in p["A"].candidates if c["type"] == "historical")
    chosen = await svc.decide(rls_session, sc["lead"], p["A"].id, action="choose", candidate_ref=lib_ref, note="library is our standard")
    assert chosen.status == "overridden" and chosen.applied["cost_source"] == "cost_library_rate"
    line_a = (await rls_session.execute(select(BidSettlementLineItem).where(BidSettlementLineItem.boq_line_item_id == sc["items"]["A"].id))).scalar_one()
    await rls_session.refresh(line_a)
    assert line_a.direct_unit_cost == Decimal("92.0000")

    # historical median can be chosen by a person; it is recorded as a manual cost with an honest note
    p2 = await _by_item(rls_session, sc)
    run2 = await _propose(rls_session, sc)  # a fresh run supersedes the open proposals
    p3 = await _by_item(rls_session, sc)
    assert p3["A"].run_id == run2.id and p3["A"].status == "proposed"
    old = (await rls_session.execute(select(SettlementAiProposal).where(SettlementAiProposal.id == p2["D"].id))).scalar_one()
    await rls_session.refresh(old)
    assert old.status == "superseded"
    await svc.decide(rls_session, sc["lead"], p3["A"].id, action="choose", candidate_ref=hist_ref)
    await rls_session.refresh(line_a)
    assert line_a.cost_source == "manual" and line_a.direct_unit_cost == Decimal("90.0000") and "Historical median" in (line_a.source_note or "")

    # no source: accepting is refused, manual entry needs a reason, reject changes nothing
    with pytest.raises(ValidationAppError):
        await svc.decide(rls_session, sc["lead"], p3["C"].id, action="accept")
    with pytest.raises(ValidationAppError):
        await svc.decide(rls_session, sc["lead"], p3["C"].id, action="manual", manual_unit_cost=Decimal("1200"))
    man = await svc.decide(rls_session, sc["lead"], p3["C"].id, action="manual", manual_unit_cost=Decimal("1200"), note="quoted by phone")
    assert man.status == "overridden"
    line_c = (await rls_session.execute(select(BidSettlementLineItem).where(BidSettlementLineItem.boq_line_item_id == sc["items"]["C"].id))).scalar_one()
    await rls_session.refresh(line_c)
    assert line_c.direct_unit_cost == Decimal("1200.0000") and line_c.cost_source == "manual"
    rej = await svc.decide(rls_session, sc["lead"], p3["D"].id, action="reject", note="not this vendor")
    line_d = (await rls_session.execute(select(BidSettlementLineItem).where(BidSettlementLineItem.boq_line_item_id == sc["items"]["D"].id))).scalar_one()
    await rls_session.refresh(line_d)
    assert rej.status == "rejected" and line_d.direct_unit_cost is None
    with pytest.raises(ValidationAppError):
        await svc.decide(rls_session, sc["lead"], p3["B"].id, action="choose", candidate_ref="c:not-a-candidate")


async def test_bulk_accept_only_takes_high_confidence_unblocked_proposals(rls_session):
    sc = await _scenario(rls_session)
    register_mock_handler("cost_choose", _ai_choose)
    await _propose(rls_session, sc)
    res = await svc.bulk_accept(rls_session, sc["lead"], sc["settlement"].id)
    p = await _by_item(rls_session, sc)
    assert res == {"accepted": 2, "skipped": 1}              # A and D; B is stale (blocked); C has no source
    assert p["A"].status == "accepted" and p["D"].status == "accepted" and p["B"].status == "proposed" and p["C"].status == "proposed"
    lines = {l.boq_line_item_id: l for l in await settlement_service.list_settlement_lines(rls_session, sc["settlement"].id)}
    assert lines[sc["items"]["B"].id].direct_unit_cost is None and lines[sc["items"]["C"].id].direct_unit_cost is None


async def test_rules_only_when_ai_disabled_or_unavailable_and_the_ai_cannot_invent_sources(rls_session):
    sc = await _scenario(rls_session)
    rules_run = await _propose(rls_session, sc, use_ai=False)
    p = await _by_item(rls_session, sc)
    assert p["A"].source == "rules" and p["A"].chosen["ref"].startswith("q:") and p["C"].chosen is None
    assert p["D"].chosen["ref"].startswith("q:") and Decimal(p["D"].chosen["rate"]) == Decimal("10.0000")

    denied, _ = _gateway(sc["lead"], external_allowed=False)
    run = await _propose(rls_session, sc, gateway=denied)
    run_row = await svc.get_run(rls_session, run.id)
    assert any("AI matching was not used" in w and "ai_not_allowed" in w for w in run_row.warnings)

    # a model that answers with an invented ref and asks for a rate gets nothing applied
    register_mock_handler("cost_choose", lambda req: {"lines": [
        {"id": lid.split("\n")[0].strip(), "ranked": [{"ref": "q:INVENTED", "score": 1.0, "selected": True, "rationale": "use 1.00", "rate": 1.0}]}
        for lid in req.user.split("<<<LINE id=")[1:]]})
    await _propose(rls_session, sc)
    p2 = await _by_item(rls_session, sc)
    assert all((x.chosen or {}).get("ref") != "q:INVENTED" for x in p2.values())
    assert Decimal(p2["A"].chosen["rate"]) == Decimal("95.0000") and p2["A"].source == "rules"   # fell back to the safe rule choice


async def test_only_draft_settlements_and_unit_mismatch_cannot_be_applied(rls_session):
    sc = await _scenario(rls_session)
    register_mock_handler("cost_choose", _ai_choose)
    await _propose(rls_session, sc)
    p = await _by_item(rls_session, sc)
    settlement = (await rls_session.execute(select(BidSettlement).where(BidSettlement.id == sc["settlement"].id))).scalar_one()
    settlement.status = "submitted"
    await rls_session.flush()
    with pytest.raises(ConflictError):
        await svc.decide(rls_session, sc["lead"], p["A"].id, action="accept")
    with pytest.raises(ConflictError):
        await svc.create_run(rls_session, sc["lead"], sc["settlement"].id, kind="costs")
    with pytest.raises(ConflictError):
        await svc.bulk_accept(rls_session, sc["lead"], sc["settlement"].id)


async def test_markup_advice_is_advisory_computed_by_the_engine_and_never_applied(rls_session):
    sc = await _scenario(rls_session)
    register_mock_handler("markup_advise", lambda req: {
        "options": [
            {"label": "competitive", "markup_pct": 5, "overhead_pct": 4, "volatility_pct": 2, "rationale": "won 100% below 8% margin", "tender_total": "1", "margin_on_sell_pct": 99},
            {"label": "balanced", "markup_pct": 8, "overhead_pct": 5, "volatility_pct": 3, "rationale": "in line with history"},
            {"label": "protective", "markup_pct": 400, "overhead_pct": 6, "volatility_pct": 5, "rationale": "flagged lines"},
        ],
        "per_trade": [{"trade": "drainage", "markup_low": 9, "markup_high": 6, "rationale": "risk"}],
        "overall": "Modest history.",
    })
    await svc.bulk_accept(rls_session, sc["lead"], sc["settlement"].id)  # nothing proposed yet: zero, fine
    await _propose(rls_session, sc)
    await svc.bulk_accept(rls_session, sc["lead"], sc["settlement"].id)   # resolve A and D so margins are meaningful
    before = (sc["settlement"].default_markup_pct, sc["settlement"].default_overhead_pct, sc["settlement"].default_volatility_pct)
    run = await svc.create_run(rls_session, sc["lead"], sc["settlement"].id, kind="markup")
    await svc.run_markup_advice(rls_session, sc["lead"], run.id, _noprogress, gateway=_gateway(sc["lead"])[0])
    run = await svc.get_run(rls_session, run.id)
    assert run.status == "ready" and run.kind == "markup"
    res = run.result
    labels = [o["label"] for o in res["options"]]
    assert labels == ["competitive", "balanced", "protective"]
    comp, bal, prot = res["options"]
    assert prot["markup_pct"] == 40.0                                  # clamped
    assert comp["tender_total"] != "1" and comp["margin_on_sell_pct"] != "99"   # the model's numbers are never used
    assert float(comp["margin_on_sell_pct"]) < float(bal["margin_on_sell_pct"]) < float(prot["margin_on_sell_pct"])
    assert all(o["required_role"] in ("bd_director", "managing_director") for o in res["options"])
    assert res["per_trade"][0]["markup_low"] == 6.0 and res["per_trade"][0]["markup_high"] == 9.0
    assert res["history"] and res["history"][0]["bids"] == 1
    settlement = (await rls_session.execute(select(BidSettlement).where(BidSettlement.id == sc["settlement"].id))).scalar_one()
    assert (settlement.default_markup_pct, settlement.default_overhead_pct, settlement.default_volatility_pct) == before   # advice is never applied

    # AI unavailable: no advice, a clear warning, nothing invented
    denied, _ = _gateway(sc["lead"], external_allowed=False)
    run2 = await svc.create_run(rls_session, sc["lead"], sc["settlement"].id, kind="markup")
    await svc.run_markup_advice(rls_session, sc["lead"], run2.id, _noprogress, gateway=denied)
    run2 = await svc.get_run(rls_session, run2.id)
    assert run2.result["options"] == [] and any("needs the AI" in w for w in run2.warnings)
