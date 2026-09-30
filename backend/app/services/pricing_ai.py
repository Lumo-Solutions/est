"""AI pricing assistant lifecycle (docs/ai-plan.md, Phase 4).

create_run -> (worker) run_cost_proposals / run_markup_advice -> list_proposals -> decide / bulk_accept.
Every proposed cost comes from a REAL source (accepted vendor quote line, cost-library rate as of the
tender date, historical median); accepting applies it through settlement.set_line_cost, so rates stay
authoritative and Decimal, and approval routing / segregation of duties are unchanged. The AI only picks
among candidates (and never outputs a rate); markup advice is advisory and the platform computes every
margin figure with the existing settlement engine.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from rapidfuzz import fuzz, process
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.gateway import AIGateway, AIMeta
from app.core.config import get_settings
from app.core.context import RequestContext
from app.core.enums import AuditAction, BidSettlementStatus, QuotationLineItemStatus
from app.core.errors import ConflictError, NotFoundError, ValidationAppError
from app.models.ai import AiCall
from app.models.boq import BoqLineItem
from app.models.costlib import CostItem, CostItemRate, CostRateComponent
from app.models.module_e import OutturnCostObservation
from app.models.pricing_ai import SettlementAiProposal, SettlementAiRun
from app.models.quotation_ingestion import Quotation, QuotationExclusionFlag, QuotationLineItem
from app.models.settlement import BidSettlement, BidSettlementLineItem
from app.models.taxonomy import TradeNode
from app.models.tenancy import Project
from app.models.vendors import Vendor
from app.pricing import ai as pai
from app.pricing import engine as pe
from app.schemas.settlement import LineCostUpdate, SimulateRequest
from app.services import audit
from app.services import settlement as settlement_service
from app.services.projects import assert_can_see_project

LIBRARY_TOP_K = 5
LIBRARY_MIN_SIMILARITY = 0.45
HISTORY_MIN_SIMILARITY = 0.8
HISTORY_MAX_SAMPLES = 15
DEFAULT_SIZE_BANDS = ((5_000_000, "small"), (50_000_000, "medium"))


# ------------------------------------------------------------------ serialisation

def _cand_json(c: pe.CostCandidate) -> dict:
    return {
        "ref": c.ref, "type": c.ctype, "label": c.label, "rate": str(c.rate), "currency": c.currency, "uom": c.uom,
        "apply": c.apply, "match_score": c.match_score, "vendor": c.vendor, "as_of": c.as_of.isoformat() if c.as_of else None,
        "samples": c.samples, "flags": c.flags, "detail": c.detail,
    }


def _prop_candidates_json(p: pe.Proposal) -> list[dict]:
    out = []
    for c, score, why in p.ranked:
        d = _cand_json(c)
        d["score"], d["reason"] = round(score, 3), why
        d["selected"] = p.chosen is not None and c.ref == p.chosen.ref
        out.append(d)
    return out


# ------------------------------------------------------------------ runs

async def create_run(
    session: AsyncSession, ctx: RequestContext, settlement_id: UUID, *, kind: str, use_ai: bool = True, params: dict | None = None
) -> SettlementAiRun:
    settlement = await settlement_service._get_settlement(session, settlement_id)
    await assert_can_see_project(session, ctx, settlement.project_id)
    if settlement.status != BidSettlementStatus.DRAFT.value:
        raise ConflictError("AI cost proposals and markup advice are only available while the settlement is a draft")
    if kind not in ("costs", "markup"):
        raise ValidationAppError(f"Unknown AI run kind {kind!r}")
    run = SettlementAiRun(
        tenant_id=ctx.tenant_id, project_id=settlement.project_id, settlement_id=settlement.id, kind=kind, use_ai=use_ai,
        params=params or {}, created_by=ctx.user_id, updated_by=ctx.user_id,
    )
    session.add(run)
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.CREATE, entity_type="settlement_ai_run", entity_id=run.id, project_id=settlement.project_id,
        payload={"kind": kind, "use_ai": use_ai, "settlement_id": str(settlement.id)},
    )
    return run


async def get_run(session: AsyncSession, run_id: UUID) -> SettlementAiRun:
    run = (await session.execute(select(SettlementAiRun).where(SettlementAiRun.id == run_id))).scalar_one_or_none()
    if run is None:
        raise NotFoundError(f"AI run {run_id} not found")
    return run


async def list_runs(session: AsyncSession, settlement_id: UUID) -> list[SettlementAiRun]:
    res = await session.execute(
        select(SettlementAiRun).where(SettlementAiRun.settlement_id == settlement_id).order_by(SettlementAiRun.created_at.desc())
    )
    return list(res.scalars().all())


async def _ai_usage(session: AsyncSession, run_id: UUID) -> tuple[int, Decimal]:
    n, cost = (
        await session.execute(
            select(func.count(), func.coalesce(func.sum(AiCall.cost_usd), 0)).where(
                AiCall.entity_type == "settlement_ai_run", AiCall.entity_id == str(run_id), AiCall.status.in_(("ok", "cached"))
            )
        )
    ).one()
    return int(n), Decimal(cost)


# ------------------------------------------------------------------ candidate gathering

async def _rate_as_of(session: AsyncSession, ctx: RequestContext, cost_item_id: UUID, valid_on: date) -> CostItemRate | None:
    """Same lookup as costlib.get_rate_as_of but without a per-row audit event: a run looks up hundreds of
    rates, and records ONE audit event for the whole run instead (see run_cost_proposals)."""
    row = (
        await session.execute(
            text("SELECT id FROM costlib_rate_as_of(:t, :i, :s, :vo, :ka)"),
            {"t": str(ctx.tenant_id), "i": str(cost_item_id), "s": "GLOBAL", "vo": valid_on, "ka": datetime.now(timezone.utc)},
        )
    ).mappings().first()
    if row is None:
        return None
    return (await session.execute(select(CostItemRate).where(CostItemRate.id == row["id"]))).scalar_one()


async def _gather(
    session: AsyncSession, ctx: RequestContext, settlement: BidSettlement, project: Project, lines: list[BidSettlementLineItem],
    items: dict[UUID, BoqLineItem], tender_date: date,
) -> tuple[dict[UUID, list[pe.CostCandidate]], int]:
    settings = get_settings()
    stale = settings.ai_stale_rate_months or pe.DEFAULT_STALE_MONTHS
    item_ids = [l.boq_line_item_id for l in lines]
    out: dict[UUID, list[pe.CostCandidate]] = {l.boq_line_item_id: [] for l in lines}
    rate_lookups = 0

    # ---- accepted vendor quote lines
    quote_rows = (
        await session.execute(
            select(QuotationLineItem, Quotation, Vendor)
            .join(Quotation, Quotation.id == QuotationLineItem.quotation_id)
            .join(Vendor, Vendor.id == Quotation.vendor_id)
            .where(
                Quotation.project_id == project.id,
                QuotationLineItem.status == QuotationLineItemStatus.ACCEPTED.value,
                QuotationLineItem.boq_line_item_id.in_(item_ids or [UUID(int=0)]),
            )
        )
    ).all()
    open_flags: dict[tuple[UUID, UUID | None], int] = {}
    if quote_rows:
        flag_rows = (
            await session.execute(
                select(QuotationExclusionFlag.quotation_id, QuotationExclusionFlag.line_item_id, func.count())
                .where(QuotationExclusionFlag.quotation_id.in_({q.id for _l, q, _v in quote_rows}), QuotationExclusionFlag.status == "open")
                .group_by(QuotationExclusionFlag.quotation_id, QuotationExclusionFlag.line_item_id)
            )
        ).all()
        open_flags = {(qid, lid): n for qid, lid, n in flag_rows}
    from app.services.procurement import _vendor_eligibility  # noqa: PLC0415 -- the one definition of vendor eligibility

    for qli, quotation, vendor in quote_rows:
        item = items.get(qli.boq_line_item_id)
        if item is None or qli.unit_price is None:
            continue
        excl = open_flags.get((quotation.id, qli.id), 0) + open_flags.get((quotation.id, None), 0)
        eligible: bool | None = None
        if item.trade_node_id is not None:
            eligible, _why = await _vendor_eligibility(session, vendor, item.trade_node_id, project.id)
        cand = pe.CostCandidate(
            ref=f"q:{qli.id}", ctype=pe.CandType.QUOTE.value,
            label=f"{vendor.trading_name or vendor.legal_name}: {(qli.vendor_description_text or item.description)[:140]}",
            rate=Decimal(str(qli.unit_price)), currency=quotation.currency or settlement.currency,
            uom=qli.vendor_uom or item.uom, vendor=vendor.trading_name or vendor.legal_name,
            as_of=quotation.submitted_at.date() if quotation.submitted_at else None,
            apply={"cost_source": "quotation_line", "source_quotation_line_item_id": str(qli.id)},
            match_score=pe.description_similarity(item.description, qli.vendor_description_text or item.description),
            detail={"vat_inclusive": quotation.vat_inclusive, "quotation_id": str(quotation.id), "vendor_id": str(vendor.id)},
        )
        cand.exclusions, cand.eligible = excl, eligible
        out[qli.boq_line_item_id].append(cand)

    # ---- cost library (fuzzy on description, unit interchangeable, rate as of the tender date)
    cost_items = (await session.execute(select(CostItem).where(CostItem.is_active.is_(True)))).scalars().all()
    lib_index = [(ci, ci.description.lower()) for ci in cost_items]
    lib_texts = [t for _ci, t in lib_index]
    rate_cache: dict[UUID, CostItemRate | None] = {}
    for line in lines:
        item = items[line.boq_line_item_id]
        if not lib_texts:
            break
        matches = process.extract(item.description.lower(), lib_texts, scorer=fuzz.token_set_ratio, limit=LIBRARY_TOP_K * 2)
        taken = 0
        for _text, score, idx in matches:
            ci = lib_index[idx][0]
            sim = round(score / 100.0, 3)
            trade_bonus = 0.05 if (item.trade_node_id and ci.trade_node_id == item.trade_node_id) else 0.0
            if sim + trade_bonus < LIBRARY_MIN_SIMILARITY:
                continue
            if ci.id not in rate_cache:
                rate_cache[ci.id] = await _rate_as_of(session, ctx, ci.id, tender_date)
                rate_lookups += 1
            rate = rate_cache[ci.id]
            if rate is None:
                continue
            valid_from = rate.valid_period.lower if rate.valid_period is not None else None
            n_components = (
                await session.execute(select(func.count()).select_from(CostRateComponent).where(CostRateComponent.rate_id == rate.id))
            ).scalar_one()
            out[line.boq_line_item_id].append(
                pe.CostCandidate(
                    ref=f"c:{ci.id}", ctype=pe.CandType.LIBRARY.value, label=f"{ci.code}: {ci.description[:160]}",
                    rate=Decimal(str(rate.total_rate)), currency=rate.currency, uom=ci.uom, as_of=valid_from,
                    apply={"cost_source": "cost_library_rate", "cost_item_id": str(ci.id), "valid_on": tender_date.isoformat()},
                    match_score=min(1.0, sim + trade_bonus), detail={"rate_id": str(rate.id), "components": int(n_components)},
                )
            )
            taken += 1
            if taken >= LIBRARY_TOP_K:
                break

    # ---- history: past submitted/approved settlements + outturn observations, fuzzy on description
    hist_rows = (
        await session.execute(
            select(BidSettlementLineItem.direct_unit_cost, BidSettlementLineItem.source_currency, BoqLineItem.description, BoqLineItem.uom)
            .join(BidSettlement, BidSettlement.id == BidSettlementLineItem.settlement_id)
            .join(BoqLineItem, BoqLineItem.id == BidSettlementLineItem.boq_line_item_id)
            .where(
                BidSettlement.project_id != project.id,
                BidSettlement.status.in_((BidSettlementStatus.SUBMITTED.value, BidSettlementStatus.APPROVED.value)),
                BidSettlementLineItem.direct_unit_cost.is_not(None),
            )
        )
    ).all()
    outturn_rows = (
        await session.execute(
            select(OutturnCostObservation.observed_unit_cost, OutturnCostObservation.currency, BoqLineItem.description, BoqLineItem.uom)
            .join(BoqLineItem, BoqLineItem.id == OutturnCostObservation.boq_line_item_id)
            .where(OutturnCostObservation.project_id != project.id, OutturnCostObservation.boq_line_item_id.is_not(None))
        )
    ).all()
    pool = [(Decimal(str(r)), cur, d, u, "settlement") for r, cur, d, u in hist_rows] + [
        (Decimal(str(r)), cur, d, u, "outturn") for r, cur, d, u in outturn_rows
    ]
    pool_texts = [p[2].lower() for p in pool]
    for line in lines:
        item = items[line.boq_line_item_id]
        if not pool_texts:
            break
        hits = process.extract(item.description.lower(), pool_texts, scorer=fuzz.token_set_ratio, limit=40, score_cutoff=HISTORY_MIN_SIMILARITY * 100)
        rates = [
            pool[idx][0] for _t, _s, idx in hits
            if pool[idx][1] == settlement.currency and pe.units_compatible(item.uom, pool[idx][3])[0]
        ][:HISTORY_MAX_SAMPLES]
        median = pe.historical_median(rates)
        if median is None:
            continue
        kinds = {pool[idx][4] for _t, _s, idx in hits}
        out[line.boq_line_item_id].append(
            pe.CostCandidate(
                ref=f"h:{line.boq_line_item_id}", ctype=pe.CandType.HISTORICAL.value,
                label=f"Median of {len(rates)} past {'/'.join(sorted(kinds))} observation(s) for similar items",
                rate=median, currency=settlement.currency, uom=item.uom, samples=len(rates),
                apply={
                    "cost_source": "manual", "manual_unit_cost": str(median), "manual_currency": settlement.currency,
                    "source_note": f"Historical median of {len(rates)} past observation(s) for similar items (AI-assisted proposal)",
                },
                match_score=0.8, detail={"min": str(min(rates)), "max": str(max(rates))},
            )
        )

    # ---- flags (computed in code)
    for line in lines:
        cands = out[line.boq_line_item_id]
        item = items[line.boq_line_item_id]
        hist = next((c for c in cands if c.ctype == pe.CandType.HISTORICAL.value), None)
        real = [c for c in cands if c.ctype != pe.CandType.HISTORICAL.value]
        for c in cands:
            if c.as_of is not None:
                c.detail["age_months"] = round(pe.months_between(c.as_of, tender_date), 1)
            c.flags = pe.compute_flags(
                c, boq_uom=item.uom, settlement_currency=settlement.currency, tender_date=tender_date, stale_months=stale,
                history_median=hist.rate if hist else None, exclusion_count=c.exclusions,
                vendor_eligible=c.eligible, source_count=max(1, len(real)) if c.ctype != "historical" else 2,
            )
    return out, rate_lookups


# ------------------------------------------------------------------ run: cost proposals

async def run_cost_proposals(
    session: AsyncSession, ctx: RequestContext, run_id: UUID, progress, gateway: AIGateway | None = None
) -> None:
    from app.boq.pdf_ai import default_gateway

    run = await get_run(session, run_id)
    settlement = await settlement_service._get_settlement(session, run.settlement_id)
    if settlement.status != BidSettlementStatus.DRAFT.value:
        raise ConflictError("The settlement is no longer a draft")
    project = (await session.execute(select(Project).where(Project.id == settlement.project_id))).scalar_one()
    tender_date = project.submission_due_at.date() if project.submission_due_at else datetime.now(timezone.utc).date()
    lines = await settlement_service.list_settlement_lines(session, settlement.id)
    items = await settlement_service._boq_items_by_id(session, [l.boq_line_item_id for l in lines])
    total = max(1, len(lines))
    await progress(0, total)
    cands, rate_lookups = await _gather(session, ctx, settlement, project, lines, items, tender_date)
    await progress(total // 3, total)

    meta = AIMeta(project_id=project.id, entity_type="settlement_ai_run", entity_id=str(run.id))
    gw = gateway or (default_gateway() if run.use_ai else None)
    ai_out: dict[str, dict] = {}
    ai_reason: str | None = None
    if run.use_ai and gw is not None:
        work = [
            {"id": str(l.boq_line_item_id), "item_no": items[l.boq_line_item_id].item_no, "description": items[l.boq_line_item_id].description,
             "uom": items[l.boq_line_item_id].uom, "quantity": f"{float(l.quantity):,.2f}"}
            for l in lines
        ]
        cmap = {str(k): v for k, v in cands.items()}
        ai_out, outcome = await pai.choose_costs(gw, work, cmap, meta)
        ai_reason = outcome.unavailable_reason
    await progress(2 * total // 3, total)

    # Supersede earlier open proposals for these lines, then write the new ones.
    await session.execute(
        text("UPDATE settlement_ai_proposals SET status='superseded', updated_at=now() WHERE settlement_id=:s AND status='proposed'"),
        {"s": str(settlement.id)},
    )
    created_at = datetime.now(timezone.utc)  # explicit: now() is the transaction time, so two runs in one transaction would tie
    counts = {"lines": len(lines), "with_source": 0, "no_source": 0, "ai_chosen": 0, "rules_chosen": 0, "blocked": 0, "bulk_acceptable": 0}
    for line in lines:
        key = str(line.boq_line_item_id)
        line_cands = cands[line.boq_line_item_id]
        if not line_cands:
            prop = pe.Proposal(None, [], 0.0, pe.NO_SOURCE_NOTE, [], "none")
        elif key in ai_out:
            prop = pe.ai_choice(line_cands, ai_out[key]["ranked"], ai_out[key]["overall"])
            if prop.chosen is None:  # the model found nothing suitable: fall back to the rules' safe choice
                fallback = pe.rules_choice(line_cands)
                if fallback.chosen is not None:
                    prop = fallback
        else:
            prop = pe.rules_choice(line_cands)
        if prop.chosen is None:
            counts["no_source"] += 1
        else:
            counts["with_source"] += 1
            counts["ai_chosen" if prop.source == "ai" else "rules_chosen"] += 1
            counts["blocked"] += 1 if pe.is_blocked(prop.flags) else 0
            counts["bulk_acceptable"] += 1 if pe.can_bulk_accept(prop) else 0
        session.add(
            SettlementAiProposal(
                tenant_id=ctx.tenant_id, project_id=project.id, run_id=run.id, settlement_id=settlement.id,
                settlement_line_id=line.id, boq_line_item_id=line.boq_line_item_id, status="proposed", source=prop.source,
                chosen=_cand_json(prop.chosen) if prop.chosen else None, candidates=_prop_candidates_json(prop),
                rationale=prop.rationale, flags=prop.flags, confidence=prop.confidence, created_by=ctx.user_id,
                created_at=created_at,
            )
        )
    warnings: list[str] = []
    if run.use_ai and (gw is None or ai_reason or not ai_out):
        warnings.append(
            "AI matching was not used" + (f" ({ai_reason})" if ai_reason else "")
            + ": proposals come from the built-in rules only (accepted quotes, then close cost-library matches)."
        )
    if counts["no_source"]:
        warnings.append(f"{counts['no_source']} line(s) have no cost source: {pe.NO_SOURCE_NOTE}.")
    run.counts, run.warnings = counts, warnings
    run.status, run.progress_done, run.progress_total = "ready", total, total
    run.finished_at = datetime.now(timezone.utc)
    run.ai_calls, run.ai_cost_usd = await _ai_usage(session, run.id)
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.READ, entity_type="cost_item_rate", entity_id=run.id, project_id=project.id,
        payload={"bulk": True, "run_id": str(run.id), "rate_lookups": rate_lookups, "valid_on": tender_date.isoformat()},
    )
    await audit.record(
        session, ctx, action=AuditAction.UPDATE, entity_type="settlement_ai_run", entity_id=run.id, project_id=project.id,
        payload={"event": "completed", "kind": "costs", "counts": counts, "ai_calls": run.ai_calls, "ai_cost_usd": str(run.ai_cost_usd)},
    )


# ------------------------------------------------------------------ proposals

async def list_proposals(
    session: AsyncSession, settlement_id: UUID, *, status: str | None = None, flagged: bool | None = None,
    no_source: bool | None = None, min_confidence: float | None = None, max_confidence: float | None = None,
    limit: int = 500, offset: int = 0,
) -> tuple[list[SettlementAiProposal], int]:
    stmt = select(SettlementAiProposal).where(
        SettlementAiProposal.settlement_id == settlement_id, SettlementAiProposal.status != "superseded"
    )
    if status:
        stmt = stmt.where(SettlementAiProposal.status == status)
    if no_source is True:
        stmt = stmt.where(SettlementAiProposal.chosen.is_(None))
    elif no_source is False:
        stmt = stmt.where(SettlementAiProposal.chosen.is_not(None))
    if min_confidence is not None:
        stmt = stmt.where(SettlementAiProposal.confidence >= min_confidence)
    if max_confidence is not None:
        stmt = stmt.where(SettlementAiProposal.confidence <= max_confidence)
    rows = list((await session.execute(stmt.order_by(SettlementAiProposal.created_at, SettlementAiProposal.id))).scalars().all())
    # One row per settlement line: the latest proposal (an older, already-decided one is history, not a second row).
    latest: dict[UUID, SettlementAiProposal] = {}
    for r in rows:
        latest[r.settlement_line_id] = r
    rows = sorted(latest.values(), key=lambda r: (r.created_at, r.id))
    if flagged is not None:
        rows = [r for r in rows if bool(r.flags and pe.is_blocked(list(r.flags))) == flagged]
    total = len(rows)
    return rows[offset : offset + limit], total


async def get_proposal(session: AsyncSession, proposal_id: UUID) -> SettlementAiProposal:
    p = (await session.execute(select(SettlementAiProposal).where(SettlementAiProposal.id == proposal_id))).scalar_one_or_none()
    if p is None:
        raise NotFoundError(f"AI proposal {proposal_id} not found")
    return p


def _to_update(apply: dict, note: str) -> LineCostUpdate:
    payload = dict(apply)
    if payload.get("cost_source") == "cost_library_rate":
        payload["valid_on"] = date.fromisoformat(payload["valid_on"])
    payload["source_note"] = note if payload.get("cost_source") == "manual" and "source_note" not in payload else (
        f"{payload['source_note']}. {note}" if payload.get("source_note") else note
    )
    return LineCostUpdate.model_validate(payload)


async def decide(
    session: AsyncSession, ctx: RequestContext, proposal_id: UUID, *, action: str, candidate_ref: str | None = None,
    manual_unit_cost: Decimal | None = None, manual_currency: str | None = None, note: str | None = None,
) -> SettlementAiProposal:
    if action not in ("accept", "choose", "manual", "reject"):
        raise ValidationAppError(f"Unknown action {action!r}")
    p = await get_proposal(session, proposal_id)
    if p.status != "proposed":
        raise ConflictError(f"This proposal was already {p.status}")
    settlement = await settlement_service._get_settlement(session, p.settlement_id)
    if settlement.status != BidSettlementStatus.DRAFT.value:
        raise ConflictError("The settlement is no longer a draft")
    await assert_can_see_project(session, ctx, p.project_id)
    run = await get_run(session, p.run_id)
    tag = f"AI proposal (run {str(run.id)[:8]}) {action}ed by user" if action != "reject" else "rejected"
    applied: dict | None = None
    new_status = "accepted"

    if action == "reject":
        new_status = "rejected"
    else:
        if action == "accept":
            if not p.chosen:
                raise ValidationAppError(f"{pe.NO_SOURCE_NOTE}: choose a candidate or enter a cost manually")
            cand = p.chosen
        elif action == "choose":
            cand = next((c for c in p.candidates if c["ref"] == candidate_ref), None)
            if cand is None:
                raise ValidationAppError("That candidate is not one of this line's proposals")
            new_status = "accepted" if p.chosen and p.chosen["ref"] == candidate_ref else "overridden"
        else:  # manual
            if manual_unit_cost is None or not (note or "").strip():
                raise ValidationAppError("manual_unit_cost and a note (why) are required")
            cand = {"apply": {"cost_source": "manual", "manual_unit_cost": str(manual_unit_cost),
                              "manual_currency": manual_currency or settlement.currency}, "ref": "manual"}
            new_status = "overridden"
        if pe.UNIT_MISMATCH in (cand.get("flags") or []):
            raise ValidationAppError("That source is in a different unit from the BOQ line and cannot be applied")
        update = _to_update(cand["apply"], f"{tag}. {note}".strip() if note else tag)
        await settlement_service.set_line_cost(session, ctx, p.settlement_id, p.settlement_line_id, update)
        applied = {"ref": cand.get("ref"), **{k: v for k, v in cand["apply"].items() if k != "source_note"}}

    p.status, p.decided_by, p.decided_at, p.decision_note, p.applied = new_status, ctx.user_id, datetime.now(timezone.utc), note, applied
    p.updated_by = ctx.user_id
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.UPDATE, entity_type="settlement_ai_proposal", entity_id=p.id, project_id=p.project_id,
        payload={"decision": new_status, "action": action, "run_id": str(p.run_id), "source": p.source,
                 "chosen_ref": (p.chosen or {}).get("ref"), "applied_ref": (applied or {}).get("ref"),
                 "confidence": float(p.confidence), "note": note},
    )
    return p


async def bulk_accept(
    session: AsyncSession, ctx: RequestContext, settlement_id: UUID, *, min_confidence: float = pe.BULK_ACCEPT_MIN_CONFIDENCE
) -> dict:
    settlement = await settlement_service._get_settlement(session, settlement_id)
    if settlement.status != BidSettlementStatus.DRAFT.value:
        raise ConflictError("The settlement is no longer a draft")
    rows, _ = await list_proposals(session, settlement_id, status="proposed", no_source=False, limit=10_000)
    accepted = skipped = 0
    for p in rows:
        if float(p.confidence) < min_confidence or pe.is_blocked(list(p.flags or [])):
            skipped += 1
            continue
        await decide(session, ctx, p.id, action="accept", note=f"bulk accept at confidence >= {min_confidence:g}")
        accepted += 1
    await audit.record(
        session, ctx, action=AuditAction.UPDATE, entity_type="settlement_ai_proposal", entity_id=settlement_id,
        project_id=settlement.project_id, payload={"bulk_accept": accepted, "skipped": skipped, "min_confidence": min_confidence},
    )
    return {"accepted": accepted, "skipped": skipped}


# ------------------------------------------------------------------ markup advice

async def _history_for_advice(session: AsyncSession, tenant_project_id: UUID) -> list[dict]:
    rows = (
        await session.execute(
            select(BidSettlement.margin_on_sell_pct, BidSettlement.outcome, BidSettlement.outcome_our_price, BidSettlement.outcome_winning_price)
            .where(BidSettlement.project_id != tenant_project_id, BidSettlement.outcome.in_(("won", "lost")))
        )
    ).all()
    return [
        {"margin_on_sell_pct": float(m) if m is not None else None, "outcome": o, "our_price": float(op) if op else None,
         "winning_price": float(wp) if wp else None}
        for m, o, op, wp in rows
    ]


async def run_markup_advice(
    session: AsyncSession, ctx: RequestContext, run_id: UUID, progress, gateway: AIGateway | None = None
) -> None:
    from app.boq.pdf_ai import default_gateway

    run = await get_run(session, run_id)
    settlement = await settlement_service._get_settlement(session, run.settlement_id)
    if settlement.status != BidSettlementStatus.DRAFT.value:
        raise ConflictError("The settlement is no longer a draft")
    project = (await session.execute(select(Project).where(Project.id == settlement.project_id))).scalar_one()
    lines = await settlement_service.list_settlement_lines(session, settlement.id)
    items = await settlement_service._boq_items_by_id(session, [l.boq_line_item_id for l in lines])
    trades = {t.id: t.name for t in (await session.execute(select(TradeNode))).scalars().all()}
    flagged_ids = {
        p.boq_line_item_id for p in (await list_proposals(session, settlement.id, limit=10_000))[0] if p.flags and pe.is_blocked(list(p.flags))
    }
    per_trade: dict[str, dict] = {}
    for l in lines:
        name = trades.get(items[l.boq_line_item_id].trade_node_id) if items[l.boq_line_item_id].trade_node_id else "Unclassified"
        t = per_trade.setdefault(name, {"trade": name, "lines": 0, "direct_cost": Decimal(0), "flagged_lines": 0, "unresolved_lines": 0})
        t["lines"] += 1
        if l.direct_unit_cost is None:
            t["unresolved_lines"] += 1
        else:
            t["direct_cost"] += Decimal(str(l.direct_unit_cost)) * Decimal(str(l.quantity))
        if l.boq_line_item_id in flagged_ids:
            t["flagged_lines"] += 1
    base = await settlement_service._compute_breakdown(session, settlement, None)
    history = pe.win_rate_by_margin(await _history_for_advice(session, project.id))
    total_direct = base.direct_cost_total
    band = next((label for limit, label in DEFAULT_SIZE_BANDS if float(total_direct) < limit), "large")
    context = {
        "project": {"name": project.name, "size_band": band, "currency": settlement.currency},
        "settings": {"plant_pct": float(settlement.default_plant_pct), "overhead_pct": float(settlement.default_overhead_pct),
                     "volatility_pct": float(settlement.default_volatility_pct), "markup_pct": float(settlement.default_markup_pct)},
        "trades": [{**t, "direct_cost": f"{t['direct_cost']:,.0f}"} for t in per_trade.values()],
        "history": history,
        "totals": {"direct_cost": f"{total_direct:,.0f}", "lines": len(lines), "flagged_lines": len(flagged_ids),
                   "unresolved_lines": len(base.unresolved_line_ids)},
    }
    await progress(1, 3)
    meta = AIMeta(project_id=project.id, entity_type="settlement_ai_run", entity_id=str(run.id))
    gw = gateway or (default_gateway() if run.use_ai else None)
    advice, reason = None, None
    if run.use_ai and gw is not None:
        advice, outcome = await pai.advise_markup(gw, context, meta)
        reason = outcome.unavailable_reason
    warnings: list[str] = []
    result: dict = {"context": {k: v for k, v in context.items() if k != "project"}, "history": history, "options": [], "per_trade": [], "overall": ""}
    if advice is None:
        warnings.append("Markup advice needs the AI" + (f" ({reason})" if reason else "") + "; nothing was suggested. Set the percentages yourself.")
    else:
        # The platform, not the model, computes what each option would mean, with the existing engine.
        for opt in advice["options"]:
            sim = await settlement_service._compute_breakdown(
                session, settlement,
                SimulateRequest(default_markup_pct=opt["markup_pct"], default_overhead_pct=opt["overhead_pct"], default_volatility_pct=opt["volatility_pct"]),
            )
            opt.update(
                tender_total=str(sim.tender_total), margin_on_sell_pct=None if sim.margin_on_sell_pct is None else str(sim.margin_on_sell_pct),
                required_role=sim.required_role, unresolved_lines=len(sim.unresolved_line_ids),
            )
        result.update(options=advice["options"], per_trade=advice["per_trade"], overall=advice["overall"])
    result["current"] = {
        "tender_total": str(base.tender_total), "margin_on_sell_pct": None if base.margin_on_sell_pct is None else str(base.margin_on_sell_pct),
        "required_role": base.required_role,
    }
    run.result, run.warnings = result, warnings
    run.counts = {"options": len(result["options"]), "trades": len(per_trade)}
    run.status, run.progress_done, run.progress_total = "ready", 3, 3
    run.finished_at = datetime.now(timezone.utc)
    run.ai_calls, run.ai_cost_usd = await _ai_usage(session, run.id)
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.UPDATE, entity_type="settlement_ai_run", entity_id=run.id, project_id=project.id,
        payload={"event": "completed", "kind": "markup", "options": len(result["options"]), "ai_calls": run.ai_calls},
    )
