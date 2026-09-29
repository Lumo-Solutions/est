"""Pre-fill for the BOQ import wizard from a classified tender workbook.

Pure: works from the (column letter, header text) cells intake stored in the
document's metadata. The wizard's mapping takes header TEXT for item,
description, unit, quantity and parent, but column LETTERS for rate and amount
(app/schemas/boq.py::BoqImportColumnMappingIn), so both are kept here.
"""

from __future__ import annotations

from app.intake.extract import _HEADER_GROUPS


def _match(cells: list[tuple[str, str]], group: str) -> tuple[str, str] | None:
    words = _HEADER_GROUPS[group]
    for letter, name in cells:
        if " ".join(name.strip().lower().split()) in words:
            return letter, name
    return None


def suggest_mapping(metadata: dict) -> dict:
    cells = [(str(c[0]), str(c[1])) for c in metadata.get("boq_columns", []) if len(c) >= 2]
    item, desc, unit, qty = (_match(cells, g) for g in ("item", "description", "unit", "qty"))
    rate, amount = _match(cells, "rate"), _match(cells, "amount")
    return {
        "sheet_name": metadata.get("boq_sheet"),
        "header_row": metadata.get("header_row") or 1,
        "item_no_column": item[1] if item else "",
        "description_column": desc[1] if desc else "",
        "uom_column": unit[1] if unit else "",
        "quantity_column": qty[1] if qty else "",
        "parent_column": "",
        "rate_column": rate[0] if rate else "",
        "amount_column": amount[0] if amount else "",
    }
