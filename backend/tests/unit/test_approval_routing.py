from __future__ import annotations

from types import SimpleNamespace

from app.services.approvals import route_tiers


def _tier(seq: int, min_amount: float, max_amount: float | None, role: str):
    return SimpleNamespace(seq=seq, min_amount=min_amount, max_amount=max_amount, required_role=role)


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
