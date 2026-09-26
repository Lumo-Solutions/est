"""Module D1: the per-line formula and the rates-are-authoritative rounding
rule (docs/module-d1-plan.md §4/§5) -- pure Decimal math, no DB needed.
Reproduces the plan's worked example exactly."""

from __future__ import annotations

from decimal import Decimal

from app.services.settlement import _calc_line, _pct_fraction, _q2

PLANT = Decimal("2")
OVERHEAD = Decimal("5")
MARKUP = Decimal("10")


def test_pct_fraction_converts_percent_number_to_fraction():
    assert _pct_fraction(Decimal("10")) == Decimal("0.1")
    assert _pct_fraction(Decimal("0")) == Decimal("0")


def test_q2_rounds_half_up():
    assert _q2(Decimal("1.005")) == Decimal("1.01")
    assert _q2(Decimal("1.004")) == Decimal("1.00")


def _line(direct_unit_cost: str, qty: str, volatility: str, markup: str = "10"):
    return _calc_line(Decimal(direct_unit_cost), Decimal(qty), PLANT, OVERHEAD, Decimal(volatility), Decimal(markup))


def test_worked_example_l1_excavation():
    base, plant, overhead, volatility, markup, model_sell = _line("45", "500", "6")
    assert base == Decimal("22500")
    assert plant == Decimal("450.00")
    assert overhead == Decimal("1125.00")
    assert volatility == Decimal("1444.5000")
    assert markup == Decimal("2551.950000")
    assert model_sell == Decimal("28071.450000")
    unit_rate = _q2(model_sell / Decimal("500"))
    assert unit_rate == Decimal("56.14")
    assert _q2(unit_rate * Decimal("500")) == Decimal("28070.00")  # rate is authoritative: no residual correction


def test_worked_example_l2_blinding_concrete():
    base, plant, overhead, volatility, markup, model_sell = _line("380", "200", "3")
    assert model_sell == Decimal("92135.560000")
    unit_rate = _q2(model_sell / Decimal("200"))
    assert unit_rate == Decimal("460.68")
    assert _q2(unit_rate * Decimal("200")) == Decimal("92136.00")


def test_worked_example_l3_rebar_supply_with_markup_override():
    base, plant, overhead, volatility, markup, model_sell = _line("3.85", "15000", "3", markup="15")
    assert model_sell == Decimal("73193.216250")
    unit_rate = _q2(model_sell / Decimal("15000"))
    assert unit_rate == Decimal("4.88")
    assert _q2(unit_rate * Decimal("15000")) == Decimal("73200.00")


def test_worked_example_settlement_totals():
    """Reproduces docs/module-d1-plan.md §5 exactly: tender_total,
    rounding_difference, and margin_on_sell_pct."""
    l1 = _line("45", "500", "6")
    l2 = _line("380", "200", "3")
    l3 = _line("3.85", "15000", "3", markup="15")

    exact_model_total = l1[5] + l2[5] + l3[5]
    assert exact_model_total == Decimal("193400.226250")

    rates_and_qty = [(l1[5], Decimal("500")), (l2[5], Decimal("200")), (l3[5], Decimal("15000"))]
    line_amounts = [_q2(_q2(sell / qty) * qty) for sell, qty in rates_and_qty]
    assert line_amounts == [Decimal("28070.00"), Decimal("92136.00"), Decimal("73200.00")]

    tender_total = _q2(sum(line_amounts))
    assert tender_total == Decimal("193406.00")

    rounding_difference = _q2(tender_total - exact_model_total)
    assert rounding_difference == Decimal("5.77")

    total_markup = l1[4] + l2[4] + l3[4]
    assert total_markup == Decimal("20474.851250")

    margin_on_sell_pct = (total_markup / tender_total * 100).quantize(Decimal("0.001"))
    assert margin_on_sell_pct == Decimal("10.586")


def test_negative_markup_produces_negative_margin_on_sell():
    """§6 boundary: negative markup (selling below landed cost) must still
    compute cleanly and yield a margin below any positive floor."""
    base, plant, overhead, volatility, markup, model_sell = _calc_line(
        Decimal("100"), Decimal("10"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("-5")
    )
    assert markup < 0
    margin_on_sell_pct = markup / model_sell * 100
    assert margin_on_sell_pct < 0
