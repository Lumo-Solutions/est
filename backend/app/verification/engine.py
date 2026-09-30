"""Drawing <-> BOQ quantity verification: the deterministic core (docs/ai-plan.md §5).

Pure functions over plain dataclasses: no database, no model. The AI only
*proposes* which drawing evidence belongs to a BOQ line (interpretation and
ranking, see app/verification/ai.py); every quantity here is computed from
evidence a person can open on the drawing:

  1. measured geometry (drawing_measurements, override-aware), else
  2. annotated values the AI READ from the sheet (drawing_annotations), else
  3. nothing: the line is 'missing_in_drawings' (or 'not_verifiable').

**A visual estimate is never a quantity.** Comparison, tolerance and unit
conversion reuse app.boq.reconciliation.reconcile / app.boq.units, so a
verification 'match' means exactly what a reconciliation 'match' means.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from rapidfuzz import fuzz

from app.boq import units as unit_conversion
from app.boq.reconciliation import DiscrepancyClass, ReconciliationConfig, reconcile

# ---------------------------------------------------------------- constants

RULES_ATTACH_MIN_SCORE = 0.4  # rules-only mapping (AI unavailable): attach candidates at/above this
AI_ATTACH_MIN_SCORE = 0.5
MAX_CANDIDATES = 8
MAX_ATTACHED = 4
ANNOTATED_FACTOR = 0.85
MULTI_ANNOTATION_FACTOR = 0.7
MISSING_IN_BOQ_MIN_CONFIDENCE = 0.5
DUPLICATE_ANNOTATION_TOLERANCE_PCT = 5.0
TOP_RISKS = 10


class VClass(StrEnum):
    MATCH = "match"
    VARIANCE = "variance"
    MISSING_IN_DRAWINGS = "missing_in_drawings"
    NOT_VERIFIABLE = "not_verifiable"
    MISSING_IN_BOQ = "missing_in_boq"


class Method(StrEnum):
    MEASURED = "measured"
    ANNOTATED = "annotated"
    NONE = "none"


# Items that describe money or effort, not something drawn.
_NOT_DRAWN = re.compile(
    r"provisional\s+sum|prime\s+cost|\bpc\s+sum\b|\bp\.?s\.?\s+sum\b|preliminar|general\s+requirements|contingenc|"
    r"day\s*works?|attendance\s+on|insurance|mobili[sz]ation|demobili[sz]ation|site\s+establishment|"
    r"as[-\s]?built\s+(?:drawings|records)|health\s+and\s+safety|supervision|testing\s+and\s+commissioning|"
    r"warranty|maintenance\s+period|allowance\s+for",
    re.I,
)
_LUMP_UNITS = {"ls", "lot", "sum", "ps", "pc", "prov", "l.s.", "l/s", "item", "lumpsum"}

_SIZE = re.compile(r"(?:dn|d|ø|Ø|dia\.?\s*)?\s*(\d{2,4})\s*(?:mm)?\s*(?:dia(?:meter)?|ø|nb)?", re.I)
_MATERIALS = (
    "upvc", "pvc", "hdpe", "grp", "di", "ductile iron", "concrete", "reinforced concrete", "rc", "steel", "cast iron",
    "asphalt", "bituminous", "granite", "precast", "block", "kerb", "brick", "geotextile", "sand", "aggregate",
)
_WORK_WORDS = {
    "excavat": "excavation", "backfill": "backfill", "trench": "trench", "pipe": "pipe", "sewer": "pipe",
    "drain": "drainage", "manhole": "manhole", "chamber": "chamber", "gully": "gully", "kerb": "kerb",
    "asphalt": "asphalt", "surfac": "surfacing", "sub-base": "subbase", "subbase": "subbase", "marking": "marking",
    "landscap": "landscape", "planting": "planting", "lighting": "lighting", "cable": "cable", "duct": "duct",
    "pave": "paving", "concrete": "concrete", "fence": "fence", "signage": "signage", "topsoil": "topsoil",
}


# ---------------------------------------------------------------- data

@dataclass(frozen=True, slots=True)
class LineInput:
    id: str
    item_no: str
    description: str
    uom: str | None
    quantity: float | None
    trade_id: str | None = None
    trade_name: str | None = None
    is_heading: bool = False
    tolerance_pct: float = 2.0


@dataclass(frozen=True, slots=True)
class Evidence:
    ref: str  # 'm:<uuid>' | 'a:<uuid>'
    kind: str  # measurement | annotation
    value: float
    unit: str | None
    label: str  # text the matcher and the AI read
    drawing_id: str | None = None
    sheet_id: str | None = None
    page: int | None = None
    bbox: list[float] | None = None
    layer: str | None = None
    trade_id: str | None = None
    trade_name: str | None = None
    confidence: float = 1.0
    material: str | None = None
    ann_kind: str | None = None  # annotation kind: length/area/volume/count/diameter/level/other
    # For a grouped measurement (all pipe runs on one layer of one sheet): the member measurement ids.
    members: tuple[str, ...] = ()

    def dimension(self) -> unit_conversion.Dimension | None:
        return unit_conversion.unit_dimension(self.unit) if self.unit else None


@dataclass(slots=True)
class Interpretation:
    work_type: str | None = None
    material: str | None = None
    size_mm: float | None = None
    unit: str | None = None
    trade: str | None = None
    source: str = "rules"  # ai | rules
    keywords: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Candidate:
    ref: str
    score: float
    reason: str = ""
    source: str = "rules"  # ai | rules
    selected: bool = False


@dataclass(slots=True)
class LineResult:
    line_id: str | None
    vclass: str
    method: str = Method.NONE.value
    mapped_by: str = "none"  # ai | rules | user | none
    boq_quantity: float | None = None
    boq_uom: str | None = None
    drawing_quantity: float | None = None
    delta: float | None = None
    delta_pct: float | None = None
    confidence: float = 0.0
    note: str = ""
    flags: list[str] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)  # attached and used for the quantity
    candidates: list[Candidate] = field(default_factory=list)
    interpretation: Interpretation | None = None


# ---------------------------------------------------------------- verifiability

def not_verifiable_reason(line: LineInput) -> str | None:
    text = f"{line.item_no} {line.description}"
    if line.is_heading:
        return "Section heading (no quantity)"
    if _NOT_DRAWN.search(text):
        return "Provisional sum, preliminaries or other item that is not drawn"
    uom = (line.uom or "").strip().lower()
    if not uom:
        return "No unit of measure on the BOQ line"
    if uom in _LUMP_UNITS and unit_conversion.unit_dimension(uom) is None:
        return f"Lump-sum unit {line.uom!r}: not a measurable quantity"
    if line.quantity is None:
        return "BOQ line has no quantity"
    if unit_conversion.unit_dimension(line.uom or "") is None:
        return f"Unit {line.uom!r} is not one the platform can compare"
    return None


# ---------------------------------------------------------------- interpretation (rules fallback)

def interpret_by_rules(line: LineInput) -> Interpretation:
    text = line.description.lower()
    material = next((m for m in sorted(_MATERIALS, key=len, reverse=True) if re.search(rf"\b{re.escape(m)}\b", text)), None)
    size = None
    m = re.search(r"(?:dn|ø|dia\.?\s*)\s*(\d{2,4})|(\d{2,4})\s*mm", text)
    if m:
        size = float(m.group(1) or m.group(2))
    work = next((w for key, w in _WORK_WORDS.items() if key in text), None)
    kws = [w for w in {work, material} if w]
    if size:
        kws.append(f"{int(size)}")
    return Interpretation(work, material, size, line.uom, line.trade_name, "rules", kws)


# ---------------------------------------------------------------- candidates

def _tokens(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", text.lower())


def score_candidate(line: LineInput, interp: Interpretation, ev: Evidence) -> tuple[float, str]:
    """0..1 plausibility that `ev` belongs to `line`, plus a short human reason."""
    reasons: list[str] = []
    query = _tokens(" ".join([line.description, *interp.keywords, interp.work_type or "", interp.material or ""]))
    label = _tokens(f"{ev.label} {ev.material or ''} {ev.layer or ''} {ev.trade_name or ''}")
    text = fuzz.token_set_ratio(query, label) / 100.0 if query.strip() and label.strip() else 0.0
    kws = [k.lower() for k in interp.keywords if k]
    if kws and label.strip():
        overlap = sum(1 for k in kws if k in label) / len(kws)
        text = max(text, overlap)
    if text >= 0.6:
        reasons.append("description matches")
    trade = 0.0
    if line.trade_id and ev.trade_id and line.trade_id == ev.trade_id:
        trade = 1.0
        reasons.append("same trade")
    elif line.trade_name and ev.trade_name and _tokens(line.trade_name).strip() == _tokens(ev.trade_name).strip():
        trade = 1.0
        reasons.append("same trade")
    size = 0.0
    if interp.size_mm:
        needle = f"{int(interp.size_mm)}"
        if needle in label.replace(" ", "") or needle in label.split():
            size = 1.0
            reasons.append(f"size {needle}")
    material = 0.0
    if interp.material and ev.material and interp.material.lower() in ev.material.lower():
        material = 1.0
        reasons.append(f"material {interp.material}")
    # Annotated values printed with a matching kind/unit are direct evidence.
    unit_bonus = 0.0
    if ev.kind == "annotation" and line.uom and ev.unit and unit_conversion.convertible(ev.unit, line.uom):
        unit_bonus = 1.0
    score = 0.45 * text + 0.2 * trade + 0.15 * size + 0.1 * material + 0.1 * unit_bonus
    return round(min(score, 1.0), 3), ", ".join(reasons) or "weak textual similarity"


def compatible(line: LineInput, ev: Evidence) -> bool:
    return bool(line.uom and ev.unit and unit_conversion.convertible(ev.unit, line.uom))


def generate_candidates(
    line: LineInput, interp: Interpretation, evidence: list[Evidence], limit: int = MAX_CANDIDATES
) -> list[Candidate]:
    scored = []
    for ev in evidence:
        if not compatible(line, ev):
            continue
        s, why = score_candidate(line, interp, ev)
        scored.append(Candidate(ev.ref, s, why, "rules"))
    scored.sort(key=lambda c: (-c.score, c.ref))
    return scored[:limit]


# ---------------------------------------------------------------- per-line computation

def compute_line(
    line: LineInput,
    interp: Interpretation,
    candidates: list[Candidate],
    evidence_by_ref: dict[str, Evidence],
    *,
    include: set[str] | None = None,
    exclude: set[str] | None = None,
    ai_ranked: bool = False,
) -> LineResult:
    """Deterministic. `candidates` are the (AI-ranked or rules) proposals; `include`/`exclude` are
    a person's decisions and always win. Re-running with the same inputs gives the same answer."""
    include, exclude = include or set(), exclude or set()
    base = LineResult(
        line_id=line.id, vclass=VClass.MISSING_IN_DRAWINGS.value, boq_quantity=line.quantity, boq_uom=line.uom,
        interpretation=interp, candidates=list(candidates),
    )
    reason = not_verifiable_reason(line)

    attached: list[tuple[str, str]] = []  # (ref, mapped_by)
    seen: set[str] = set()
    for c in candidates:
        if c.ref in exclude or c.ref in seen or c.ref not in evidence_by_ref:
            continue
        if c.source == "ai":
            take = c.selected and c.score >= AI_ATTACH_MIN_SCORE
        else:
            take = c.score >= RULES_ATTACH_MIN_SCORE
        if take:
            attached.append((c.ref, c.source))
            seen.add(c.ref)
    for ref in sorted(include):
        if ref not in evidence_by_ref:
            continue
        if ref in seen:  # already proposed: a person confirming it makes it theirs
            attached = [(r, "user" if r == ref else by) for r, by in attached]
        else:
            attached.append((ref, "user"))
            seen.add(ref)
    attached = attached[: MAX_ATTACHED + len(include)]

    used = [(evidence_by_ref[r], by) for r, by in attached if compatible(line, evidence_by_ref[r])]
    dropped = [r for r, _ in attached if not compatible(line, evidence_by_ref[r])]
    if dropped:
        base.flags.append("unit_mismatch_dropped")
    measured = [(e, by) for e, by in used if e.kind == "measurement"]
    annotated = [(e, by) for e, by in used if e.kind == "annotation"]

    if reason and not used:
        base.vclass = VClass.NOT_VERIFIABLE.value
        base.note = reason
        return base

    if not used or line.uom is None:
        base.note = "No drawing evidence found for this line" if not reason else reason
        base.vclass = VClass.NOT_VERIFIABLE.value if reason else VClass.MISSING_IN_DRAWINGS.value
        return base

    pool, method = (measured, Method.MEASURED) if measured else (annotated, Method.ANNOTATED)
    total = 0.0
    for ev, _by in pool:
        converted = unit_conversion.convert(ev.value, ev.unit or "", line.uom)
        if converted is None:  # cannot happen after compatible(), kept as a guard
            continue
        total += converted
    mapped_by = "user" if any(by == "user" for _e, by in pool) else pool[0][1]

    if method is Method.ANNOTATED and len(pool) > 1:
        base.flags.append("multiple_annotations")
        base.note = "Several annotations were added together; check they are not the same length printed twice"

    result = reconcile(
        line.quantity, line.uom, total, line.uom, ReconciliationConfig(tolerance_pct=line.tolerance_pct)
    )
    base.vclass = VClass.MATCH.value if result.discrepancy_class == DiscrepancyClass.MATCH.value else VClass.VARIANCE.value
    if result.discrepancy_class == DiscrepancyClass.UNMATCHED.value:  # incomparable (defensive)
        base.vclass = VClass.MISSING_IN_DRAWINGS.value
        base.note = result.note or base.note
    base.method = method.value
    base.mapped_by = mapped_by
    base.drawing_quantity = round(total, 4)
    base.delta = None if result.variance is None else round(result.variance, 4)
    base.delta_pct = None if result.variance_pct is None else round(result.variance_pct, 3)
    base.evidence = [e for e, _ in pool]

    map_conf = min((c.score for c in candidates if c.ref in {e.ref for e in base.evidence}), default=1.0)
    if mapped_by == "user":
        map_conf = 1.0
    source_factor = 1.0 if method is Method.MEASURED else ANNOTATED_FACTOR
    if "multiple_annotations" in base.flags:
        source_factor *= MULTI_ANNOTATION_FACTOR
    ev_conf = min((e.confidence for e in base.evidence), default=1.0)
    base.confidence = round(max(0.0, min(1.0, map_conf * source_factor * ev_conf)), 3)
    if mapped_by == "rules" and not ai_ranked:
        base.flags.append("rules_only")
    return base


