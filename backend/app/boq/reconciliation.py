"""Pure BOQ-vs-takeoff reconciliation math (Phase 3): given a BOQ line
item's tendered quantity and an optionally-linked drawing_measurement,
compute the variance and classify it into exactly one of three classes,
per MASTER_SRS.MD's "three-class discrepancy flagging" (Module B).

No DB/ORM types here on purpose -- everything takes plain values so the
classification rules can be hand-checked and unit tested in isolation from
persistence (app/services/boq.py calls this and writes the result).

**The three classes are not specified numerically anywhere in the SRS** --
only "three-class discrepancy flagging" is named. The taxonomy and the
2%/tolerance default below are this implementation's own choice, not a
transcription of a documented business rule, and should be validated
against real tender/QS practice:

- ``match``: a measurement is linked and its value is within
  ``tolerance_pct`` of the BOQ's tendered quantity.
- ``variance``: a measurement is linked but outside that tolerance.
- ``unmatched``: no measurement is linked yet, *or* one is linked but its
  unit is a different *dimension* (length/area/volume/count -- see
  ``app.boq.units``) than the BOQ item's uom, e.g. comparing a length in
  metres against a volume in cubic metres is meaningless, not "close" or
  "far" (see ``reconciliation_note``). Same-dimension, different-unit pairs
  (e.g. BOQ tendered in "m", measurement in "mm") are converted, not
  rejected.

A BOQ line item can link *several* measurements (``app.models.boq.
BoqLineItemMeasurement``, e.g. a pipe run's length summed across several
sheets) -- ``aggregate_measurement_values()`` below sums them (each
converted into the BOQ's own uom) into the single ``(value, unit)`` pair
``reconcile()`` compares against. Aggregation only ever sums
*same-dimension* values; a measurement whose unit isn't convertible to the
BOQ's uom should be rejected at link time
(``app/services/boq.py::add_measurement_link``), but
``aggregate_measurement_values()`` still refuses to silently drop it and
sum the rest if one slips through.

**Explicitly out of scope for this pass** (see docs/architecture.md's
Module B "deferred" list): the SRS also calls for *semantic*
cross-referencing (pgvector RAG) to automatically find which measurement a
BOQ line item's description refers to. This module only classifies a
quantity comparison once at least one link already exists -- linking
itself is a manual, explicit action
(app/services/boq.py::add_measurement_link) for now.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from app.boq import units as unit_conversion


class DiscrepancyClass(StrEnum):
    MATCH = "match"
    VARIANCE = "variance"
    UNMATCHED = "unmatched"


@dataclass(frozen=True, slots=True)
class ReconciliationConfig:
    # Percent of the BOQ's tendered quantity; |variance| at or below this
    # is a MATCH, above it is a VARIANCE. Applies symmetrically to
    # over-measurement and under-measurement.
    tolerance_pct: float = 2.0


DEFAULT_RECONCILIATION_CONFIG = ReconciliationConfig()


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    discrepancy_class: str
    variance: float | None
    variance_pct: float | None
    note: str | None


def reconcile(
    boq_quantity: float | None,
    boq_uom: str | None,
    measurement_value: float | None,
    measurement_unit: str | None,
    config: ReconciliationConfig = DEFAULT_RECONCILIATION_CONFIG,
) -> ReconciliationResult:
    if measurement_value is None:
        return ReconciliationResult(DiscrepancyClass.UNMATCHED.value, None, None, "No linked takeoff measurement")

    if not boq_uom or not measurement_unit:
        return ReconciliationResult(
            DiscrepancyClass.UNMATCHED.value, None, None,
            "Missing unit on the BOQ item or the linked measurement -- nothing to compare",
        )

    if boq_quantity is None:
        return ReconciliationResult(DiscrepancyClass.UNMATCHED.value, None, None, "BOQ item has no tendered quantity")

    # Converted into the BOQ's own uom, so `variance` is always expressed
    # in the unit the estimator actually tendered in -- not the geometry
    # extractor's SI unit, if those two differ (e.g. BOQ in "LM", takeoff
    # in "m": same dimension, different unit string).
    converted_value = unit_conversion.convert(measurement_value, measurement_unit, boq_uom)
    if converted_value is None:
        boq_dim = unit_conversion.unit_dimension(boq_uom)
        measurement_dim = unit_conversion.unit_dimension(measurement_unit)
        if boq_dim is None or measurement_dim is None:
            note = f"Unrecognized unit: BOQ uom {boq_uom!r} or measurement unit {measurement_unit!r}"
        else:
            note = (
                f"Unit mismatch: BOQ uom {boq_uom!r} ({boq_dim.value}) vs measurement unit "
                f"{measurement_unit!r} ({measurement_dim.value}) -- different dimensions, not comparable"
            )
        return ReconciliationResult(DiscrepancyClass.UNMATCHED.value, None, None, note)

    variance = converted_value - boq_quantity

    if boq_quantity == 0.0:
        # Percent-of-zero is undefined; a linked measurement of exactly
        # zero too is a real match (both claim nothing exists here), any
        # nonzero measurement is a real variance -- not "infinite percent
        # within tolerance".
        is_match = variance == 0.0
        return ReconciliationResult(
            DiscrepancyClass.MATCH.value if is_match else DiscrepancyClass.VARIANCE.value,
            variance, None,
            None if is_match else "BOQ tendered zero quantity but a nonzero measurement is linked",
        )

    variance_pct = (variance / boq_quantity) * 100.0
    discrepancy_class = (
        DiscrepancyClass.MATCH.value if math.fabs(variance_pct) <= config.tolerance_pct else DiscrepancyClass.VARIANCE.value
    )
    return ReconciliationResult(discrepancy_class, variance, variance_pct, None)


def aggregate_measurement_values(boq_uom: str | None, measurements: list[tuple[float, str]]) -> tuple[float, str] | None:
    """Sums each (value, unit) pair converted into `boq_uom`. Returns None
    -- meaning "nothing usable to compare", the same as an empty list --
    when `boq_uom` is missing, the list is empty, or *any* measurement's
    unit isn't convertible to `boq_uom`: a dimension mismatch among linked
    measurements should be prevented at link time
    (app/services/boq.py::add_measurement_link), but this never silently
    drops the mismatched one and sums the rest into a partial, misleading
    total."""
    if not boq_uom or not measurements:
        return None
    total = 0.0
    for value, unit in measurements:
        converted = unit_conversion.convert(value, unit, boq_uom)
        if converted is None:
            return None
        total += converted
    return total, boq_uom
