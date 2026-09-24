"""Generates the .xlsx pricing sheet attached to every dispatched RFQ.

Two worksheets:
  - "Pricing" (visible): item_no/description/unit/quantity columns are
    filled in and cell-locked; rate/remarks columns are left blank and
    unlocked for the vendor to fill in. Sheet protection is a UX guardrail
    (stops a vendor accidentally overtyping a quantity), not a security
    boundary -- it carries no password.
  - "_meta" (hidden): rfq_ref/rfq_id/reply_token plus one row per pricing
    row mapping row_index -> boq_line_item_id, so Module C2's ingestion can
    match a returned row back to its BOQ line item deterministically even
    if the vendor reorders or deletes rows, without relying on the visible
    item_no text matching exactly.
"""

from __future__ import annotations

import hashlib
import io
import uuid

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill, Protection
from openpyxl.worksheet.worksheet import Worksheet

from app.procurement.content import RfqLineItem

_HEADER_FILL = PatternFill(start_color="FFE0E0E0", end_color="FFE0E0E0", fill_type="solid")
_HEADER_FONT = Font(bold=True)
_LOCKED_COLUMNS = ("A", "B", "C", "D")  # Item No, Description, Unit, Quantity
# Rate/Remarks (E, F) are the only cells left unlocked -- see _write_pricing_sheet.
_FIRST_DATA_ROW = 4


def _write_pricing_sheet(ws: Worksheet, package_name: str, rfq_ref: str, items: list[RfqLineItem]) -> None:
    ws.title = "Pricing"
    ws["A1"] = f"RFQ {rfq_ref} - {package_name}"
    ws["A1"].font = Font(bold=True, size=13)
    ws.merge_cells("A1:F1")

    headers = ["Item No", "Description", "Unit", "Quantity", "Rate", "Remarks"]
    for col_idx, header in enumerate(headers, start=1):
        cell = ws.cell(row=3, column=col_idx, value=header)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL

    for offset, item in enumerate(items):
        row = _FIRST_DATA_ROW + offset
        ws.cell(row=row, column=1, value=item.item_no)
        ws.cell(row=row, column=2, value=item.description)
        ws.cell(row=row, column=3, value=item.uom or "")
        ws.cell(row=row, column=4, value=float(item.quantity) if item.quantity is not None else None)
        # Rate (E) and Remarks (F) are left blank for the vendor.

    ws.column_dimensions["A"].width = 12
    ws.column_dimensions["B"].width = 50
    ws.column_dimensions["C"].width = 10
    ws.column_dimensions["D"].width = 12
    ws.column_dimensions["E"].width = 14
    ws.column_dimensions["F"].width = 30
    ws["B3"].alignment = Alignment(wrap_text=True)

    last_row = _FIRST_DATA_ROW + max(len(items) - 1, 0)
    for row in range(1, last_row + 1):
        for col_letter in ("A", "B", "C", "D", "E", "F"):
            cell = ws[f"{col_letter}{row}"]
            cell.protection = Protection(locked=col_letter in _LOCKED_COLUMNS or row < _FIRST_DATA_ROW)
    ws.protection.sheet = True


def _write_meta_sheet(
    wb: Workbook, *, rfq_id: uuid.UUID, rfq_ref: str, reply_token: str, items: list[RfqLineItem]
) -> None:
    ws = wb.create_sheet("_meta")
    ws.append(["rfq_id", str(rfq_id)])
    ws.append(["rfq_ref", rfq_ref])
    ws.append(["reply_token", reply_token])
    ws.append([])
    ws.append(["pricing_row", "boq_line_item_id", "item_no"])
    for offset, item in enumerate(items):
        ws.append([_FIRST_DATA_ROW + offset, str(item.boq_line_item_id), item.item_no])
    ws.sheet_state = "hidden"


def build_pricing_workbook(
    *, rfq_id: uuid.UUID, rfq_ref: str, reply_token: str, package_name: str, items: list[RfqLineItem]
) -> tuple[bytes, str]:
    """Returns (xlsx_bytes, sha256_hex) -- the sha256 is stored verbatim on
    Rfq.attachment_sha256 as the durable record of what was sent."""
    wb = Workbook()
    pricing_ws = wb.active
    assert pricing_ws is not None
    _write_pricing_sheet(pricing_ws, package_name, rfq_ref, items)
    _write_meta_sheet(wb, rfq_id=rfq_id, rfq_ref=rfq_ref, reply_token=reply_token, items=items)

    buf = io.BytesIO()
    wb.save(buf)
    data = buf.getvalue()
    return data, hashlib.sha256(data).hexdigest()
