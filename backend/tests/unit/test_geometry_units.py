from __future__ import annotations

import pytest

from app.takeoff.geometry.units import meters_per_unit, to_meters, to_native_units


def test_millimeters_to_meters() -> None:
    # 1000 mm is exactly 1 m by definition.
    assert to_meters(1000.0, "mm") == pytest.approx(1.0)


def test_feet_to_meters() -> None:
    # 1 international foot = 0.3048 m exactly -> 10 ft = 3.048 m.
    assert to_meters(10.0, "ft") == pytest.approx(3.048)


def test_us_survey_foot_differs_from_international_foot() -> None:
    # US survey foot = 1200/3937 m = 0.304800609601... m (NIST definition).
    # Per foot, the difference from the international foot (0.3048 m
    # exactly) is 1200/3937 - 0.3048 = 0.0000006096... m. Over 1,000,000
    # survey feet that accumulates to 0.0000006096 * 1e6 = 0.6096 m (609.6mm)
    # -- small per-unit, but not zero, which is exactly why it's kept as its
    # own unit here rather than an alias for "ft".
    survey_ft_m = to_meters(1.0, "us_survey_ft")
    intl_ft_m = to_meters(1.0, "ft")
    assert survey_ft_m == pytest.approx(1200.0 / 3937.0)
    assert survey_ft_m != intl_ft_m
    assert (survey_ft_m - intl_ft_m) * 1_000_000 == pytest.approx(0.6096, abs=1e-4)


def test_unitless_and_unknown_units_return_none() -> None:
    assert meters_per_unit("unitless") is None
    assert to_meters(5.0, "unitless") is None
    assert to_meters(5.0, "furlongs") is None


def test_round_trip_to_native_units() -> None:
    # 2.5 m in mm is 2500 mm; converting back gives 2.5 m again.
    native = to_native_units(2.5, "mm")
    assert native == pytest.approx(2500.0)
    assert to_meters(native, "mm") == pytest.approx(2.5)
