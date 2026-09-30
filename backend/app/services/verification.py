"""Drawing <-> BOQ verification lifecycle (docs/ai-plan.md §5).

create_run -> (worker) run_verification -> list/get -> set_mapping (accept / reject / include /
clear, audited, non-destructive) -> recompute -> export. All quantities come from
app.verification.engine over measured geometry or annotations READ from the sheets; the AI only
proposes which evidence belongs to which line. Accepting a measurement also creates the existing
reconciliation link, so verification and reconciliation stay one system.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.errors import describe_reason
from app.ai.gateway import AIGateway, AIMeta
from app.boq import units as unit_conversion
from app.core.context import RequestContext
from app.core.enums import AuditAction
from app.core.errors import ConflictError, NotFoundError, ValidationAppError
from app.models.ai import AiCall
from app.models.boq import BoqLineItem, BoqTolerance
from app.models.takeoff import DrawingAnnotation, DrawingMeasurement, DrawingSheet, live_drawing_ids
from app.models.taxonomy import TradeNode
from app.models.verification import VerificationLine, VerificationMapping, VerificationRun
from app.services import audit
from app.services.projects import assert_can_see_project
from app.services.semantic_matching import MATCH_TYPE_BOQ_MEASUREMENT, build_measurement_descriptor, record_feedback
from app.verification import ai as vai
from app.verification.engine import (
    Candidate,
    Evidence,
    Interpretation,
    LineInput,
    LineResult,
    compute_line,
    find_missing_in_boq,
    generate_candidates,
    interpret_by_rules,
    summarize,
)

DEFAULT_TOLERANCE = 2.0
GROUPED_CAPABILITY = "pipe_network_topology"


def group_ref(sheet_id, capability: str, kind: str, layer: str | None) -> str:
    """Stable id of a group of measurements: it depends on WHAT the group is (sheet, kind, layer), not on
    which runs are in it, so a person's decision about it survives a re-extraction."""
    import hashlib

    return "g:" + hashlib.sha1(f"{sheet_id}|{capability}|{kind}|{layer or ''}".encode()).hexdigest()[:20]


# ------------------------------------------------------------------ serialisation

def _ev_json(e: Evidence) -> dict:
    return {
        "ref": e.ref, "kind": e.kind, "value": e.value, "unit": e.unit, "label": e.label, "drawing_id": e.drawing_id,
        "sheet_id": e.sheet_id, "page": e.page, "bbox": e.bbox, "layer": e.layer, "confidence": e.confidence,
        "material": e.material, "ann_kind": e.ann_kind, "members": list(e.members), "member_values": list(e.member_values),
    }


def _ev_from_json(d: dict) -> Evidence:
    return Evidence(
        ref=d["ref"], kind=d["kind"], value=float(d["value"]), unit=d.get("unit"), label=d.get("label", ""),
        drawing_id=d.get("drawing_id"), sheet_id=d.get("sheet_id"), page=d.get("page"), bbox=d.get("bbox"),
        layer=d.get("layer"), confidence=float(d.get("confidence", 1.0)), material=d.get("material"),
        ann_kind=d.get("ann_kind"), members=tuple(d.get("members") or ()),
        member_values=tuple(float(v) for v in (d.get("member_values") or ())),
    )


def _cand_json(c: Candidate) -> dict:
    return {"ref": c.ref, "score": round(c.score, 3), "reason": c.reason, "source": c.source, "selected": c.selected}


def _cand_from_json(d: dict) -> Candidate:
    return Candidate(d["ref"], float(d["score"]), d.get("reason", ""), d.get("source", "rules"), bool(d.get("selected")))


def _interp_json(i: Interpretation | None) -> dict | None:
    if i is None:
        return None
    return {"work_type": i.work_type, "material": i.material, "size_mm": i.size_mm, "unit": i.unit, "trade": i.trade,
            "source": i.source, "keywords": i.keywords}


def _interp_from_json(d: dict | None, line: LineInput) -> Interpretation:
    if not d:
        return interpret_by_rules(line)
    return Interpretation(d.get("work_type"), d.get("material"), d.get("size_mm"), d.get("unit"), d.get("trade"),
                          d.get("source", "rules"), list(d.get("keywords") or []))