# ---------------------------------------------------------------- missing in BOQ

def find_missing_in_boq(evidence: list[Evidence], attached_refs: set[str]) -> list[LineResult]:
    """Drawing quantities no BOQ line accounts for: possible missed scope. An annotation that
    restates an attached measurement (same dimension, within 5%) is not extra scope."""
    attached_values: dict[unit_conversion.Dimension, list[float]] = {}
    for ev in evidence:
        if ev.ref in attached_refs and ev.unit and ev.dimension():
            base_unit = {"length": "m", "area": "m2", "volume": "m3", "count": "nr"}[ev.dimension().value]  # type: ignore[union-attr]
            v = unit_conversion.convert(ev.value, ev.unit, base_unit)
            if v is not None:
                attached_values.setdefault(ev.dimension(), []).append(v)  # type: ignore[arg-type]
    out: list[LineResult] = []
    for ev in evidence:
        if ev.ref in attached_refs or ev.value is None or ev.value <= 0 or not ev.unit:
            continue
        dim = ev.dimension()
        if dim is None or ev.confidence < MISSING_IN_BOQ_MIN_CONFIDENCE:
            continue
        if ev.kind == "annotation" and ev.ann_kind not in ("length", "area", "volume", "count"):
            continue
        if ev.kind == "annotation":
            base_unit = {"length": "m", "area": "m2", "volume": "m3", "count": "nr"}[dim.value]
            v = unit_conversion.convert(ev.value, ev.unit, base_unit)
            if v is not None and any(
                abs(v - a) / a * 100.0 <= DUPLICATE_ANNOTATION_TOLERANCE_PCT for a in attached_values.get(dim, []) if a
            ):
                continue
        out.append(
            LineResult(
                line_id=None, vclass=VClass.MISSING_IN_BOQ.value,
                method=Method.MEASURED.value if ev.kind == "measurement" else Method.ANNOTATED.value,
                mapped_by="none", drawing_quantity=round(ev.value, 4), boq_uom=ev.unit,
                confidence=round(ev.confidence * (1.0 if ev.kind == "measurement" else ANNOTATED_FACTOR), 3),
                note=f"Drawing shows {ev.label} with no BOQ line", evidence=[ev],
            )
        )
    out.sort(key=lambda r: -(r.drawing_quantity or 0))
    return out


