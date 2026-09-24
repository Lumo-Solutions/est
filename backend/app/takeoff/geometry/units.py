"""Linear unit conversion between DXF/native drawing units and metres.

Every extractor in this package does its geometry math (stitching
tolerances, triangulation, stationing) in the drawing's **native** units --
whatever coordinates ezdxf hands back, i.e. `$INSUNITS` -- and only converts
to SI at the point of building a `Measurement`. That keeps a single
consistent coordinate system per computation instead of converting
mid-calculation and accumulating rounding drift or, worse, silently mixing
converted and unconverted values in the same comparison.

`$INSUNITS = 0` ("unitless") and any unit this table doesn't recognise
convert to `None`: callers must then either skip the conversion (report the
raw native-unit magnitude with a low confidence and `unit="unitless"`) or
refuse to produce a Measurement at all -- never guess a unit.
"""

from __future__ import annotations

# Exact conversions. `in`/`ft` are the international inch/foot definitions
# (1 in = 25.4 mm exactly, since 1959). `us_survey_ft` is the pre-1959 US
# survey foot, defined as exactly 1200/3937 m -- it differs from the
# international foot by about 2 parts per million, which is negligible for
# a single pipe run but not for a kilometre-scale road alignment, so it is
# kept as its own unit rather than approximated as `ft`.
_METERS_PER_UNIT: dict[str, float] = {
    "mm": 0.001,
    "cm": 0.01,
    "dm": 0.1,
    "m": 1.0,
    "in": 0.0254,
    "ft": 0.3048,
    "us_survey_ft": 1200.0 / 3937.0,
}


def meters_per_unit(unit: str) -> float | None:
    """Conversion factor to metres for `unit`, or `None` for "unitless" or
    any unrecognized unit string (see module docstring)."""
    return _METERS_PER_UNIT.get(unit)


def to_meters(value: float, unit: str) -> float | None:
    factor = meters_per_unit(unit)
    return None if factor is None else value * factor


def to_native_units(value_m: float, unit: str) -> float | None:
    factor = meters_per_unit(unit)
    return None if factor is None else value_m / factor