# ------------------------------------------------------------------ loading

async def load_evidence(session: AsyncSession, project_id: UUID) -> list[Evidence]:
    trades = {t.id: t.name for t in (await session.execute(select(TradeNode))).scalars().all()}
    sheets = {
        s.id: s for s in (await session.execute(select(DrawingSheet).where(DrawingSheet.project_id == project_id, DrawingSheet.drawing_id.in_(live_drawing_ids(project_id))))).scalars().all()
    }
    out: list[Evidence] = []
    ms = (await session.execute(select(DrawingMeasurement).where(DrawingMeasurement.project_id == project_id, DrawingMeasurement.drawing_id.in_(live_drawing_ids(project_id))))).scalars().all()
    groups: dict[tuple, list[DrawingMeasurement]] = {}
    for m in ms:
        layer = (m.extractor_metadata or {}).get("layer") if m.extractor_metadata else None
        trade_name = trades.get(m.trade_node_id) if m.trade_node_id else None
        sheet = sheets.get(m.sheet_id)
        if m.capability == GROUPED_CAPABILITY:
            # The pipe extractor emits one measurement per run PLUS a network total. A BOQ line is the sum of
            # the runs of one size, so runs are grouped per (sheet, kind, layer) into one piece of evidence,
            # and the redundant total is skipped (selecting both would double count).
            if m.kind.endswith("_total_length_m"):
                continue
            groups.setdefault((m.drawing_id, m.sheet_id, m.capability, m.kind, layer or ""), []).append(m)
            continue
        bbox = None
        if None not in (m.bbox_min_x, m.bbox_min_y, m.bbox_max_x, m.bbox_max_y):
            bbox = [float(m.bbox_min_x), float(m.bbox_min_y), float(m.bbox_max_x), float(m.bbox_max_y)]
        out.append(
            Evidence(
                ref=f"m:{m.id}", kind="measurement", value=float(m.effective_value), unit=m.unit,
                label=build_measurement_descriptor(capability=m.capability, kind=m.kind, layer=layer, trade_name=trade_name),
                drawing_id=str(m.drawing_id), sheet_id=str(m.sheet_id), page=(sheet.sheet_index + 1) if sheet else None,
                bbox=bbox, layer=layer, trade_id=str(m.trade_node_id) if m.trade_node_id else None, trade_name=trade_name,
                confidence=float(m.confidence),
            )
        )
    for (drawing_id, sheet_id, capability, kind, layer), members in groups.items():
        sheet = sheets.get(sheet_id)
        trade_id = next((m.trade_node_id for m in members if m.trade_node_id), None)
        trade_name = trades.get(trade_id) if trade_id else None
        boxes = [(m.bbox_min_x, m.bbox_min_y, m.bbox_max_x, m.bbox_max_y) for m in members]
        bbox = None
        if all(None not in b for b in boxes):
            bbox = [min(float(b[0]) for b in boxes), min(float(b[1]) for b in boxes), max(float(b[2]) for b in boxes), max(float(b[3]) for b in boxes)]
        label = build_measurement_descriptor(capability=capability, kind=kind, layer=layer or None, trade_name=trade_name)
        out.append(
            Evidence(
                ref=group_ref(sheet_id, capability, kind, layer), kind="measurement",
                value=sum(float(m.effective_value) for m in members), unit=members[0].unit,
                label=f"{label} ({len(members)} run{'s' if len(members) != 1 else ''} summed)",
                drawing_id=str(drawing_id), sheet_id=str(sheet_id), page=(sheet.sheet_index + 1) if sheet else None,
                bbox=bbox, layer=layer or None, trade_id=str(trade_id) if trade_id else None, trade_name=trade_name,
                confidence=min(float(m.confidence) for m in members), members=tuple(sorted(str(m.id) for m in members)),
                member_values=tuple(float(m.effective_value) for m in members),
            )
        )
    anns = (await session.execute(select(DrawingAnnotation).where(DrawingAnnotation.project_id == project_id, DrawingAnnotation.sheet_id.in_(select(DrawingSheet.id).where(DrawingSheet.drawing_id.in_(live_drawing_ids(project_id))))))).scalars().all()
    for a in anns:
        if a.value is None:
            continue
        out.append(
            Evidence(
                ref=f"a:{a.id}", kind="annotation", value=float(a.value), unit=a.unit, label=a.text,
                drawing_id=str(a.drawing_id), sheet_id=str(a.sheet_id), page=a.page,
                bbox=[float(v) for v in a.bbox] if a.bbox else None, confidence=float(a.confidence or 0.6),
                material=a.material, ann_kind=a.kind,
            )
        )
    return out


