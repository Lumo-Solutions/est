"""Unit dimension checking + conversion for BOQ reconciliation.

Deliberately separate from `app.takeoff.geometry.units` (native-drawing-unit
<-> metre conversion for the geometry extractors): that module only ever
deals with *length* in a DXF's native units. This one compares a BOQ
item's free-text `uom` (typed by a human, or later parsed from an Excel
import -- see docs/boq-reconciliation.md) against a `drawing_measurements`
row's `unit` (always exactly "m"/"m2"/"m3"/"unitless" today, since the
geometry extractors always normalize to SI when a conversion factor is
known -- see `app.takeoff.geometry.units`), across four dimensions
(length/area/volume/count).

Not exhaustive: this is a starting alias list covering common Gulf/British
QS abbreviations (`LM`, `SQM`, `CUM`, `NR`, ...) alongside SI unit strings,
extend as real tender BOQs turn up units this doesn't recognize. An
unrecognized unit on either side is never guessed at -- it's simply
"not convertible", which `app.boq.reconciliation.reconcile()` turns into
`unmatched`, never a silently wrong comparison.
"""

from __future__ import annotations

from enum import StrEnum


class Dimension(StrEnum):
    LENGTH = "length"
    AREA = "area"
    VOLUME = "volume"
    COUNT = "count"


# unit string (case-insensitive) -> (dimension, factor to that dimension's
# base unit: m for length, m2 for area, m3 for volume, 1 for count).
_UNITS: dict[str, tuple[Dimension, float]] = {
    # length
    "M": (Dimension.LENGTH, 1.0),
    "MM": (Dimension.LENGTH, 0.001),
    "CM": (Dimension.LENGTH, 0.01),
    "KM": (Dimension.LENGTH, 1000.0),
    "FT": (Dimension.LENGTH, 0.3048),
    "IN": (Dimension.LENGTH, 0.0254),
    "LM": (Dimension.LENGTH, 1.0),  # "linear metre" -- common BOQ abbreviation for m
    "RM": (Dimension.LENGTH, 1.0),  # "running metre" -- same
    # area
    "M2": (Dimension.AREA, 1.0),
    "MM2": (Dimension.AREA, 1e-6),
    "CM2": (Dimension.AREA, 1e-4),
    "FT2": (Dimension.AREA, 0.09290304),
    "SQM": (Dimension.AREA, 1.0),  # common BOQ abbreviation for m2
    # volume
    "M3": (Dimension.VOLUME, 1.0),
    "MM3": (Dimension.VOLUME, 1e-9),
    "CM3": (Dimension.VOLUME, 1e-6),
    "FT3": (Dimension.VOLUME, 0.028316846592),
    "CUM": (Dimension.VOLUME, 1.0),  # common BOQ abbreviation for m3
    # count (dimensionless -- factor is always 1)
    "NO": (Dimension.COUNT, 1.0),
    "NR": (Dimension.COUNT, 1.0),  # "number" -- common BOQ abbreviation
    "EA": (Dimension.COUNT, 1.0),
    "EACH": (Dimension.COUNT, 1.0),
    "ITEM": (Dimension.COUNT, 1.0),
    "PCS": (Dimension.COUNT, 1.0),
}


def _normalize(unit: str) -> str:
    return unit.strip().upper()


def unit_dimension(unit: str) -> Dimension | None:
    """None for an unrecognized unit -- never guessed at."""
    entry = _UNITS.get(_normalize(unit))
    return entry[0] if entry else None


def convertible(from_unit: str, to_unit: str) -> bool:
    from_dim = unit_dimension(from_unit)
    to_dim = unit_dimension(to_unit)
    return from_dim is not None and from_dim == to_dim


def convert(value: float, from_unit: str, to_unit: str) -> float | None:
    """None if either unit is unrecognized or they're different dimensions
    (e.g. a length and a volume) -- converting those isn't a unit-system
    problem, it's a category error, and this never silently returns a
    number for it."""
    if not convertible(from_unit, to_unit):
        return None
    from_factor = _UNITS[_normalize(from_unit)][1]
    to_factor = _UNITS[_normalize(to_unit)][1]
    return value * from_factor / to_factor
