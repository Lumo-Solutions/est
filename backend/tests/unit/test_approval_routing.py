from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from app.services.approvals import route_tiers


def _tier(seq: int, min_amount: float, max_amount: float | None, role: str, max_margin_pct: float | None = None):
    return SimpleNamespace(
        seq=seq, min_amount=min_amount, max_amount=max_amount, required_role=role, max_margin_pct=max_margin_pct
    )


DEFAULT_TIERS = [
    _tier(1, 0, 50_000, "lead_estimator"),
    _tier(2, 50_000, 250_000, "procurement_head"),
    _tier(3, 250_000, 1_000_000, "bd_director"),
    _tier(4, 1_000_000, None, "managing_director"),
]


def test_sequential_up_to_tier_small_amount_needs_only_first_tier():
    routed = route_tiers(DEFAULT_TIERS, 10_000, "sequential_up_to_tier")
    assert [t.required_role for t in routed] == ["lead_estimator"]


def test_sequential_up_to_tier_mid_amount_needs_two_tiers():
    routed = route_tiers(DEFAULT_TIERS, 60_000, "sequential_up_to_tier")
    assert [t.required_role for t in routed] == ["lead_estimator", "procurement_head"]


def test_sequential_up_to_tier_large_amount_needs_all_tiers():
    routed = route_tiers(DEFAULT_TIERS, 2_000_000, "sequential_up_to_tier")
    assert [t.required_role for t in routed] == [
        "lead_estimator", "procurement_head", "bd_director", "managing_director",
    ]


def test_highest_tier_only_mode_returns_single_bracketing_tier():
    routed = route_tiers(DEFAULT_TIERS, 60_000, "highest_tier_only")
    assert [t.required_role for t in routed] == ["procurement_head"]


def test_highest_tier_only_mode_open_ended_top_tier():
    routed = route_tiers(DEFAULT_TIERS, 5_000_000, "highest_tier_only")
    assert [t.required_role for t in routed] == ["managing_director"]


def test_zero_amount_still_routes_to_first_tier():
    routed = route_tiers(DEFAULT_TIERS, 0, "sequential_up_to_tier")
    assert [t.required_role for t in routed] == ["lead_estimator"]


def test_no_matching_tiers_returns_empty():
    tiers = [_tier(1, 100, 200, "lead_estimator")]
    assert route_tiers(tiers, 50, "sequential_up_to_tier") == []
    assert route_tiers(tiers, 50, "highest_tier_only") == []


# --------------------------------------------------------------------------
# Module D1: bid_submission policy -- managing_director if sell_total >
# AED 2,000,000 OR margin-on-sell < 8%, otherwise bd_director. Boundary
# tests required by docs/preconstruction-build-brief.md Phase 1 item 6 /
# docs/module-d1-plan.md §6.
# --------------------------------------------------------------------------

BID_SUBMISSION_TIERS = [
    _tier(1, 0, 2_000_000.00, "bd_director"),
    _tier(2, 2_000_000.01, None, "managing_director", max_margin_pct=8),
]


def test_bid_submission_amount_exactly_at_threshold_stays_bd_director():
    routed = route_tiers(BID_SUBMISSION_TIERS, 2_000_000.00, "highest_tier_only", margin_pct=15)
    assert [t.required_role for t in routed] == ["bd_director"]


def test_bid_submission_amount_one_cent_over_threshold_escalates():
    routed = route_tiers(BID_SUBMISSION_TIERS, 2_000_000.01, "highest_tier_only", margin_pct=15)
    assert [t.required_role for t in routed] == ["managing_director"]


def test_bid_submission_margin_exactly_at_floor_stays_bd_director():
    routed = route_tiers(BID_SUBMISSION_TIERS, 500_000, "highest_tier_only", margin_pct=8.00)
    assert [t.required_role for t in routed] == ["bd_director"]


def test_bid_submission_margin_just_below_floor_escalates():
    routed = route_tiers(BID_SUBMISSION_TIERS, 500_000, "highest_tier_only", margin_pct=7.99)
    assert [t.required_role for t in routed] == ["managing_director"]


def test_bid_submission_zero_total_routes_on_margin_alone():
    routed = route_tiers(BID_SUBMISSION_TIERS, 0, "highest_tier_only", margin_pct=15)
    assert [t.required_role for t in routed] == ["bd_director"]
    routed_thin = route_tiers(BID_SUBMISSION_TIERS, 0, "highest_tier_only", margin_pct=2)
    assert [t.required_role for t in routed_thin] == ["managing_director"]


def test_bid_submission_negative_markup_escalates_regardless_of_amount():
    # Selling below landed cost -- margin-on-sell goes negative, always < 8.
    routed = route_tiers(BID_SUBMISSION_TIERS, 100_000, "highest_tier_only", margin_pct=-5.26)
    assert [t.required_role for t in routed] == ["managing_director"]


def test_bid_submission_margin_at_third_decimal_below_floor_escalates():
    # route_tiers/_tier_matches compare Decimal end to end (amount,
    # min/max_amount, margin_pct), with no float() conversion anywhere in
    # the path -- app/services/settlement.py's margin_on_sell_pct is
    # quantized to 3dp (_Q3), so 7.995 must stay exactly 7.995 through this
    # comparison and correctly escalate, even though it would round to
    # 8.00 at the 2dp precision the UI displays elsewhere. See
    # docs/build-log.md's Phase 10 section.
    tiers = [
        _tier(1, Decimal("0"), Decimal("2000000.00"), "bd_director"),
        _tier(2, Decimal("2000000.01"), None, "managing_director", max_margin_pct=Decimal("8.00")),
    ]
    routed = route_tiers(tiers, Decimal("500000"), "highest_tier_only", margin_pct=Decimal("7.995"))
    assert [t.required_role for t in routed] == ["managing_director"]

    routed_at_floor = route_tiers(tiers, Decimal("500000"), "highest_tier_only", margin_pct=Decimal("8.00"))
    assert [t.required_role for t in routed_at_floor] == ["bd_director"]