async def _tolerances(session: AsyncSession, project_id: UUID) -> tuple[float, dict[UUID, float]]:
    rows = (await session.execute(select(BoqTolerance).where(BoqTolerance.project_id == project_id))).scalars().all()
    default = next((float(r.tolerance_pct) for r in rows if r.trade_node_id is None), DEFAULT_TOLERANCE)
    return default, {r.trade_node_id: float(r.tolerance_pct) for r in rows if r.trade_node_id is not None}


async def load_lines(session: AsyncSession, project_id: UUID) -> tuple[list[LineInput], dict[str, str], dict[str, str | None]]:
    items = (
        await session.execute(select(BoqLineItem).where(BoqLineItem.project_id == project_id).order_by(BoqLineItem.path))
    ).scalars().all()
    trades = {t.id: t.name for t in (await session.execute(select(TradeNode))).scalars().all()}
    default_tol, per_trade = await _tolerances(session, project_id)
    parents_with_children = {i.parent_id for i in items if i.parent_id}
    by_id = {i.id: i for i in items}
    lines: list[LineInput] = []
    parent_desc: dict[str, str] = {}
    trade_of: dict[str, str | None] = {}
    for i in items:
        trade_name = trades.get(i.trade_node_id) if i.trade_node_id else None
        lines.append(
            LineInput(
                id=str(i.id), item_no=i.item_no, description=i.description, uom=i.uom,
                quantity=float(i.boq_quantity) if i.boq_quantity is not None else None,
                trade_id=str(i.trade_node_id) if i.trade_node_id else None, trade_name=trade_name,
                is_heading=(i.id in parents_with_children and i.boq_quantity is None),
                tolerance_pct=per_trade.get(i.trade_node_id, default_tol) if i.trade_node_id else default_tol,
            )
        )
        parent = by_id.get(i.parent_id) if i.parent_id else None
        if parent is not None:
            parent_desc[str(i.id)] = f"{parent.item_no} {parent.description}"[:160]
        trade_of[str(i.id)] = trade_name
    return lines, parent_desc, trade_of


async def _decisions(session: AsyncSession, project_id: UUID) -> dict[str, tuple[set[str], set[str]]]:
    rows = (await session.execute(select(VerificationMapping).where(VerificationMapping.project_id == project_id))).scalars().all()
    out: dict[str, tuple[set[str], set[str]]] = {}
    for r in rows:
        inc, exc = out.setdefault(str(r.boq_line_item_id), (set(), set()))
        (inc if r.decision == "include" else exc).add(r.evidence_ref)
    return out


# ------------------------------------------------------------------ compute

def compute_all(
    lines: list[LineInput],
    interps: dict[str, Interpretation],
    cands: dict[str, list[Candidate]],
    evidence: list[Evidence],
    decisions: dict[str, tuple[set[str], set[str]]],
    ai_ranked: set[str],
) -> tuple[list[LineResult], list[LineResult]]:
    by_ref = {e.ref: e for e in evidence}
    results: list[LineResult] = []
    attached: set[str] = set()
    for line in lines:
        inc, exc = decisions.get(line.id, (set(), set()))
        res = compute_line(
            line, interps.get(line.id) or interpret_by_rules(line), cands.get(line.id, []), by_ref,
            include=inc, exclude=exc, ai_ranked=line.id in ai_ranked,
        )
        results.append(res)
        attached.update(e.ref for e in res.evidence)
    # Evidence a person explicitly excluded from a line is not "attached", so it can surface as
    # possible missed scope; evidence they included anywhere is accounted for.
    for inc, _exc in decisions.values():
        attached.update(inc)
    return results, find_missing_in_boq(evidence, attached)


