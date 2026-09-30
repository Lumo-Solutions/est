"""Pricing assistant engine: units, flags, rules choice, AI choice guards, confidence, history, advice
clamping. Pure, no DB, no model."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.pricing import engine as pe
from app.pricing.ai import clean_advice

TENDER = date(2026, 6, 1)


def cand(ref="q:1", ctype="quote", rate="100", uom="m", cur="AED", score=0.9, as_of=date(2026, 3, 1), **kw):
    return pe.CostCandidate(
        ref=ref, ctype=ctype, label=kw.pop("label", ref), rate=Decimal(rate), currency=cur, uom=uom, apply=kw.pop("apply", {"cost_source": "manual"}),
        match_score=score, as_of=as_of, **kw,
    )


def flagged(c, **kw):
    defaults = dict(boq_uom="m", settlement_currency="AED", tender_date=TENDER, stale_months=12, history_median=None, source_count=2)
    defaults.update(kw)
    c.flags = pe.compute_flags(c, **defaults)
    return c


# ---------------------------------------------------------------- units

def test_units_must_be_interchangeable_one_to_one_not_just_same_dimension():
    assert pe.units_compatible("m", "m") == (True, False)
    assert pe.units_compatible("m", "LM") == (True, True)
    assert pe.units_compatible("nr", "nos") == (True, True)
    assert pe.units_compatible("m2", "sqm") == (True, True)
    assert pe.units_compatible("m", "mm") == (False, False)   # a rate per mm is not a rate per m
    assert pe.units_compatible("m", "m3") == (False, False)
    assert pe.units_compatible("m", None) == (False, False)


# ---------------------------------------------------------------- flags

def test_flags_are_computed_in_code():
    assert pe.UNIT_MISMATCH in flagged(cand(uom="mm")).flags
    assert pe.UNIT_ALIAS in flagged(cand(uom="lm")).flags and pe.UNIT_MISMATCH not in flagged(cand(uom="lm")).flags
    assert pe.STALE_RATE in flagged(cand(as_of=date(2024, 1, 1))).flags
    assert pe.STALE_RATE not in flagged(cand(as_of=date(2026, 1, 1))).flags
    assert pe.STALE_RATE not in flagged(cand(ctype="historical", as_of=date(2020, 1, 1))).flags  # history has no 'age'
    assert pe.QUOTE_EXCLUSIONS in flagged(cand(), exclusion_count=2).flags
    assert pe.VENDOR_NOT_ELIGIBLE in flagged(cand(), vendor_eligible=False).flags
    assert pe.VENDOR_NOT_ELIGIBLE not in flagged(cand(), vendor_eligible=None).flags
    assert pe.NEEDS_FX in flagged(cand(cur="USD")).flags
    assert pe.SINGLE_SOURCE in flagged(cand(), source_count=1).flags and pe.SINGLE_SOURCE not in flagged(cand(), source_count=2).flags


def test_deviation_from_history_thresholds():
    med = Decimal("100")
    assert pe.DEVIATION not in flagged(cand(rate="110"), history_median=med).flags
    assert pe.DEVIATION in flagged(cand(rate="130"), history_median=med).flags
    f = flagged(cand(rate="160"), history_median=med)
    assert pe.LARGE_DEVIATION in f.flags and f.detail["deviation_pct"] == 60.0
    assert pe.is_blocked(f.flags) and not pe.is_blocked(flagged(cand(rate="130"), history_median=med).flags)


def test_blocking_flags_and_unit_alias_is_not_blocking():
    assert not pe.is_blocked([pe.UNIT_ALIAS, pe.SINGLE_SOURCE, pe.DEVIATION])
    for f in (pe.UNIT_MISMATCH, pe.STALE_RATE, pe.QUOTE_EXCLUSIONS, pe.VENDOR_NOT_ELIGIBLE, pe.LARGE_DEVIATION, pe.NEEDS_FX):
        assert pe.is_blocked([f])


# ---------------------------------------------------------------- rules choice

def test_rules_pick_the_only_clean_quote():
    q = flagged(cand("q:1", rate="88"))
    p = pe.rules_choice([q, flagged(cand("c:1", "library", rate="90", score=0.9))])
    assert p.chosen.ref == "q:1" and p.source == "rules" and p.chosen.rate == Decimal("88")


def test_rules_pick_cheapest_of_several_clean_quotes():
    p = pe.rules_choice([flagged(cand("q:1", rate="95")), flagged(cand("q:2", rate="90")), flagged(cand("q:3", rate="99"))])
    assert p.chosen.ref == "q:2" and "Lowest of 3" in p.rationale


def test_blocked_quote_falls_back_to_a_close_library_rate():
    bad = flagged(cand("q:1", rate="50"), exclusion_count=1)
    lib = flagged(cand("c:1", "library", rate="92", score=0.8))
    p = pe.rules_choice([bad, lib])
    assert p.chosen.ref == "c:1"


def test_library_rate_needs_a_close_description_and_no_blockers():
    assert pe.rules_choice([flagged(cand("c:1", "library", score=0.5))]).chosen is None
    assert pe.rules_choice([flagged(cand("c:1", "library", score=0.9, as_of=date(2020, 1, 1)))]).chosen is None  # stale
    assert pe.rules_choice([flagged(cand("c:1", "library", score=0.9, uom="mm"))]).chosen is None  # wrong unit


def test_no_candidates_is_no_source_never_a_guess():
    p = pe.rules_choice([])
    assert p.chosen is None and p.rationale == pe.NO_SOURCE_NOTE and p.source == "none" and p.confidence == 0.0


def test_historical_is_context_not_chosen_by_the_rules():
    assert pe.rules_choice([flagged(cand("h:1", "historical", score=0.8))]).chosen is None


# ---------------------------------------------------------------- AI choice guards

def test_ai_choice_uses_our_rate_and_ignores_unknown_refs():
    a, b = flagged(cand("q:1", rate="88")), flagged(cand("c:1", "library", rate="120", score=0.7))
    p = pe.ai_choice([a, b], [("q:ROGUE", 1.0, True, "trust me"), ("c:1", 0.8, True, "same size and material")], "")
    assert p.chosen.ref == "c:1" and p.chosen.rate == Decimal("120") and p.source == "ai"
    assert [c.ref for c, _s, _w in p.ranked][0] == "c:1" and "q:ROGUE" not in [c.ref for c, _s, _w in p.ranked]
    assert next(w for c, _s, w in p.ranked if c.ref == "q:1") == "not assessed by the AI"


def test_ai_choice_honours_only_the_best_scored_selection_and_never_a_unit_mismatch():
    a = flagged(cand("q:1", rate="88"))
    b = flagged(cand("q:2", rate="80"))
    mism = flagged(cand("q:3", rate="10", uom="mm"))
    p = pe.ai_choice([a, b, mism], [("q:3", 0.99, True, "cheapest"), ("q:1", 0.7, True, "ok"), ("q:2", 0.9, True, "better")], "")
    assert p.chosen.ref == "q:2"
    none = pe.ai_choice([mism], [("q:3", 0.99, True, "")], "nothing suitable")
    assert none.chosen is None and none.rationale == "nothing suitable"


def test_ai_scores_are_clamped():
    p = pe.ai_choice([flagged(cand("q:1"))], [("q:1", 7.5, True, "")], "")
    assert p.ranked[0][1] == 1.0


# ---------------------------------------------------------------- confidence and bulk accept

def test_confidence_penalties_and_bulk_accept():
    clean = pe.rules_choice([flagged(cand("q:1", score=0.95), source_count=2)])
    assert clean.confidence == 0.95 and pe.can_bulk_accept(clean)
    single = pe.rules_choice([flagged(cand("q:1", score=0.95), source_count=1)])
    assert single.confidence == round(0.95 * pe.SINGLE_SOURCE_FACTOR, 3) and pe.can_bulk_accept(single)
    ai = pe.ai_choice([flagged(cand("q:1", rate="10", score=0.9), history_median=Decimal("100"))], [("q:1", 0.95, True, "")], "")
    assert pe.LARGE_DEVIATION in ai.flags and ai.confidence < 0.6 and not pe.can_bulk_accept(ai)
    assert not pe.can_bulk_accept(pe.rules_choice([]))
    assert not pe.can_bulk_accept(clean, min_confidence=0.99)


# ---------------------------------------------------------------- history & advice

def test_history_median_and_win_rate_buckets():
    assert pe.historical_median([]) is None
    assert pe.historical_median([Decimal(90), Decimal(100), Decimal(200)]) == Decimal("100.0000")
    rows = [
        {"margin_on_sell_pct": 5, "outcome": "won", "our_price": 100, "winning_price": 100},
        {"margin_on_sell_pct": 9, "outcome": "lost", "our_price": 110, "winning_price": 100},
        {"margin_on_sell_pct": 9.5, "outcome": "won", "our_price": 100, "winning_price": 100},
        {"margin_on_sell_pct": None, "outcome": "won"},
    ]
    b = {x["margin_bucket"]: x for x in pe.win_rate_by_margin(rows)}
    assert b["under 6%"]["win_rate_pct"] == 100.0 and b["8-10%"]["bids"] == 2 and b["8-10%"]["win_rate_pct"] == 50.0
    assert b["8-10%"]["avg_price_gap_when_lost_pct"] == 10.0


def test_advice_is_clamped_deduplicated_and_ranges_are_ordered():
    out = clean_advice({
        "options": [
            {"label": "balanced", "markup_pct": 99, "overhead_pct": -3, "volatility_pct": 4.256, "rationale": "x"},
            {"label": "balanced", "markup_pct": 1, "overhead_pct": 1, "volatility_pct": 1, "rationale": "dup"},
        ],
        "per_trade": [{"trade": "drainage", "markup_low": 12, "markup_high": 6, "volatility_low": 25, "volatility_high": None, "rationale": "r"}],
        "overall": "o" * 5000,
    })
    assert len(out["options"]) == 1
    o = out["options"][0]
    assert o["markup_pct"] == 40.0 and o["overhead_pct"] == 0.0 and o["volatility_pct"] == 4.26
    t = out["per_trade"][0]
    assert (t["markup_low"], t["markup_high"]) == (6.0, 12.0) and t["volatility_low"] == 20.0 and t["volatility_high"] is None
    assert len(out["overall"]) == 1000
