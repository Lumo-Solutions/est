"""BOQ import from Excel (.xlsx) or CSV (Phase 3b(c)) -- PDF BOQs are
explicitly out of scope (see docs/boq-reconciliation.md). Pure parsing
here, no DB/session involvement, so a dry-run preview and the actual
commit can share the exact same logic and never disagree about what would
be created.

**Hierarchy**: built from item_no's own dot-numbering (e.g. "1.1.2"'s
parent is "1.1") by default -- no separate parent column needed for the
common case. `mapping.parent_column`, when given and non-empty for a row,
overrides that inference (for a real tender BOQ that has an explicit
"Section"/"Parent" column instead of, or in addition to, dot-numbered item
codes). Parent references only resolve *within the same file* -- this
always builds a fresh hierarchy of new items, never attaches into an
existing one (see app/services/boq_import.py::commit_import).
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field

from openpyxl import load_workbook

from app.core.errors import ValidationAppError


@dataclass(frozen=True, slots=True)
class BoqImportColumnMapping:
    item_no_column: str
    description_column: str
    uom_column: str | None = None
    quantity_column: str | None = None
    parent_column: str | None = None
    # Module D2: the tender BOQ's rate/amount columns, by letter (e.g.
    # "F"). Blank at import time -- never parsed as values -- purely
    # recorded so a later settlement export can write into the exact
    # original cell (app/services/boq_import.py::commit_import,
    # app/models/boq.py::BoqImportBatch). None when the template has no
    # such columns yet, or the caller doesn't know them.
    rate_column: str | None = None
    amount_column: str | None = None
    # 1-indexed row containing the column headers this mapping's *_column
    # values refer to (some real tender BOQ exports have a title/logo
    # block above the real header row). CSV always uses row 1 -- most
    # CSV exports don't carry that extra header cruft, and skipping rows
    # would need this same field anyway if one does.
    header_row: int = 1


@dataclass(slots=True)
class ParsedBoqRow:
    row_number: int  # 1-indexed source row, for error messages -- not the header
    item_no: str | None
    description: str | None
    uom: str | None
    boq_quantity: float | None
    parent_item_no: str | None
    errors: list[str] = field(default_factory=list)


@dataclass(slots=True)
class BoqImportResult:
    rows: list[ParsedBoqRow]

    @property
    def valid_count(self) -> int:
        return sum(1 for r in self.rows if not r.errors)

    @property
    def error_count(self) -> int:
        return sum(1 for r in self.rows if r.errors)


def _read_csv_rows(data: bytes) -> list[dict[str, str]]:
    text = data.decode("utf-8-sig")  # -sig strips a BOM if Excel added one on CSV export
    reader = csv.DictReader(io.StringIO(text))
    return [dict(row) for row in reader]


def _read_xlsx_rows(data: bytes, header_row: int) -> list[dict[str, str]]:
    workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    sheet = workbook.active
    rows_iter = sheet.iter_rows(values_only=True)
    for _ in range(header_row - 1):
        next(rows_iter, None)
    headers = [str(h).strip() if h is not None else "" for h in (next(rows_iter, None) or ())]
    result = []
    for values in rows_iter:
        if values is None or all(v is None for v in values):
            continue  # skip fully blank rows (trailing rows are common in real exports)
        row = {headers[i]: values[i] for i in range(min(len(headers), len(values)))}
        result.append({k: ("" if v is None else str(v)) for k, v in row.items()})
    return result


def _parse_quantity(raw: str | None) -> tuple[float | None, str | None]:
    """Returns (value, error). Blank is valid (None, no error) -- not
    every BOQ line item necessarily has a quantity (e.g. a bare section
    heading)."""
    if raw is None or raw.strip() == "":
        return None, None
    cleaned = raw.strip().replace(",", "")  # "1,234.5" -- a common thousands-separator export
    try:
        return float(cleaned), None
    except ValueError:
        return None, f"quantity {raw!r} is not a number"


def parse_boq_rows(raw_rows: list[dict[str, str]], mapping: BoqImportColumnMapping) -> BoqImportResult:
    parsed: list[ParsedBoqRow] = []
    for i, raw in enumerate(raw_rows, start=1):
        errors: list[str] = []
        item_no = (raw.get(mapping.item_no_column) or "").strip() or None
        description = (raw.get(mapping.description_column) or "").strip() or None
        uom = (raw.get(mapping.uom_column) or "").strip() or None if mapping.uom_column else None
        quantity_raw = raw.get(mapping.quantity_column) if mapping.quantity_column else None
        boq_quantity, quantity_error = _parse_quantity(quantity_raw)
        if quantity_error:
            errors.append(quantity_error)

        parent_item_no: str | None = None
        if mapping.parent_column:
            parent_item_no = (raw.get(mapping.parent_column) or "").strip() or None
        if parent_item_no is None and item_no and "." in item_no:
            parent_item_no = item_no.rsplit(".", 1)[0]

        if not item_no:
            errors.append("item_no is required")
        if not description:
            errors.append("description is required")

        parsed.append(ParsedBoqRow(i, item_no, description, uom, boq_quantity, parent_item_no, errors))

    _validate_hierarchy(parsed)
    return BoqImportResult(parsed)


def _validate_hierarchy(rows: list[ParsedBoqRow]) -> None:
    item_no_counts: dict[str, int] = {}
    for r in rows:
        if r.item_no:
            item_no_counts[r.item_no] = item_no_counts.get(r.item_no, 0) + 1
    known_item_nos = set(item_no_counts)

    for r in rows:
        if r.item_no and item_no_counts[r.item_no] > 1:
            r.errors.append(f"duplicate item_no {r.item_no!r} in this file")
        if r.parent_item_no is None:
            continue
        if r.parent_item_no == r.item_no:
            r.errors.append("an item cannot be its own parent")
        elif r.parent_item_no not in known_item_nos:
            r.errors.append(f"parent item_no {r.parent_item_no!r} not found in this file")

    # Cycle check (only reachable via an explicit parent_column -- dot-
    # numbering inference can never produce a cycle on its own).
    parent_by_item_no = {r.item_no: r.parent_item_no for r in rows if r.item_no}
    for r in rows:
        if not r.item_no:
            continue
        visited = {r.item_no}
        current = r.parent_item_no
        while current is not None:
            if current in visited:
                r.errors.append(f"circular parent reference involving {r.item_no!r}")
                break
            visited.add(current)
            current = parent_by_item_no.get(current)


def parse_boq_file(data: bytes, filename: str, mapping: BoqImportColumnMapping) -> BoqImportResult:
    lower = filename.lower()
    if lower.endswith(".csv"):
        raw_rows = _read_csv_rows(data)
    elif lower.endswith(".xlsx"):
        raw_rows = _read_xlsx_rows(data, mapping.header_row)
    else:
        raise ValidationAppError(f"Unsupported BOQ import file type: {filename!r} (only .xlsx and .csv are supported)")
    return parse_boq_rows(raw_rows, mapping)