def _row_from_result(
    run: VerificationRun, ctx: RequestContext, order: int, line: LineInput | None, res: LineResult
) -> VerificationLine:
    return VerificationLine(
        tenant_id=ctx.tenant_id, project_id=run.project_id, run_id=run.id,
        boq_line_item_id=UUID(line.id) if line else None, sort_order=order,
        item_no=line.item_no if line else None,
        description=line.description if line else (res.note or None),
        trade_name=line.trade_name if line else None, vclass=res.vclass, method=res.method, mapped_by=res.mapped_by,
        boq_quantity=res.boq_quantity if line else None, boq_uom=res.boq_uom,
        drawing_quantity=res.drawing_quantity, delta=res.delta, delta_pct=res.delta_pct, confidence=res.confidence,
        note=res.note or None, flags=res.flags, interpretation=_interp_json(res.interpretation),
        evidence=[_ev_json(e) for e in res.evidence], candidates=[_cand_json(c) for c in res.candidates],
        created_by=ctx.user_id,
    )


def _summary(results: list[LineResult], missing: list[LineResult], trade_of: dict[str, str | None]) -> tuple[dict, dict]:
    summ = summarize(results + missing, trade_of)
    return summ["counts"], {k: v for k, v in summ.items() if k != "counts"}


# ------------------------------------------------------------------ lifecycle

async def create_run(session: AsyncSession, ctx: RequestContext, project_id: UUID, *, use_ai: bool = True) -> VerificationRun:
    await assert_can_see_project(session, ctx, project_id)
    run = VerificationRun(
        tenant_id=ctx.tenant_id, project_id=project_id, status="queued", use_ai=use_ai, created_by=ctx.user_id,
        updated_by=ctx.user_id,
    )
    session.add(run)
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.CREATE, entity_type="verification_run", entity_id=run.id, project_id=project_id,
        payload={"use_ai": use_ai},
    )
    return run


async def get_run(session: AsyncSession, run_id: UUID) -> VerificationRun:
    run = (await session.execute(select(VerificationRun).where(VerificationRun.id == run_id))).scalar_one_or_none()
    if run is None:
        raise NotFoundError(f"Verification run {run_id} not found")
    return run


async def list_runs(session: AsyncSession, project_id: UUID) -> list[VerificationRun]:
    res = await session.execute(
        select(VerificationRun).where(VerificationRun.project_id == project_id).order_by(VerificationRun.created_at.desc())
    )
    return list(res.scalars().all())


