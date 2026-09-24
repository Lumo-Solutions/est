from __future__ import annotations

import pytest

from app.boq.units import Dimension, convert, convertible, unit_dimension


def test_unit_dimension_recognizes_length_area_volume_count() -> None:
    assert unit_dimension("m") == Dimension.LENGTH
    assert unit_dimension("mm") == Dimension.LENGTH
    assert unit_dimension("LM") == Dimension.LENGTH
    assert unit_dimension("m2") == Dimension.AREA
    assert unit_dimension("SQM") == Dimension.AREA
    assert unit_dimension("m3") == Dimension.VOLUME
    assert unit_dimension("CUM") == Dimension.VOLUME
    assert unit_dimension("no") == Dimension.COUNT
    assert unit_dimension("NR") == Dimension.COUNT


def test_unit_dimension_is_case_and_whitespace_insensitive() -> None:
    assert unit_dimension("  M3  ") == Dimension.VOLUME
    assert unit_dimension("m3") == unit_dimension("M3")


def test_unit_dimension_unrecognized_returns_none() -> None:
    assert unit_dimension("sqft") is None
    assert unit_dimension("unitless") is None
    assert unit_dimension("") is None


def test_convertible_same_dimension_true() -> None:
    assert convertible("m", "mm") is True
    assert convertible("m3", "CUM") is True


def test_convertible_different_dimension_false() -> None:
    assert convertible("m", "m2") is False
    assert convertible("m3", "m") is False


def test_convertible_unrecognized_unit_false() -> None:
    assert convertible("m", "sqft") is False
    assert convertible("sqft", "sqft") is False  # both unrecognized -- must not compare equal-by-accident


def test_convert_millimeters_to_meters() -> None:
    # 5000 mm = 5.0 m exactly.
    assert convert(5000.0, "mm", "m") == pytest.approx(5.0)


def test_convert_meters_to_millimeters() -> None:
    assert convert(5.0, "m", "mm") == pytest.approx(5000.0)


def test_convert_cubic_millimeters_to_cubic_meters() -> None:
    # Volume scales with the cube of the linear factor: 1 mm = 0.001 m,
    # so 1 mm3 = 0.001^3 m3 = 1e-9 m3.
    # 500,000,000 mm3 * 1e-9 = 0.5 m3.
    assert convert(500_000_000.0, "mm3", "m3") == pytest.approx(0.5)


def test_convert_boq_abbreviations_are_aliases_for_si() -> None:
    # LM/CUM/SQM are just alternate spellings of m/m3/m2 -- a 1:1 identity
    # conversion (factor 1.0 in both directions).
    assert convert(12.5, "LM", "m") == pytest.approx(12.5)
    assert convert(3.2, "m3", "CUM") == pytest.approx(3.2)


def test_convert_different_dimensions_returns_none() -> None:
    assert convert(10.0, "m", "m2") is None
    assert convert(10.0, "m3", "m") is None


def test_convert_unrecognized_unit_returns_none() -> None:
    assert convert(10.0, "m", "sqft-typo") is None
