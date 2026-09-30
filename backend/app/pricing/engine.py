"""Pricing assistant: the deterministic core (docs/ai-plan.md §5, Phase 4).

Pure functions. For every BOQ line of a settlement draft we gather REAL cost candidates (an accepted
vendor quote line, a cost-library rate as of the tender date, a historical median from past
settlements and outturn observations), compute flags in code, and pick a proposal. The AI only helps
choose among the candidates (semantic matching, see app/pricing/ai.py); **the rate always comes from
the chosen candidate's stored value. The AI never invents a rate.** A line with no candidate is
"No cost source: manual entry required".
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum

from rapidfuzz import fuzz

from app.boq import units as unit_conversion

# Flags. BLOCKING ones stop bulk-accept and cap confidence; INFO ones are shown.
UNIT_MISMATCH = "unit_mismatch"
STALE_RATE = "stale_rate"
QUOTE_EXCLUSIONS = "quote_exclusions"
VENDOR_NOT_ELIGIBLE = "vendor_not_eligible"
LARGE_DEVIATION = "large_deviation"
NEEDS_FX = "needs_fx"
SINGLE_SOURCE = "single_source"
DEVIATION = "deviation_from_history"
UNIT_ALIAS = "unit_alias"
BLOCKING = {UNIT_MISMATCH, STALE_RATE, QUOTE_EXCLUSIONS, VENDOR_NOT_ELIGIBLE, LARGE_DEVIATION, NEEDS_FX}

DEVIATION_PCT = 25.0
LARGE_DEVIATION_PCT = 50.0
DEFAULT_STALE_MONTHS = 12
BULK_ACCEPT_MIN_CONFIDENCE = 0.85
BLOCKING_CONFIDENCE_FACTOR = 0.55
SINGLE_SOURCE_FACTOR = 0.9
LIBRARY_MIN_MATCH = 0.72  # rules-only choice of a library rate needs a description at least this close
NO_SOURCE_NOTE = "No cost source: manual entry required"


class CandType(StrEnum):
    QUOTE = "quote"
    LIBRARY = "library"
    HISTORICAL = "historical"


@dataclass(slots=True)
class CostCandidate:
    ref: str  # 'q:<quotation_line_item_id>' | 'c:<cost_item_id>' | 'h:<boq_line_item_id>'
    ctype: str
    label: str
    rate: Decimal
    currency: str
    uom: str | None
    # how the settlement service must apply it (all values come from the DB rows, never the model)
    apply: dict
    match_score: float = 0.0  # deterministic description similarity 0..1
    vendor: str | None = None
    as_of: date | None = None  # date of the quote / start of the rate's validity
    samples: int = 0  # historical: number of observations
    flags: list[str] = field(default_factory=list)
    detail: dict = field(default_factory=dict)
    exclusions: int = 0  # open exclusion flags on the vendor quote (input to flags, not stored)
    eligible: bool | None = None  # vendor prequal + location eligibility (None = not applicable)


@dataclass(slots=True)
class Proposal:
    chosen: CostCandidate | None
    ranked: list[tuple[CostCandidate, float, str]]  # (candidate, score, reason)
    confidence: float
    rationale: str
    flags: list[str]
    source: str  # ai | rules | none


# ---------------------------------------------------------------- units

def units_compatible(boq_uom: str | None, cand_uom: str | None) -> tuple[bool, bool]:
    """(same_for_pricing, is_alias). A rate is per unit, so units must be interchangeable 1:1
    (m/LM/RM, nr/no/nos/ea, m2/sqm, m3/cum), not merely the same dimension (a rate per mm is not
    a rate per m)."""
    if not boq_uom or not cand_uom:
        return False, False
    if boq_uom.strip().lower() == cand_uom.strip().lower():
        return True, False
    conv = unit_conversion.convert(1.0, cand_uom, boq_uom)
    if conv is not None and abs(conv - 1.0) < 1e-9:
        return True, True
    return False, False


def description_similarity(a: str, b: str) -> float:
    return round(fuzz.token_set_ratio(a.lower(), b.lower()) / 100.0, 3)


# ---------------------------------------------------------------- flags

def months_between(earlier: date, later: date) -> float:
    return (later.year - earlier.year) * 12 + (later.month - earlier.month) + (later.day - earlier.day) / 30.0


def historical_median(rates: list[Decimal]) -> Decimal | None:
    if not rates:
        return None
    return Decimal(str(statistics.median([float(r) for r in rates]))).quantize(Decimal("0.0001"))


def compute_flags(
    cand: CostCandidate,
    *,
    boq_uom: str | None,
    settlement_currency: str,
    tender_date: date,
    stale_months: int,
    history_median: Decimal | None,
    exclusion_count: int = 0,
    vendor_eligible: bool | None = None,
    source_count: int = 1,
) -> list[str]:
    flags: list[str] = []
    same, alias = units_compatible(boq_uom, cand.uom)
    if not same:
        flags.append(UNIT_MISMATCH)
    elif alias:
        flags.append(UNIT_ALIAS)
    if cand.as_of is not None and cand.ctype != CandType.HISTORICAL.value:
        if months_between(cand.as_of, tender_date) > stale_months:
            flags.append(STALE_RATE)
    if exclusion_count > 0:
        flags.append(QUOTE_EXCLUSIONS)
        cand.detail["open_exclusions"] = exclusion_count
    if vendor_eligible is False:
        flags.append(VENDOR_NOT_ELIGIBLE)
    if cand.currency and cand.currency != settlement_currency:
        flags.append(NEEDS_FX)
    if source_count <= 1:
        flags.append(SINGLE_SOURCE)
    if history_median and history_median > 0 and cand.ctype != CandType.HISTORICAL.value:
        dev = abs(float((cand.rate - history_median) / history_median)) * 100.0
        cand.detail["deviation_pct"] = round(dev, 1)
        if dev >= LARGE_DEVIATION_PCT:
            flags.append(LARGE_DEVIATION)
        elif dev >= DEVIATION_PCT:
            flags.append(DEVIATION)
    return flags


def is_blocked(flags: list[str]) -> bool:
    return any(f in BLOCKING for f in flags)


# ---------------------------------------------------------------- choosing

def rules_choice(cands: list[CostCandidate]) -> Proposal:
    """Used when the AI is unavailable (or as its fallback): an accepted quote with no blocking flag,
    else a library rate whose description is close enough and has no blocking flag, else nothing."""
    usable = [c for c in cands if UNIT_MISMATCH not in c.flags and c.rate > 0]
    ranked = [(c, c.match_score, "rules: description similarity") for c in sorted(cands, key=lambda c: -c.match_score)]
    clean_quotes = [c for c in usable if c.ctype == CandType.QUOTE.value and not is_blocked(c.flags)]
    if len(clean_quotes) == 1:
        chosen = clean_quotes[0]
        reason = "The only accepted vendor quote for this line, with no blocking flags"
    elif len(clean_quotes) > 1:
        chosen = min(clean_quotes, key=lambda c: c.rate)
        reason = f"Lowest of {len(clean_quotes)} accepted vendor quotes with no blocking flags"
    else:
        libs = [c for c in usable if c.ctype == CandType.LIBRARY.value and c.match_score >= LIBRARY_MIN_MATCH and not is_blocked(c.flags)]
        chosen = max(libs, key=lambda c: c.match_score) if libs else None
        reason = "Closest cost-library item by description" if chosen else NO_SOURCE_NOTE
    if chosen is None:
        return Proposal(None, ranked, 0.0, NO_SOURCE_NOTE if not cands else "No candidate passed the checks; choose one or enter a cost manually", [], "none")
    conf = _confidence(chosen, chosen.match_score, len(usable))
    return Proposal(chosen, ranked, conf, reason, list(chosen.flags), "rules")


def _confidence(c: CostCandidate, base: float, source_count: int) -> float:
    conf = max(0.0, min(1.0, base))
    if is_blocked(c.flags):
        conf *= BLOCKING_CONFIDENCE_FACTOR
    if SINGLE_SOURCE in c.flags:
        conf *= SINGLE_SOURCE_FACTOR
    return round(conf, 3)


def ai_choice(
    cands: list[CostCandidate], ai_ranked: list[tuple[str, float, bool, str]], overall: str
) -> Proposal:
    """`ai_ranked` = (ref, score 0..1, selected, rationale) in the model's order. Unknown refs are
    ignored (the model cannot introduce a source); at most one selection is honoured (the best-scored
    selected one); the rate is read from OUR candidate, never from the model."""
    by_ref = {c.ref: c for c in cands}
    ranked: list[tuple[CostCandidate, float, str]] = []
    seen: set[str] = set()
    for ref, score, _sel, why in ai_ranked:
        c = by_ref.get(ref)
        if c is None or ref in seen:
            continue
        seen.add(ref)
        ranked.append((c, max(0.0, min(1.0, score)), why))
    for c in cands:
        if c.ref not in seen:
            ranked.append((c, 0.0, "not assessed by the AI"))
    sel_map = {ref: sel for ref, _score, sel, _why in ai_ranked}
    selected = [(c, sc, w) for c, sc, w in ranked if sel_map.get(c.ref)]
    selected = [t for t in selected if UNIT_MISMATCH not in t[0].flags and t[0].rate > 0]
    if not selected:
        return Proposal(None, ranked, 0.0, overall or NO_SOURCE_NOTE, [], "ai")
    chosen, score, why = max(selected, key=lambda t: t[1])
    conf = _confidence(chosen, score, len(cands))
    return Proposal(chosen, ranked, conf, why or overall, list(chosen.flags), "ai")


def can_bulk_accept(p: Proposal, min_confidence: float = BULK_ACCEPT_MIN_CONFIDENCE) -> bool:
    return p.chosen is not None and p.confidence >= min_confidence and not is_blocked(p.flags)


# ---------------------------------------------------------------- markup context

def win_rate_by_margin(history: list[dict]) -> list[dict]:
    """history rows: {margin_on_sell_pct, outcome ('won'|'lost'), our_price, winning_price}. Buckets of the
    margin actually bid; win rate and, for losses, the average gap to the winning price."""
    buckets = [(-1e9, 6.0, "under 6%"), (6.0, 8.0, "6-8%"), (8.0, 10.0, "8-10%"), (10.0, 1e9, "10% and over")]
    out = []
    for lo, hi, label in buckets:
        rows = [h for h in history if h.get("margin_on_sell_pct") is not None and lo <= float(h["margin_on_sell_pct"]) < hi]
        if not rows:
            continue
        won = sum(1 for h in rows if h.get("outcome") == "won")
        gaps = [
            (float(h["our_price"]) - float(h["winning_price"])) / float(h["winning_price"]) * 100.0
            for h in rows
            if h.get("outcome") == "lost" and h.get("our_price") and h.get("winning_price")
        ]
        out.append(
            {"margin_bucket": label, "bids": len(rows), "won": won, "win_rate_pct": round(won / len(rows) * 100.0, 1),
             "avg_price_gap_when_lost_pct": round(sum(gaps) / len(gaps), 1) if gaps else None}
        )
    return out


def clamp_option(value: float | None, lo: float, hi: float, default: float) -> float:
    if value is None:
        return default
    return round(max(lo, min(hi, float(value))), 2)