async def run_verification(
    session: AsyncSession, ctx: RequestContext, run_id: UUID, progress, gateway: AIGateway | None = None
) -> None:
    """Worker body. No write to the run row until the end (see boq_pdf.run_extraction)."""
    from app.boq.pdf_ai import default_gateway

    run = await get_run(session, run_id)
    project_id = run.project_id
    lines, parents, trade_of = await load_lines(session, project_id)
    evidence = await load_evidence(session, project_id)
    by_ref = {e.ref: e for e in evidence}
    decisions = await _decisions(session, project_id)
    warnings: list[str] = []
    meta = AIMeta(project_id=project_id, entity_type="verification_run", entity_id=str(run.id))
    gw = gateway or (default_gateway() if run.use_ai else None)

    total = max(1, len(lines))
    await progress("interpreting", 0, total)
    ai_reason: str | None = None
    if run.use_ai and gw is not None:
        interps, outcome = await vai.interpret_lines(gw, lines, parents, meta)
        ai_reason = outcome.unavailable_reason
    else:
        interps = {l.id: interpret_by_rules(l) for l in lines}
    await progress("ranking", 0, total)

    work: list[tuple[LineInput, Interpretation, list[Candidate]]] = []
    for i, line in enumerate(lines):
        cands = generate_candidates(line, interps[line.id], evidence)
        work.append((line, interps[line.id], cands))
    ranked: dict[str, list[Candidate]] = {line.id: cands for line, _i, cands in work}
    ai_ranked: set[str] = set()
    if run.use_ai and gw is not None:
        ranked, outcome2 = await vai.rank_lines(gw, [w for w in work if not vai.not_verifiable_skip(w[0])], by_ref, meta)
        ranked = {**{line.id: cands for line, _i, cands in work}, **ranked}
        ai_reason = ai_reason or outcome2.unavailable_reason
        if outcome2.ai_used:
            ai_ranked = {lid for lid, cs in ranked.items() if any(c.source == "ai" for c in cs)}
    if run.use_ai and (gw is None or ai_reason or not ai_ranked) and lines:
        warnings.append(
            "AI mapping was not used"
            + (f" ({describe_reason(ai_reason)})" if ai_reason else "")
            + ": lines were matched with the built-in rules only, so more lines may need a person to check the mapping."
        )
    await progress("computing", total, total)
    results, missing = compute_all(lines, interps, ranked, evidence, decisions, ai_ranked)

    sheets = (await session.execute(select(DrawingSheet.annotations_status).where(DrawingSheet.project_id == project_id, DrawingSheet.drawing_id.in_(live_drawing_ids(project_id))))).scalars().all()
    if sheets and not any(s == "done" for s in sheets):
        warnings.append("No drawing annotations have been read yet, so quantities can only come from measured geometry. Use 'Read annotations' on the drawings first for better coverage.")
    elif sheets and sum(1 for s in sheets if s != "done") > 0:
        warnings.append(f"Annotations were read for {sum(1 for s in sheets if s == 'done')} of {len(sheets)} sheets.")
    if not evidence:
        warnings.append("This project has no measured geometry or annotations yet; every verifiable line will be reported as missing in the drawings.")

    await session.execute(delete(VerificationLine).where(VerificationLine.run_id == run.id))
    for order, (line, res) in enumerate(zip(lines, results, strict=True)):
        session.add(_row_from_result(run, ctx, order, line, res))
    for j, res in enumerate(missing):
        session.add(_row_from_result(run, ctx, len(lines) + j, None, res))

    counts, summary = _summary(results, missing, trade_of)
    run.counts, run.summary, run.warnings = counts, summary, warnings
    run.status, run.phase, run.error = "ready", None, None
    run.progress_done = run.progress_total = total
    run.finished_at = datetime.now(timezone.utc)
    ai_n, ai_cost = await _ai_usage(session, ctx, run.id)
    run.ai_calls, run.ai_cost_usd = ai_n, ai_cost
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.UPDATE, entity_type="verification_run", entity_id=run.id, project_id=project_id,
        payload={"event": "completed", "counts": counts, "ai_calls": ai_n, "ai_cost_usd": str(ai_cost)},
    )


async def _ai_usage(session: AsyncSession, ctx: RequestContext, run_id: UUID) -> tuple[int, Decimal]:
    # ai_calls is readable by lead_estimator+ only; the run is created by one, and a system context reads it anyway.
    n, cost = (
        await session.execute(
            select(func.count(), func.coalesce(func.sum(AiCall.cost_usd), 0)).where(
                AiCall.entity_type == "verification_run", AiCall.entity_id == str(run_id), AiCall.status.in_(("ok", "cached"))
            )
        )
    ).one()
    return int(n), Decimal(cost)


# ------------------------------------------------------------------ recompute (no AI)

