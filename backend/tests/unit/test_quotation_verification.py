"""Module C Phase 6: pure verification logic -- subtotal arithmetic,
unit-aware quantity comparison, and exclusion-citation substring
verification. No DB/session -- see
tests/integration/test_procurement_geography_and_verification.py for the
DB-backed geography-eligibility and end-to-end verification tests."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.procurement.quotation_verification import (
    check_total_mismatch,
    resolve_quantity_comparison,
    verify_citation,
)
from app.services.procurement import _resolve_geography_eligibility

# --------------------------------------------------------------------------
# subtotal verification
# --------------------------------------------------------------------------


def test_check_total_mismatch_false_within_tolerance():
    assert check_total_mismatch(Decimal("300.00"), [Decimal("100.00"), Decimal("100.00"), Decimal("100.00")]) is False


def test_check_total_mismatch_true_beyond_tolerance():
    assert check_total_mismatch(Decimal("350.00"), [Decimal("100.00"), Decimal("100.00"), Decimal("100.00")]) is True


def test_check_total_mismatch_tolerance_scales_with_line_count():
    # 3 lines -> 0.03 tolerance; a 0.02 discrepancy is within it.
    assert check_total_mismatch(Decimal("300.02"), [Decimal("100.00"), Decimal("100.00"), Decimal("100.00")]) is False


def test_check_total_mismatch_treats_missing_line_amounts_as_zero():
    assert check_total_mismatch(Decimal("100.00"), [Decimal("100.00"), None]) is False
    assert check_total_mismatch(Decimal("200.00"), [Decimal("100.00"), None]) is True


# --------------------------------------------------------------------------
# unit-aware quantity comparison
# --------------------------------------------------------------------------


def test_resolve_quantity_comparison_passes_through_when_units_match():
    qty, uom_mismatch = resolve_quantity_comparison("M", "M", Decimal("100"))
    assert qty == Decimal("100")
    assert uom_mismatch is False


def test_resolve_quantity_comparison_passes_through_when_either_uom_missing():
    assert resolve_quantity_comparison(None, "M", Decimal("100")) == (Decimal("100"), False)
    assert resolve_quantity_comparison("M", None, Decimal("100")) == (Decimal("100"), False)


def test_resolve_quantity_comparison_converts_when_convertible_but_different_notation():
    qty, uom_mismatch = resolve_quantity_comparison("LM", "M", Decimal("100"))
    assert qty == pytest.approx(100.0)  # "LM" (linear metre) and "M" are the same length unit
    assert uom_mismatch is False


def test_resolve_quantity_comparison_flags_uom_mismatch_when_not_convertible():
    qty, uom_mismatch = resolve_quantity_comparison("M2", "M3", Decimal("100"))  # area vs volume -- a category error
    assert qty is None
    assert uom_mismatch is True


# --------------------------------------------------------------------------
# citation verification
# --------------------------------------------------------------------------


def test_verify_citation_true_on_exact_substring_match():
    assert verify_citation("Excludes dewatering", "Some preamble. Excludes dewatering. Some more text.") is True


def test_verify_citation_true_ignoring_whitespace_differences():
    assert verify_citation("Excludes   dewatering", "Some preamble.\nExcludes\tdewatering.\n") is True


def test_verify_citation_false_when_genuinely_absent():
    assert verify_citation("Excludes dewatering", "This document says nothing about that at all.") is False


def test_verify_citation_false_when_no_source_text_at_all():
    """Image-only extraction (no text layer) -- nothing to search, not a
    failed verification of something checkable."""
    assert verify_citation("Excludes dewatering", "") is False


# --------------------------------------------------------------------------
# geography eligibility (pure decision)
# --------------------------------------------------------------------------


def test_geography_eligible_when_project_has_no_emirate_set():
    assert _resolve_geography_eligibility(None, {"Dubai"}) == (True, None)


def test_geography_eligible_when_vendor_has_no_declared_regions():
    assert _resolve_geography_eligibility("Dubai", set()) == (True, None)


def test_geography_eligible_when_project_emirate_is_in_served_regions():
    assert _resolve_geography_eligibility("Dubai", {"Dubai", "Abu Dhabi"}) == (True, None)


def test_geography_ineligible_when_project_emirate_not_served():
    eligible, reason = _resolve_geography_eligibility("Sharjah", {"Dubai", "Abu Dhabi"})
    assert eligible is False
    assert "Sharjah" in reason
