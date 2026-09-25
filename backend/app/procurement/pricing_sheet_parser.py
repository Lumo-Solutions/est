"""Deterministic parser for a vendor's returned pricing sheet -- our own xlsx
template (app/procurement/pricing_sheet.py), round-tripped.

SRS change #1: row identity comes from the hidden, locked column G
(row-id == boq_line_item_id, written per-row by build_pricing_workbook), not
row position. If the returned sheet's set of row-ids doesn't exactly match
what we sent -- a row reordered (fine, ids just move with their row, no
issue), inserted, deleted, or duplicated -- the *entire* sheet is rejected to
needs-review rather than partially mapped by best-effort. `_meta`'s
rfq_id/rfq_ref/reply_token must also match the RFQ the inbound email was
already matched to, or this isn't trusted as an unmodified copy of what we
sent at all.

SRS change #2: a Rate cell that is a formula with no cached value, or
non-numeric text, is flagged for review -- never silently read as 0/blank.
A genuinely empty Rate cell (vendor simply didn't price that line) is not an
error and is left as unit_price=None with no flag.
"""

from __future__ import annotations

import io
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from openpyxl import load_workbook
from openpyxl.cell.cell import Cell

from app.procurement.pricing_sheet import FIRST_DATA_ROW

_YES_VALUES = {"y", "yes", "true", "incl", "inclusive"}
_NO_VALUES = {"n", "no", "false", "excl", "exclusive"}


@dataclass(frozen=True, slots=True)
class ParsedRateCell:
    value: Decimal | None
    needs_review: bool
    review_reason: str | None


@dataclass(frozen=True, slots=True)
class ParsedPricingRow:
    boq_line_item_id: uuid.UUID
    rate: ParsedRateCell
    remarks: str | None


@dataclass(frozen=True, slots=True)
class ParsedPricingSheet:
    """`ok=False` means the whole sheet failed identity verification (SRS
    change #1) -- the caller must treat this quotation as needs-review with
    no line items created, not fall back to any partial mapping."""

    ok: bool
    reason: str | None
    currency: str | None
    vat_inclusive: bool | None
    rows: list[ParsedPricingRow]


def _read_rate_cell(formula_cell: Cell, value_cell: Cell) -> ParsedRateCell:
    if formula_cell.value is None:
        return ParsedRateCell(value=None, needs_review=False, review_reason=None)

    if formula_cell.data_type == "f":
        cached = value_cell.value
        if cached is None:
            return ParsedRateCell(value=None, needs_review=True, review_reason="formula rate cell has no cached value")
        if not isinstance(cached, (int, float, Decimal)):
            return ParsedRateCell(value=None, needs_review=True, review_reason="formula rate cell's cached value is non-numeric")
        return ParsedRateCell(value=Decimal(str(cached)), needs_review=False, review_reason=None)

    raw = formula_cell.value
    if isinstance(raw, (int, float, Decimal)):
        return ParsedRateCell(value=Decimal(str(raw)), needs_review=False, review_reason=None)
    try:
        return ParsedRateCell(value=Decimal(str(raw).strip()), needs_review=False, review_reason=None)
    except (InvalidOperation, ValueError):
        return ParsedRateCell(value=None, needs_review=True, review_reason=f"rate cell contains non-numeric text: {raw!r}")


def _parse_vat_inclusive(raw: object) -> bool | None:
    if raw is None:
        return None
    text = str(raw).strip().lower()
    if text in _YES_VALUES:
        return True
    if text in _NO_VALUES:
        return False
    return None


def _parse_currency(raw: object) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip().upper()
    return text if len(text) == 3 and text.isalpha() else None


def looks_like_our_pricing_sheet(data: bytes) -> bool:
    """Cheap routing check the worker uses before deciding between the
    deterministic parser and the LLM path -- true only means "has our sheet
    names", not that it will actually parse cleanly (that's parse_pricing_sheet's
    job, including the meta rfq_id/reply_token/row-id checks)."""
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True)
    except Exception:  # noqa: BLE001
        return False
    return "_meta" in wb.sheetnames and "Pricing" in wb.sheetnames