async def recompute(session: AsyncSession, ctx: RequestContext, run: VerificationRun) -> None:
    """Re-derives every line from its STORED candidates and the current decisions, then rebuilds the
    'missing in BOQ' rows and the summary. Deterministic and free: no model is called."""
    project_id = run.project_id
    lines, _parents, trade_of = await load_lines(session, project_id)
    line_by_id = {l.id: l for l in lines}
    evidence = await load_evidence(session, project_id)
    decisions = await _decisions(session, project_id)
    stored = (
        await session.execute(
            select(VerificationLine).where(VerificationLine.run_id == run.id, VerificationLine.boq_line_item_id.is_not(None))
            .order_by(VerificationLine.sort_order)
        )
    ).scalars().all()
    interps: dict[str, Interpretation] = {}
    cands: dict[str, list[Candidate]] = {}
    ai_ranked: set[str] = set()
    inputs: list[LineInput] = []
    rows: dict[str, VerificationLine] = {}
    for row in stored:
        lid = str(row.boq_line_item_id)
        line = line_by_id.get(lid)
        if line is None:
            continue
        inputs.append(line)
        rows[lid] = row
        interps[lid] = _interp_from_json(row.interpretation, line)
        cands[lid] = [_cand_from_json(c) for c in row.candidates]
        if any(c.source == "ai" for c in cands[lid]):
            ai_ranked.add(lid)
    results, missing = compute_all(inputs, interps, cands, evidence, decisions, ai_ranked)
    for line, res in zip(inputs, results, strict=True):
        row = rows[line.id]
        row.vclass, row.method, row.mapped_by = res.vclass, res.method, res.mapped_by
        row.boq_quantity, row.boq_uom = res.boq_quantity, res.boq_uom
        row.drawing_quantity, row.delta, row.delta_pct = res.drawing_quantity, res.delta, res.delta_pct
        row.confidence, row.note, row.flags = res.confidence, res.note or None, res.flags
        row.evidence = [_ev_json(e) for e in res.evidence]
        row.updated_by = ctx.user_id
    await session.execute(
        delete(VerificationLine).where(VerificationLine.run_id == run.id, VerificationLine.boq_line_item_id.is_(None))
    )
    base = len(inputs)
    for j, res in enumerate(missing):
        session.add(_row_from_result(run, ctx, base + j, None, res))
    counts, summary = _summary(results, missing, trade_of)
    run.counts, run.summary = counts, summary
    run.updated_by = ctx.user_id
    await session.flush()


# ------------------------------------------------------------------ reading

async def list_lines(
    session: AsyncSession, run_id: UUID, *, vclass: str | None = None, trade: str | None = None,
    min_confidence: float | None = None, max_confidence: float | None = None, q: str | None = None,
    limit: int = 200, offset: int = 0,
) -> tuple[list[VerificationLine], int]:
    stmt = select(VerificationLine).where(VerificationLine.run_id == run_id)
    if vclass:
        stmt = stmt.where(VerificationLine.vclass == vclass)
    if trade:
        stmt = stmt.where(VerificationLine.trade_name == trade)
    if min_confidence is not None:
        stmt = stmt.where(VerificationLine.confidence >= min_confidence)
    if max_confidence is not None:
        stmt = stmt.where(VerificationLine.confidence <= max_confidence)
    if q:
        like = f"%{q}%"
        stmt = stmt.where((VerificationLine.description.ilike(like)) | (VerificationLine.item_no.ilike(like)))
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await session.execute(stmt.order_by(VerificationLine.sort_order).limit(limit).offset(offset))).scalars().all()
    return list(rows), total


