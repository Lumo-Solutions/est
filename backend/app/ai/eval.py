"""Evaluation harness (`make ai-eval`): golden sets for every AI task, run through the PRODUCTION code paths, with
accuracy, tokens, estimated cost and latency reported per provider and model.

    python -m app.ai.eval --out DIR [--tasks intake_classify,boq_pdf_rows,...]

* Golden sets are built from the synthetic demo pack (app/demo/ai_demo.py): no tenant data is ever sent, so the
  harness uses an in-memory store and does not go through tenant governance -- but an EXTERNAL provider still
  needs its key (AI_PROVIDER / AI_API_KEY / AI_MODEL) and this run spends real money on it.
* Against `mock` it reports the deterministic fixtures' honest baseline, not a model's quality.
* Results land in DIR as JSON + Markdown (`make ai-eval` copies them to docs/ai-eval/).
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.ai.gateway import AIGateway, AIMeta
from app.ai.store import MemoryStore
from app.core.config import get_settings
from app.core.context import RequestContext, system_context
from app.demo import ai_demo as demo

EVAL_TASKS = ["intake_classify", "boq_pdf_rows", "drawing_annotations", "boq_interpret", "evidence_rank", "cost_choose", "markup_advise"]


@dataclass(slots=True)
class TaskResult:
    task: str
    cases: int
    score: float  # 0..1
    passed: int
    details: list[dict[str, Any]] = field(default_factory=list)
    errors: int = 0
    calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    avg_latency_ms: float = 0.0
    seconds: float = 0.0


def _f1(expected: set, got: set) -> float:
    if not expected and not got:
        return 1.0
    tp = len(expected & got)
    if tp == 0:
        return 0.0
    p, r = tp / len(got), tp / len(expected)
    return 2 * p * r / (p + r)


# ================================================================== golden sets

def _pack() -> dict[str, bytes]:
    return {p.rsplit("/", 1)[-1]: d for p, d in demo.build_pack().items()}


def _classification_cases() -> list[dict]:

    cases: list[dict] = []
    for path, data in demo.build_pack().items():
        name = path.rsplit("/", 1)[-1]
        ext = name.rsplit(".", 1)[-1].lower()
        cases.append({"name": name, "folder": path.rsplit("/", 1)[0].split(PACK_ROOT_PREFIX)[-1], "filename": name, "ext": ext,
                      "data": data, "expected": demo.EXPECTED_CLASSIFICATION[name]})
    extra = [
        ("Minutes of clarification meeting 2.pdf", "Minutes of tender clarification meeting No. 2. Request for information responses: RFI 14, RFI 15.", "clarification"),
        ("letter_client_2026-03-02.pdf", "Dear Sirs, further to our letter of 2 March, we confirm the tender submission date. Yours faithfully, Client Representative", "correspondence"),
        ("BH logs.pdf", "GEOTECHNICAL INVESTIGATION REPORT. Borehole logs BH-01 to BH-12. Groundwater encountered at 2.4 m.", "site_investigation"),
        ("Form of Tender.pdf", "FORM OF TENDER. The undersigned offers to execute the works. Bid Bond of 2% attached. APPENDIX TO TENDER.", "tender_forms"),
        ("Master programme.pdf", "MASTER PROGRAMME - baseline schedule. Activity, start, finish, duration. Gantt chart attached.", "programme"),
        ("ITT.pdf", "INSTRUCTIONS TO TENDERERS. Clause 1: Tenders shall be submitted in sealed envelopes not later than 12:00.", "tender_instructions"),
        ("Addendum 2.pdf", "ADDENDUM No. 2. This addendum amends the Bill of Quantities item 4.1.", "addendum"),
        ("Technical spec roads.pdf", "SPECIFICATION - ROADWORKS. SECTION 32 12 16 ASPHALT PAVING. PART 1 - GENERAL.", "specification"),
    ]
    for name, text, exp in extra:
        cases.append({"name": name, "folder": "", "filename": name, "ext": "pdf", "text": text, "expected": exp})
    return cases


PACK_ROOT_PREFIX = demo.PACK_ROOT + "/"


async def eval_intake_classify(gw: AIGateway, meta: AIMeta) -> TaskResult:
    from app.intake.classifier import classify_with_model
    from app.intake.extract import DocContent, extract_content

    details, ok = [], 0
    cases = _classification_cases()
    for c in cases:
        if "data" in c:
            content = extract_content(filename=c["filename"], ext=c["ext"], sniffed=c["ext"], data=c["data"])
        else:
            content = DocContent(filename=c["filename"], ext=c["ext"], sniffed=c["ext"], text=c["text"], page_texts=[c["text"]], has_text_layer=True)
        try:
            got = await classify_with_model(filename=c["filename"], content=content, candidates=[], folder_path=c["folder"], meta=meta)
            cls = got.doc_class
        except Exception as exc:  # noqa: BLE001
            cls = f"error:{type(exc).__name__}"
        ok += cls == c["expected"]
        details.append({"case": c["name"], "expected": c["expected"], "got": cls})
    return TaskResult("intake_classify", len(cases), ok / len(cases), ok, details)


def _pdf_pages_truth(data: bytes) -> list[tuple[int, set[tuple[str, float]]]]:
    """Expected (item_no, quantity) per page: the deterministic reader for the text pages, the BOQ list for the scanned one."""
    from app.boq.pdf_reader import read_pdf_boq

    out = []
    scanned_items = {b.item_no: b for b in demo.BOQ[16:]}
    for p in read_pdf_boq(data):
        if p.status == "table":
            out.append((p.page, {(r.item_no or "", float(r.quantity or 0.0)) for r in p.rows}))
        elif p.status == "needs_ai":
            out.append((p.page, {(n, float(b.qty or 0.0)) for n, b in scanned_items.items()}))
    return out


async def eval_boq_pdf_rows(gw: AIGateway, meta: AIMeta) -> TaskResult:
    from app.boq.pdf_reader import PageResult
    from app.boq.pdf_ai import _read_page_with_ai

    data = _pack()["BOQ Rev 0 (print copy).pdf"]
    details, scores = [], []
    for page, truth in _pdf_pages_truth(data):
        pr = PageResult(page, "needs_ai")
        warnings: list[str] = []
        await _read_page_with_ai(gw, data, pr, meta, warnings)  # forces the AI on every page, clean or not
        got = {(r.item_no or "", float(r.quantity or 0.0)) for r in pr.rows}
        s = _f1(truth, got)
        scores.append(s)
        details.append({"case": f"page {page}", "f1": round(s, 3), "expected": len(truth), "got": len(got), "status": pr.status})
    return TaskResult("boq_pdf_rows", len(scores), sum(scores) / max(1, len(scores)), sum(1 for s in scores if s >= 0.9), details)


def _sheet_texts() -> dict[str, tuple[str, set[tuple[str, float]]]]:
    import pdfplumber

    from app.takeoff.dxf import index_dxf

    pack = _pack()
    dxf_text = "\n".join(t.text_value for lay in index_dxf(pack["C-101 Road and Drainage Plan Rev B.dxf"]) for t in lay.text_entities)
    with pdfplumber.open(io.BytesIO(pack["L-201 Landscape Plan Rev A.pdf"])) as pdf:
        pdf_text = pdf.pages[0].extract_text() or ""
    return {
        "C-101 (DXF text)": (dxf_text, {("length", 100.0), ("length", 90.0), ("length", 56.0), ("count", 12.0), ("length", 1040.0), ("volume", 12480.0), ("area", 7300.0)}),
        "L-201 (PDF text)": (pdf_text, {("area", 4200.0), ("area", 3100.0), ("count", 46.0)}),
    }


async def eval_drawing_annotations(gw: AIGateway, meta: AIMeta) -> TaskResult:
    from app.takeoff.annotations import read_sheet

    details, scores = [], []
    for name, (text, truth) in _sheet_texts().items():
        try:
            reading = await read_sheet(gw, page_number=1, sheet_text=text, image_png=None, meta=meta)
            got = {(a.kind, round(float(a.value), 1)) for a in reading.annotations if a.value is not None and a.kind in ("length", "area", "volume", "count")}
        except Exception as exc:  # noqa: BLE001
            got = set()
            details.append({"case": name, "error": type(exc).__name__})
        s = _f1(truth, got)
        scores.append(s)
        details.append({"case": name, "f1": round(s, 3), "missed": sorted(truth - got), "extra": sorted(got - truth)})
    return TaskResult("drawing_annotations", len(scores), sum(scores) / len(scores), sum(1 for s in scores if s >= 0.9), details)


def _demo_lines():
    from app.verification.engine import LineInput

    return [LineInput(id=b.item_no, item_no=b.item_no, description=b.description, uom=b.uom, quantity=b.qty, trade_name=None) for b in demo.BOQ if b.expected and b.expected != "not_verifiable"]


def _demo_evidence():
    from app.verification.engine import Evidence

    def m(ref, label, value, unit="m", **kw):
        return Evidence(ref=ref, kind="measurement", value=value, unit=unit, label=label, drawing_id="d1", sheet_id="s1", page=1, **kw)

    def a(ref, text, value, unit, ann_kind):
        return Evidence(ref=ref, kind="annotation", value=value, unit=unit, label=text, drawing_id="d1", sheet_id="s1", page=1, ann_kind=ann_kind, confidence=0.85)

    return [
        m("g:sewer300", "pipe_network_topology pipe_run_length_m layer=SEWER-300 trade=unclassified (3 runs summed)", 246.0, layer="SEWER-300"),
        m("g:sewer150", "pipe_network_topology pipe_run_length_m layer=SEWER-150 trade=unclassified (2 runs summed)", 150.0, layer="SEWER-150"),
        m("g:storm450", "pipe_network_topology pipe_run_length_m layer=STORM-450 trade=unclassified (1 run summed)", 80.0, layer="STORM-450"),
        m("m:align", "alignment alignment_length_m layer=ROAD-CL trade=unclassified", 520.0, layer="ROAD-CL"),
        m("m:corridor", "corridor_area corridor_area_m2 layer=ROAD trade=unclassified", 7280.0, unit="m2", layer="ROAD"),
        a("a:exc", "EXCAVATION 12,480 m3 (ROADWAY)", 12480.0, "m3", "volume"),
        a("a:mh", "12 nos PRECAST MANHOLE 1200mm (SEE SCHEDULE)", 12.0, "nos", "count"),
        a("a:kerb", "KERB L=1,040.0m PRECAST CONCRETE KERB TYPE A 300x150", 1040.0, "m", "length"),
        a("a:asph", "ASPHALT WEARING COURSE 50mm 7,300 m2", 7300.0, "m2", "area"),
        a("a:top", "TOPSOIL 4,200 m2 (200mm THICK)", 4200.0, "m2", "area"),
        a("a:turf", "TURF 3,100 m2", 3100.0, "m2", "area"),
        a("a:tree", "TREES 46 nos GHAF 2.5m HEIGHT", 46.0, "nos", "count"),
    ]


# acceptable evidence per BOQ line (empty set = nothing in the drawings should be selected)
_MAPPING_TRUTH: dict[str, set[str]] = {
    "1.1": {"a:exc"}, "1.2": {"m:corridor"}, "1.3": set(), "2.1": {"g:sewer300"}, "2.2": {"g:sewer150"}, "2.3": {"a:mh"}, "2.4": set(),
    "3.1": {"m:corridor", "a:asph"}, "3.2": {"a:kerb"}, "3.3": {"m:align"}, "3.4": set(), "4.1": set(), "4.2": set(),
    "5.1": {"a:top"}, "5.2": {"a:tree"}, "5.3": {"a:turf"},
}


async def eval_boq_interpret(gw: AIGateway, meta: AIMeta) -> TaskResult:
    from app.verification import ai as vai

    lines = _demo_lines()
    interps, outcome = await vai.interpret_lines(gw, lines, {}, meta)
    truth = {"2.1": (300.0, {"upvc"}), "2.2": (150.0, {"upvc"}), "2.3": (1200.0, {"precast", "concrete", "precast concrete"})}
    details, ok = [], 0
    for lid, (size, mats) in truth.items():
        i = interps[lid]
        good = i.size_mm == size and (i.material or "").lower() in mats
        ok += good
        details.append({"case": lid, "ok": good, "expected": {"size_mm": size, "material": sorted(mats)}, "got": {"size_mm": i.size_mm, "material": i.material, "source": i.source}})
    return TaskResult("boq_interpret", len(truth), ok / len(truth), ok, details, errors=0 if outcome.ai_used else 1)


async def eval_evidence_rank(gw: AIGateway, meta: AIMeta) -> TaskResult:
    from app.verification import ai as vai
    from app.verification.engine import generate_candidates, interpret_by_rules

    lines, evidence = _demo_lines(), _demo_evidence()
    by_ref = {e.ref: e for e in evidence}
    work = []
    for line in lines:
        interp = interpret_by_rules(line)
        work.append((line, interp, generate_candidates(line, interp, evidence)))
    ranked, outcome = await vai.rank_lines(gw, work, by_ref, meta)
    details, ok = [], 0
    for line in lines:
        truth = _MAPPING_TRUTH.get(line.id, set())
        selected = {c.ref for c in ranked.get(line.id, []) if c.source == "ai" and c.selected}
        good = (selected <= truth and bool(selected)) if truth else not selected
        ok += good
        details.append({"case": f"{line.item_no} {line.description[:40]}", "expected": sorted(truth), "selected": sorted(selected), "ok": good})
    return TaskResult("evidence_rank", len(lines), ok / len(lines), ok, details, errors=0 if outcome.ai_used else 1)


def _cost_cases():
    from app.pricing.engine import CostCandidate

    def lib(code, rate=None):
        it = next(i for i in demo.COST_LIBRARY if i.code == f"{demo.COST_CODE_PREFIX}{code}")
        return CostCandidate(ref=f"c:{code}", ctype="library", label=f"{it.code}: {it.description}", rate=Decimal(str(rate or it.rate)), currency="AED", uom=it.uom, apply={})

    def quote(qid, vendor, rate, desc, uom):
        return CostCandidate(ref=f"q:{qid}", ctype="quote", label=f"{vendor}: {desc}", rate=Decimal(str(rate)), currency="AED", uom=uom, vendor=vendor, apply={})

    b = {x.item_no: x for x in demo.BOQ}
    # (item, candidates, acceptable refs; empty set = the right answer is to select nothing)
    return [
        ("2.1", [quote("2.1", "National Pipes Trading", 98.0, b["2.1"].description, "m"), lib("PP-UPVC-300"), lib("PP-UPVC-150"), lib("PP-UPVC-S-300")], {"q:2.1", "c:PP-UPVC-300"}),
        ("2.2", [lib("PP-UPVC-150"), lib("PP-UPVC-300"), lib("PP-UPVC-200")], {"c:PP-UPVC-150"}),
        ("2.3", [lib("MH-1200-up"), lib("MH-1500-up"), lib("CP-001"), lib("CV-001")], {"c:MH-1200-up"}),
        ("2.4", [lib("MH-1200-up"), lib("WM-CON-1"), lib("UT-DIV-1")], set()),
        ("3.1", [lib("AS-001"), lib("AS-002"), lib("AS-006")], {"c:AS-001"}),
        ("3.2", [lib("KB-001"), lib("KB-002"), lib("KB-007")], {"c:KB-001"}),
        ("3.4", [lib("RM-003"), lib("RM-004"), lib("RM-001")], {"c:RM-003", "c:RM-004"}),
        ("4.1", [lib("SL-COL-8"), lib("SL-COL-10"), lib("SL-LUM-90")], {"c:SL-COL-8"}),
        ("5.2", [lib("LS-TREE-GHAF"), lib("LS-TREE-PALM"), lib("LS-SHRUB")], {"c:LS-TREE-GHAF"}),
    ]


async def eval_cost_choose(gw: AIGateway, meta: AIMeta) -> TaskResult:
    from app.pricing import ai as pai

    boq = {x.item_no: x for x in demo.BOQ}
    cases = _cost_cases()
    work = [{"id": item, "item_no": item, "description": boq[item].description, "uom": boq[item].uom, "quantity": f"{boq[item].qty:,.2f}"} for item, _c, _t in cases]
    cmap = {item: cands for item, cands, _t in cases}
    out, outcome = await pai.choose_costs(gw, work, cmap, meta)
    details, ok = [], 0
    for item, _cands, truth in cases:
        ranked = out.get(item, {}).get("ranked", [])
        selected = {ref for ref, _s, sel, _w in ranked if sel}
        good = (bool(selected) and selected <= truth) if truth else not selected
        ok += good
        details.append({"case": f"{item} {boq[item].description[:40]}", "expected": sorted(truth), "selected": sorted(selected), "ok": good})
    return TaskResult("cost_choose", len(cases), ok / len(cases), ok, details, errors=0 if outcome.ai_used else 1)


async def eval_markup_advise(gw: AIGateway, meta: AIMeta) -> TaskResult:
    from app.pricing import ai as pai
    from app.pricing.engine import win_rate_by_margin

    hist = win_rate_by_margin([{"margin_on_sell_pct": t.margin_on_sell_pct, "outcome": t.outcome, "our_price": t.our_price, "winning_price": t.winning_price} for t in demo.history()])
    contexts = [
        {"project": {"name": "Demo A", "size_band": "medium", "currency": "AED"}, "settings": {"plant_pct": 0, "overhead_pct": 5, "volatility_pct": 3, "markup_pct": 8},
         "trades": [{"trade": "Utilities", "lines": 20, "direct_cost": "3,000,000", "flagged_lines": 6, "unresolved_lines": 2}], "history": hist,
         "totals": {"direct_cost": "9,000,000", "lines": 60, "flagged_lines": 12, "unresolved_lines": 4}},
        {"project": {"name": "Demo B", "size_band": "small", "currency": "AED"}, "settings": {"plant_pct": 0, "overhead_pct": 6, "volatility_pct": 4, "markup_pct": 10},
         "trades": [], "history": [], "totals": {"direct_cost": "1,500,000", "lines": 30, "flagged_lines": 0, "unresolved_lines": 0}},
    ]
    details, ok = [], 0
    for i, ctx in enumerate(contexts, start=1):
        advice, _o = await pai.advise_markup(gw, ctx, meta)
        checks = {}
        if advice:
            labels = [o["label"] for o in advice["options"]]
            mk = [o["markup_pct"] for o in advice["options"]]
            checks = {"three_options": labels == ["competitive", "balanced", "protective"], "ordered": mk == sorted(mk),
                      "in_range": all(0 <= v <= 40 for v in mk), "reasoned": all(o["rationale"] for o in advice["options"])}
        good = bool(checks) and all(checks.values())
        ok += good
        details.append({"case": f"context {i}", "checks": checks, "ok": good})
    return TaskResult("markup_advise", len(contexts), ok / len(contexts), ok, details)


RUNNERS = {
    "intake_classify": eval_intake_classify, "boq_pdf_rows": eval_boq_pdf_rows, "drawing_annotations": eval_drawing_annotations,
    "boq_interpret": eval_boq_interpret, "evidence_rank": eval_evidence_rank, "cost_choose": eval_cost_choose, "markup_advise": eval_markup_advise,
}
# the tasks each runner exercises, for cost/latency accounting from the audit rows
_CALL_TASKS = {"boq_interpret": {"boq_interpret"}, "evidence_rank": {"evidence_rank"}}


def build_gateway() -> tuple[AIGateway, MemoryStore, RequestContext]:
    settings = get_settings()
    ctx = system_context(uuid.uuid4())
    store = MemoryStore(external_allowed=True)   # synthetic golden sets only: no tenant data leaves, so no tenant governance
    return AIGateway(settings=settings, store=store, ctx=ctx), store, ctx


async def run_eval(tasks: list[str] | None = None) -> dict[str, Any]:
    from app.ai.factory import set_gateway_override

    gw, store, _ctx = build_gateway()
    if gw.provider.external and not gw.provider.is_configured():
        return {"skipped": True, "reason": "AI provider selected but AI_API_KEY / AI_MODEL are not set", "provider": gw.provider.name}
    set_gateway_override(lambda _s: gw)   # production code that builds its own gateway (the classifier) uses this one
    meta = AIMeta(project_id=None, entity_type="eval", entity_id="golden")
    results: list[TaskResult] = []
    try:
        for name in tasks or EVAL_TASKS:
            before = len(store.calls)
            started = time.monotonic()
            res = await RUNNERS[name](gw, meta)
            res.seconds = round(time.monotonic() - started, 2)
            calls = [c for c in store.calls[before:] if c.status in ("ok", "cached", "error")]
            res.calls = len(calls)
            res.errors += sum(1 for c in calls if c.status == "error")
            res.tokens_in, res.tokens_out = sum(c.tokens_in for c in calls), sum(c.tokens_out for c in calls)
            res.cost_usd = float(sum((c.cost_usd for c in calls), Decimal(0)))
            lat = [c.latency_ms for c in calls if c.status == "ok"]
            res.avg_latency_ms = round(sum(lat) / len(lat), 1) if lat else 0.0
            results.append(res)
    finally:
        set_gateway_override(None)
    settings = get_settings()
    models = sorted({c.model for c in store.calls})
    total = sum(r.cost_usd for r in results)
    return {
        "provider": gw.provider.name, "models": models, "date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": "mock = deterministic fixtures (an honest baseline of the fixtures, not of a model)" if gw.provider.name == "mock" else "",
        "results": [asdict(r) for r in results],
        "mean_score": round(sum(r.score for r in results) / max(1, len(results)), 3),
        "total_cost_usd": round(total, 4),
        "config": {"ai_model": settings.ai_model, "classify": settings.ai_model_classify, "vision": settings.ai_model_vision, "reasoning": settings.ai_model_reasoning},
    }


def to_markdown(report: dict[str, Any]) -> str:
    if report.get("skipped"):
        return f"# AI evaluation skipped\n\n{report['reason']}.\n"
    lines = [
        f"# AI evaluation: {report['provider']} ({', '.join(report['models']) or 'n/a'})", "",
        f"Run {report['date']}. Mean score **{report['mean_score']:.0%}**. Estimated cost ${report['total_cost_usd']:.4f}.", "",
    ]
    if report.get("note"):
        lines += [f"> {report['note']}", ""]
    lines += ["| Task | Cases | Score | Passed | Calls | Tokens in/out | Est. cost | Avg latency |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for r in report["results"]:
        lines.append(f"| {r['task']} | {r['cases']} | {r['score']:.0%} | {r['passed']} | {r['calls']} | {r['tokens_in']}/{r['tokens_out']} | ${r['cost_usd']:.4f} | {r['avg_latency_ms']:.0f} ms |")
    lines += ["", "## Misses", ""]
    any_miss = False
    for r in report["results"]:
        for d in r["details"]:
            if d.get("ok") is False or (d.get("f1") is not None and d["f1"] < 0.9) or (d.get("expected") is not None and d.get("got") is not None and d["expected"] != d["got"] and "f1" not in d and "ok" not in d):
                any_miss = True
                lines.append(f"- **{r['task']}** {d}")
    if not any_miss:
        lines.append("None.")
    return "\n".join(lines) + "\n"


def write_report(report: dict[str, Any], out_dir: str) -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    provider = report.get("provider", "unknown")
    paths = [out / f"eval-{provider}-{stamp}.json", out / f"latest-{provider}.md"]
    paths[0].write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    paths[1].write_text(to_markdown(report), encoding="utf-8")
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.ai.eval")
    parser.add_argument("--out", required=True)
    parser.add_argument("--tasks", default="")
    args = parser.parse_args(argv)
    tasks = [t for t in args.tasks.split(",") if t] or None
    if tasks and any(t not in RUNNERS for t in tasks):
        print(f"unknown task in {tasks}; choose from {EVAL_TASKS}", file=sys.stderr)
        return 2
    report = asyncio.run(run_eval(tasks))
    if report.get("skipped"):
        print(f"SKIPPED: {report['reason']} (provider {report['provider']}). Fill the AI_* keys in deploy/.env and re-run.")
        return 0
    for p in write_report(report, args.out):
        print(f"wrote {p}")
    print(to_markdown(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