def dump_workbook_text(data: bytes) -> str:
    """Flattens every cell of every sheet into text, for the LLM path when a
    vendor returns a spreadsheet that isn't our own template."""
    wb = load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    lines: list[str] = []
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            cells = [str(v) for v in row if v is not None]
            if cells:
                lines.append("\t".join(cells))
    return "\n".join(lines)


def parse_pricing_sheet(
    data: bytes, *, expected_rfq_id: uuid.UUID, expected_reply_token: str, expected_boq_line_item_ids: set[uuid.UUID]
) -> ParsedPricingSheet:
    try:
        wb_formulas = load_workbook(io.BytesIO(data), data_only=False)
        wb_values = load_workbook(io.BytesIO(data), data_only=True)
    except Exception as exc:  # noqa: BLE001 -- any corrupt/unexpected workbook is needs-review, not a crash
        return ParsedPricingSheet(ok=False, reason=f"could not open workbook: {exc}", currency=None, vat_inclusive=None, rows=[])

    if "_meta" not in wb_formulas.sheetnames or "Pricing" not in wb_formulas.sheetnames:
        return ParsedPricingSheet(ok=False, reason="missing _meta or Pricing sheet", currency=None, vat_inclusive=None, rows=[])

    meta = wb_formulas["_meta"]
    meta_values = {row[0].value: row[1].value for row in meta.iter_rows(min_row=1, max_row=3)}
    if str(meta_values.get("rfq_id")) != str(expected_rfq_id) or meta_values.get("reply_token") != expected_reply_token:
        return ParsedPricingSheet(ok=False, reason="_meta rfq_id/reply_token does not match the matched RFQ", currency=None, vat_inclusive=None, rows=[])

    ws_formulas = wb_formulas["Pricing"]
    ws_values = wb_values["Pricing"]

    currency = _parse_currency(ws_values["B2"].value)
    vat_inclusive = _parse_vat_inclusive(ws_values["E2"].value)

    rows: list[ParsedPricingRow] = []
    seen_ids: list[uuid.UUID] = []
    row = FIRST_DATA_ROW
    while ws_formulas[f"G{row}"].value is not None:
        raw_id = str(ws_formulas[f"G{row}"].value).strip()
        try:
            boq_line_item_id = uuid.UUID(raw_id)
        except ValueError:
            return ParsedPricingSheet(ok=False, reason=f"row {row} has an unrecognizable row-id {raw_id!r}", currency=currency, vat_inclusive=vat_inclusive, rows=[])
        seen_ids.append(boq_line_item_id)
        rate = _read_rate_cell(ws_formulas[f"E{row}"], ws_values[f"E{row}"])
        remarks_raw = ws_values[f"F{row}"].value
        rows.append(ParsedPricingRow(boq_line_item_id=boq_line_item_id, rate=rate, remarks=str(remarks_raw) if remarks_raw is not None else None))
        row += 1

    if len(seen_ids) != len(set(seen_ids)):
        return ParsedPricingSheet(ok=False, reason="duplicate row-id found -- a row appears to have been copy-pasted", currency=currency, vat_inclusive=vat_inclusive, rows=[])
    if set(seen_ids) != expected_boq_line_item_ids:
        missing = expected_boq_line_item_ids - set(seen_ids)
        extra = set(seen_ids) - expected_boq_line_item_ids
        return ParsedPricingSheet(
            ok=False,
            reason=f"row-id set does not match the RFQ's items (missing={len(missing)}, unexpected={len(extra)}) -- rows were likely inserted, deleted, or the id column was edited",
            currency=currency, vat_inclusive=vat_inclusive, rows=[],
        )

    return ParsedPricingSheet(ok=True, reason=None, currency=currency, vat_inclusive=vat_inclusive, rows=rows)
