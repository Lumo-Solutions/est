"""Module C Phase 6: pure verification logic for vendor quotations --
subtotal arithmetic, unit-aware quantity comparison, and exclusion-citation
substring verification. Deliberately separate from app/workers/tasks/
quotation_ingestion.py (which orchestrates DB reads/writes) so this can be
unit-tested with no DB/session at all, same separation as
app/procurement/quotation_matching.py.
"""

from __future__ import annotations

from decimal import Decimal

from app.boq import units as unit_conversion


def check_total_mismatch(stated_total: Decimal, line_amounts: list[Decimal | None]) -> bool:
    """True when the vendor's own stated grand total doesn't reconcile
    with the sum of their own line items' amounts, beyond a rounding
    tolerance of 0.01 per line (accumulated rounding, not a single fixed
    cent -- consistent with the per-line 0.01 absolute tolerance already
    used for arithmetic_mismatch, scaled for a sum of many lines)."""
    line_sum = sum((amount for amount in line_amounts if amount is not None), Decimal("0"))
    tolerance = Decimal("0.01") * max(len(line_amounts), 1)
    return abs(stated_total - line_sum) > tolerance


def resolve_quantity_comparison(
    vendor_uom: str | None, boq_uom: str | None, vendor_quantity: Decimal | None
) -> tuple[Decimal | None, bool]:
    """Returns (quantity_to_compare_against_the_BOQ, uom_mismatch).

    - Either uom missing, or they're the same unit string (case/whitespace
      -insensitive): compare the raw vendor_quantity unchanged, no
      mismatch flag -- nothing to convert.
    - Both present, different strings, but the same dimension (e.g. "LM"
      vendor-side vs "M" BOQ-side -- the same length, different
      notation): convert vendor_quantity into the BOQ's own unit before
      comparison.
    - Both present, different strings, and NOT the same dimension (e.g.
      "M" vs "M2"): uom_mismatch=True, quantity_to_compare=None -- a
      category error, not a "the numbers don't match" case; never
      silently compared as if convertible.
    """
    if not boq_uom or not vendor_uom or vendor_quantity is None:
        return vendor_quantity, False
    if vendor_uom.strip().upper() == boq_uom.strip().upper():
        return vendor_quantity, False
    if unit_conversion.convertible(vendor_uom, boq_uom):
        return unit_conversion.convert(float(vendor_quantity), vendor_uom, boq_uom), False
    return None, True


def verify_citation(source_quote_text: str, source_text: str) -> bool:
    """A plain substring search for the (whitespace-collapsed) citation
    within the actual text sent to the extraction model -- never trusted
    from the model's own say-so. False (not an error) when there's no
    source_text at all to search (e.g. an image-only extraction with no
    text layer) -- there is genuinely nothing to verify against in that
    case, not a failed verification of something checkable."""
    if not source_text:
        return False
    return " ".join(source_quote_text.split()) in " ".join(source_text.split())