# ---------------------------------------------------------------- summary

def summarize(results: list[LineResult], trade_of: dict[str, str | None]) -> dict:
    counts = {c.value: 0 for c in VClass}
    by_trade: dict[str, dict] = {}
    for r in results:
        counts[r.vclass] += 1
        trade = (trade_of.get(r.line_id or "", None) if r.line_id else None) or "Unclassified"
        t = by_trade.setdefault(trade, {"trade": trade, "lines": 0, "match": 0, "variance": 0, "missing_in_drawings": 0,
                                        "not_verifiable": 0, "abs_variance_pct_sum": 0.0})
        if r.line_id:
            t["lines"] += 1
            if r.vclass in t:
                t[r.vclass] += 1
            if r.vclass == VClass.VARIANCE.value and r.delta_pct is not None:
                t["abs_variance_pct_sum"] += abs(r.delta_pct)
    risks = sorted(
        (r for r in results if r.vclass in (VClass.VARIANCE.value, VClass.MISSING_IN_DRAWINGS.value, VClass.MISSING_IN_BOQ.value)),
        key=lambda r: -_risk(r),
    )[:TOP_RISKS]
    return {
        "counts": counts,
        "verifiable": counts["match"] + counts["variance"] + counts["missing_in_drawings"],
        "by_trade": sorted(by_trade.values(), key=lambda t: -t["variance"]),
        "top_risks": [{"line_id": r.line_id, "class": r.vclass, "delta_pct": r.delta_pct, "note": r.note} for r in risks],
    }


def _risk(r: LineResult) -> float:
    if r.vclass == VClass.VARIANCE.value and r.delta_pct is not None:
        return abs(r.delta_pct)
    if r.vclass == VClass.MISSING_IN_DRAWINGS.value:
        return 100.0
    return 50.0
