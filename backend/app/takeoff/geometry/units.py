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
    # PDF page-space points (1/72 in), exact under the same in=25.4mm
    # definition above -- see sheet_scale_factor()'s docstring for why
    # this one unit, alone, also needs the sheet's scale_ratio folded in.
    "pt": 0.0254 / 72.0,
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


def sheet_scale_factor(unit: str | None, scale_ratio: float | None) -> float | None:
    """Combined native-unit-to-metres factor for one sheet's geometry,
    folding in the sheet's paper-scale ratio when (and only when) the
    geometry's own native unit is itself paper-space ("pt", PDF page
    points -- Module B Phase 4a). DXF geometry is modelled true-to-real-
    world-scale via its own $INSUNITS already (see this module's
    docstring) -- multiplying by scale_ratio there too would double-scale
    a DXF drawing whose title block also happens to state a print scale,
    a real ambiguity this deliberately avoids rather than guesses through."""
    base = meters_per_unit(unit) if unit else None
    if base is None:
        return None
    if unit == "pt" and scale_ratio:
        # scale_ratio round-trips through a Numeric(12, 6) column, so a
        # value freshly read back from the DB (e.g. a reverted calibration
        # -- app.services.takeoff::revert_scale_calibration) arrives as a
        # Decimal, not a float; `float * Decimal` raises TypeError.
        return base * float(scale_ratio)
    return base
