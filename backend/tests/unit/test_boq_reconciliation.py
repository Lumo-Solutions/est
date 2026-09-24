from __future__ import annotations

import pytest

from app.boq.reconciliation import (
    DiscrepancyClass,
    ReconciliationConfig,
    aggregate_measurement_values,
    reconcile,
)


def test_match_within_default_tolerance() -> None:
    # BOQ tendered 100 m3; takeoff measured 101.5 m3.
    # variance = 101.5 - 100 = 1.5; variance_pct = 1.5/100*100 = 1.5%.
    # Default tolerance is 2.0% -> 1.5% <= 2.0% -> MATCH.
    result = reconcile(boq_quantity=100.0, boq_uom="m3", measurement_value=101.5, measurement_unit="m3")
    assert result.discrepancy_class == DiscrepancyClass.MATCH.value
    assert result.variance == pytest.approx(1.5)
    assert result.variance_pct == pytest.approx(1.5)
    assert result.note is None


def test_match_at_exactly_the_tolerance_boundary() -> None:
    # variance_pct = exactly 2.0% -- "at or below" tolerance is a MATCH
    # (the boundary itself counts as matching, not variance).
    result = reconcile(boq_quantity=200.0, boq_uom="m", measurement_value=204.0, measurement_unit="m")
    assert result.variance == pytest.approx(4.0)
    assert result.variance_pct == pytest.approx(2.0)
    assert result.discrepancy_class == DiscrepancyClass.MATCH.value


def test_variance_over_default_tolerance() -> None:
    # BOQ tendered 50 m; takeoff measured 60 m.
    # variance = 10; variance_pct = 10/50*100 = 20% > 2% -> VARIANCE.
    result = reconcile(boq_quantity=50.0, boq_uom="m", measurement_value=60.0, measurement_unit="m")
    assert result.variance == pytest.approx(10.0)
    assert result.variance_pct == pytest.approx(20.0)
    assert result.discrepancy_class == DiscrepancyClass.VARIANCE.value
    assert result.note is None


def test_variance_is_symmetric_for_under_measurement() -> None:
    # Takeoff measured LESS than tendered: BOQ 100, measured 80.
    # variance = -20; variance_pct = -20% -> |−20| > 2% -> VARIANCE.
    result = reconcile(boq_quantity=100.0, boq_uom="m2", measurement_value=80.0, measurement_unit="m2")
    assert result.variance == pytest.approx(-20.0)
    assert result.variance_pct == pytest.approx(-20.0)
    assert result.discrepancy_class == DiscrepancyClass.VARIANCE.value


def test_custom_tolerance_config() -> None:
    # Same 20%-over case as above, but with a much looser 25% tolerance
    # configured -> now a MATCH instead of a VARIANCE.
    config = ReconciliationConfig(tolerance_pct=25.0)
    result = reconcile(boq_quantity=50.0, boq_uom="m", measurement_value=60.0, measurement_unit="m", config=config)
    assert result.variance_pct == pytest.approx(20.0)
    assert result.discrepancy_class == DiscrepancyClass.MATCH.value


def test_unmatched_when_no_measurement_linked() -> None:
    result = reconcile(boq_quantity=100.0, boq_uom="m3", measurement_value=None, measurement_unit=None)
    assert result.discrepancy_class == DiscrepancyClass.UNMATCHED.value
    assert result.variance is None
    assert result.variance_pct is None
    assert result.note == "No linked takeoff measurement"


def test_unmatched_on_unit_mismatch() -> None:
    # BOQ item is in m3 (a volume) but somehow got linked to an alignment
    # length measurement (m) -- comparing the numbers directly would be
    # meaningless, not "close" or "far".
    result = reconcile(boq_quantity=100.0, boq_uom="m3", measurement_value=100.0, measurement_unit="m")
    assert result.discrepancy_class == DiscrepancyClass.UNMATCHED.value
    assert result.variance is None
    assert result.variance_pct is None
    assert "m3" in result.note and "m" in result.note


def test_unit_comparison_is_case_insensitive() -> None:
    result = reconcile(boq_quantity=100.0, boq_uom="M3", measurement_value=101.0, measurement_unit="m3")
    assert result.discrepancy_class == DiscrepancyClass.MATCH.value


def test_converts_millimeters_to_meters_before_comparing() -> None:
    # BOQ tendered 5.0 m; takeoff measurement is 5010 mm (a length
    # extractor could plausibly report in mm on a drawing modeled that
    # way). Converted: 5010 mm = 5.01 m.
    # variance = 5.01 - 5.0 = 0.01; variance_pct = 0.01/5.0*100 = 0.2% -> MATCH.
    result = reconcile(boq_quantity=5.0, boq_uom="m", measurement_value=5010.0, measurement_unit="mm")
    assert result.variance == pytest.approx(0.01)
    assert result.variance_pct == pytest.approx(0.2)
    assert result.discrepancy_class == DiscrepancyClass.MATCH.value