async def get_line(session: AsyncSession, run_id: UUID, line_id: UUID) -> VerificationLine:
    row = (
        await session.execute(select(VerificationLine).where(VerificationLine.id == line_id, VerificationLine.run_id == run_id))
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError(f"Verification line {line_id} not found")
    return row


async def all_lines(session: AsyncSession, run_id: UUID) -> list[VerificationLine]:
    return list((await session.execute(select(VerificationLine).where(VerificationLine.run_id == run_id).order_by(VerificationLine.sort_order))).scalars().all())


async def search_evidence(session: AsyncSession, project_id: UUID, *, q: str | None, kind: str | None, limit: int = 50) -> list[Evidence]:
    all_ev = await load_evidence(session, project_id)
    if kind:
        all_ev = [e for e in all_ev if e.kind == kind]
    if q:
        needle = q.lower()
        all_ev = [e for e in all_ev if needle in e.label.lower() or needle in (e.layer or "").lower()]
    return all_ev[:limit]


# ------------------------------------------------------------------ decisions

async def set_mapping(
    session: AsyncSession, ctx: RequestContext, run_id: UUID, line_id: UUID, *, action: str, evidence_ref: str,
    note: str | None = None,
) -> VerificationLine:
    if action not in ("accept", "reject", "include", "clear"):
        raise ValidationAppError(f"Unknown mapping action {action!r}")
    run = await get_run(session, run_id)
    row = await get_line(session, run_id, line_id)
    if row.boq_line_item_id is None:
        raise ValidationAppError("Mappings apply to BOQ lines; this row is drawing quantity with no BOQ line")
    if run.status != "ready":
        raise ConflictError(f"The report is {run.status}; wait until it is ready")
    await assert_can_see_project(session, ctx, run.project_id)
    kind_prefix, _, raw_id = evidence_ref.partition(":")
    if kind_prefix not in ("m", "a", "g"):
        raise ValidationAppError("Unknown evidence reference")
    boq = (await session.execute(select(BoqLineItem).where(BoqLineItem.id == row.boq_line_item_id))).scalar_one()

    measurement_ids: list[UUID] = []  # the measurements behind this evidence (linked into reconciliation on accept)
    if kind_prefix == "g":  # a group of measurements (e.g. all 300mm sewer runs on one sheet)
        group = next((e for e in await load_evidence(session, run.project_id) if e.ref == evidence_ref), None)
        if group is None:
            raise NotFoundError("That drawing evidence was not found in this project")
        unit, measurement_ids = group.unit, [UUID(m) for m in group.members]
    else:
        try:
            evidence_id = UUID(raw_id)
        except ValueError as exc:
            raise ValidationAppError("Unknown evidence reference") from exc
        target: DrawingMeasurement | DrawingAnnotation | None
        if kind_prefix == "m":
            target = (await session.execute(select(DrawingMeasurement).where(DrawingMeasurement.id == evidence_id, DrawingMeasurement.project_id == run.project_id))).scalar_one_or_none()
            measurement_ids = [evidence_id]
        else:
            target = (await session.execute(select(DrawingAnnotation).where(DrawingAnnotation.id == evidence_id, DrawingAnnotation.project_id == run.project_id))).scalar_one_or_none()
        if target is None:
            raise NotFoundError("That drawing evidence was not found in this project")
        unit = target.unit
    if action in ("accept", "include") and boq.uom and unit and not unit_conversion.convertible(unit, boq.uom):
        raise ValidationAppError(f"Cannot count {unit!r} evidence toward a BOQ line measured in {boq.uom!r}: different dimensions")

    existing = (
        await session.execute(select(VerificationMapping).where(VerificationMapping.boq_line_item_id == boq.id, VerificationMapping.evidence_ref == evidence_ref))
    ).scalar_one_or_none()
    before = existing.decision if existing else None
    link_note: str | None = None
    if action == "clear":
        if existing is not None:
            await session.delete(existing)
        after = None
    else:
        decision = "exclude" if action == "reject" else "include"
        if existing is None:
            session.add(VerificationMapping(tenant_id=ctx.tenant_id, project_id=run.project_id, boq_line_item_id=boq.id,
                                            evidence_ref=evidence_ref, decision=decision, note=note, created_by=ctx.user_id, updated_by=ctx.user_id))
        else:
            existing.decision, existing.note, existing.updated_by = decision, note, ctx.user_id
        after = decision
    await session.flush()

    # Feed the existing reconciliation and the continuous-learning store (measurements only).
    if measurement_ids and action in ("accept", "include"):
        from app.services import boq as boq_service

        for mid in measurement_ids:
            try:
                await boq_service.add_measurement_link(session, ctx, boq.id, mid)
            except ValidationAppError as exc:  # unit incompatibility etc.: the decision stands, the link does not
                link_note = str(exc)
    if measurement_ids and action in ("accept", "reject"):
        for mid in measurement_ids:
            await record_feedback(
                session, ctx, project_id=run.project_id, match_type=MATCH_TYPE_BOQ_MEASUREMENT,
                query_embedding=list(boq.description_embedding) if boq.description_embedding is not None else None,
                target_id=mid, outcome="accepted" if action == "accept" else "rejected",
            )
    await audit.record(
        session, ctx, action=AuditAction.UPDATE, entity_type="verification_mapping", entity_id=boq.id, project_id=run.project_id,
        payload={"run_id": str(run.id), "action": action, "evidence_ref": evidence_ref, "before": before, "after": after,
                 "link_note": link_note},
    )
    await recompute(session, ctx, run)
    return await get_line(session, run_id, line_id)