def test_converts_common_boq_abbreviation_before_comparing() -> None:
    # BOQ tendered 100 LM ("linear metre", a common BOQ abbreviation for
    # m); takeoff measured 106 m. Converted: 106 m in LM terms = 106 (LM
    # is a 1:1 alias for m).
    # variance = 106 - 100 = 6; variance_pct = 6% > 2% default -> VARIANCE.
    result = reconcile(boq_quantity=100.0, boq_uom="LM", measurement_value=106.0, measurement_unit="m")
    assert result.variance == pytest.approx(6.0)
    assert result.variance_pct == pytest.approx(6.0)
    assert result.discrepancy_class == DiscrepancyClass.VARIANCE.value


def test_unmatched_on_dimension_mismatch_names_both_dimensions() -> None:
    # BOQ tendered in m3 (volume) but linked to a length measurement (m) --
    # same as test_unmatched_on_unit_mismatch, but also checking the note
    # explicitly names the dimension of each side, not just the raw unit
    # strings.
    result = reconcile(boq_quantity=100.0, boq_uom="m3", measurement_value=100.0, measurement_unit="m")
    assert result.discrepancy_class == DiscrepancyClass.UNMATCHED.value
    assert "volume" in result.note and "length" in result.note


def test_unmatched_on_unrecognized_unit() -> None:
    # "sqft-ish" isn't in the unit table at all -- must not be silently
    # treated as compatible with anything, including itself.
    result = reconcile(boq_quantity=10.0, boq_uom="sqft-ish", measurement_value=10.0, measurement_unit="sqft-ish")
    assert result.discrepancy_class == DiscrepancyClass.UNMATCHED.value
    assert "Unrecognized unit" in result.note


def test_unmatched_when_boq_quantity_missing() -> None:
    # A measurement is linked but the BOQ item itself has no tendered
    # quantity yet (e.g. a placeholder line item) -- nothing to compare
    # against.
    result = reconcile(boq_quantity=None, boq_uom="m3", measurement_value=50.0, measurement_unit="m3")
    assert result.discrepancy_class == DiscrepancyClass.UNMATCHED.value
    assert result.note == "BOQ item has no tendered quantity"


def test_zero_boq_quantity_matches_zero_measurement() -> None:
    # BOQ tendered 0 (nothing expected here); takeoff also measured 0 --
    # percent-of-zero is undefined, but variance=0 is still a real match.
    result = reconcile(boq_quantity=0.0, boq_uom="m3", measurement_value=0.0, measurement_unit="m3")
    assert result.discrepancy_class == DiscrepancyClass.MATCH.value
    assert result.variance == pytest.approx(0.0)
    assert result.variance_pct is None


def test_zero_boq_quantity_with_nonzero_measurement_is_a_variance() -> None:
    # BOQ tendered 0, but the takeoff found 15 m3 of it -- a real
    # discrepancy (undefined percentage, but very much not a match).
    result = reconcile(boq_quantity=0.0, boq_uom="m3", measurement_value=15.0, measurement_unit="m3")
    assert result.discrepancy_class == DiscrepancyClass.VARIANCE.value
    assert result.variance == pytest.approx(15.0)
    assert result.variance_pct is None
    assert result.note is not None


# ---------------------------------------------------------------------------
# aggregate_measurement_values (Phase 3b: many-to-one links)
# ---------------------------------------------------------------------------


def test_aggregate_sums_same_unit_measurements() -> None:
    # A pipe run split across three sheets: 10.5 + 8.25 + 6.0 = 24.75 m.
    result = aggregate_measurement_values("m", [(10.5, "m"), (8.25, "m"), (6.0, "m")])
    assert result == pytest.approx((24.75, "m"))


def test_aggregate_converts_mixed_units_before_summing() -> None:
    # Two measurements in m, one in mm: 10.0 + 5.0 + (2500 mm = 2.5 m)
    # = 17.5 m.
    result = aggregate_measurement_values("m", [(10.0, "m"), (5.0, "m"), (2500.0, "mm")])
    value, unit = result
    assert unit == "m"
    assert value == pytest.approx(17.5)


def test_aggregate_result_is_in_boq_uom_not_measurement_unit() -> None:
    # BOQ tendered in "LM"; measurements in "m" -- summed value is
    # reported in the BOQ's own uom (LM), a 1:1 alias for m so the number
    # itself is unchanged (3.0 + 4.0 = 7.0), but the returned unit string
    # must be "LM", not "m".
    result = aggregate_measurement_values("LM", [(3.0, "m"), (4.0, "m")])
    assert result == (pytest.approx(7.0), "LM")


def test_aggregate_empty_list_returns_none() -> None:
    assert aggregate_measurement_values("m", []) is None


def test_aggregate_missing_boq_uom_returns_none() -> None:
    assert aggregate_measurement_values(None, [(10.0, "m")]) is None


def test_aggregate_refuses_to_silently_drop_a_dimension_mismatch() -> None:
    # One measurement is a volume (m3), incompatible with the BOQ's length
    # uom (m) -- must return None (refuse entirely), not silently sum only
    # the two compatible ones into a partial, misleading 15.0.
    result = aggregate_measurement_values("m", [(10.0, "m"), (5.0, "m"), (2.0, "m3")])
    assert result is None
