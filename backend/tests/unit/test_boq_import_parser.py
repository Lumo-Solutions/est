from __future__ import annotations

import io

import pytest
from openpyxl import Workbook

from app.boq.import_parser import BoqImportColumnMapping, parse_boq_file, parse_boq_rows
from app.core.errors import ValidationAppError

_DEFAULT_MAPPING = BoqImportColumnMapping(
    item_no_column="Item No", description_column="Description", uom_column="Unit", quantity_column="Quantity"
)

# A small, realistic tender BOQ: two sections (EARTHWORKS, DRAINAGE), each
# with dot-numbered sub-items. Sections themselves carry no unit/quantity
# (a bare heading row) -- a real, common BOQ convention.
_SAMPLE_BOQ_CSV = """Item No,Description,Unit,Quantity
1,EARTHWORKS,,
1.1,Excavation for trench,m3,25
1.2,Backfill and compaction,m3,20
2,DRAINAGE,,
2.1,Supply and lay 300mm dia. pipe,m,150
2.2,Manholes complete,no,6
"""


def test_parses_sample_boq_csv_into_correct_hierarchy() -> None:
    result = parse_boq_file(_SAMPLE_BOQ_CSV.encode("utf-8"), "sample.csv", _DEFAULT_MAPPING)
    assert result.error_count == 0
    assert result.valid_count == 6

    by_item_no = {r.item_no: r for r in result.rows}
    assert by_item_no["1"].parent_item_no is None
    assert by_item_no["1"].description == "EARTHWORKS"
    assert by_item_no["1"].boq_quantity is None  # section heading -- no quantity

    assert by_item_no["1.1"].parent_item_no == "1"
    assert by_item_no["1.1"].uom == "m3"
    assert by_item_no["1.1"].boq_quantity == pytest.approx(25.0)

    assert by_item_no["2.2"].parent_item_no == "2"
    assert by_item_no["2.2"].uom == "no"
    assert by_item_no["2.2"].boq_quantity == pytest.approx(6.0)


def test_parses_sample_boq_as_xlsx_identically() -> None:
    workbook = Workbook()
    sheet = workbook.active
    for line in _SAMPLE_BOQ_CSV.strip().split("\n"):
        cells = line.split(",")
        sheet.append([c if c else None for c in cells])
    buf = io.BytesIO()
    workbook.save(buf)

    result = parse_boq_file(buf.getvalue(), "sample.xlsx", _DEFAULT_MAPPING)
    assert result.error_count == 0
    assert result.valid_count == 6
    by_item_no = {r.item_no: r for r in result.rows}
    assert by_item_no["1.1"].parent_item_no == "1"
    assert by_item_no["1.1"].boq_quantity == pytest.approx(25.0)


def test_xlsx_skips_blank_rows() -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Item No", "Description", "Unit", "Quantity"])
    sheet.append(["1", "Excavation", "m3", "10"])
    sheet.append([None, None, None, None])  # a fully blank trailing row
    sheet.append(["2", "Backfill", "m3", "8"])
    buf = io.BytesIO()
    workbook.save(buf)

    result = parse_boq_file(buf.getvalue(), "sample.xlsx", _DEFAULT_MAPPING)
    assert len(result.rows) == 2
    assert result.error_count == 0


def test_xlsx_respects_header_row_offset() -> None:
    # A real export with a title/logo block before the real header.
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["ACME Constructors Tender BOQ"])
    sheet.append(["Project: Sample"])
    sheet.append(["Item No", "Description", "Unit", "Quantity"])
    sheet.append(["1", "Excavation", "m3", "10"])
    buf = io.BytesIO()
    workbook.save(buf)

    mapping = BoqImportColumnMapping(
        item_no_column="Item No", description_column="Description", uom_column="Unit",
        quantity_column="Quantity", header_row=3,
    )
    result = parse_boq_file(buf.getvalue(), "sample.xlsx", mapping)
    assert result.error_count == 0
    assert result.rows[0].item_no == "1"
    assert result.rows[0].boq_quantity == pytest.approx(10.0)


def test_explicit_parent_column_overrides_dot_numbering_inference() -> None:
    # item_no has no dots at all -- hierarchy can only come from the
    # explicit "Section" column here.
    raw_rows = [
        {"Item No": "A", "Description": "Earthworks section", "Unit": "", "Quantity": "", "Section": ""},
        {"Item No": "A1", "Description": "Excavation", "Unit": "m3", "Quantity": "25", "Section": "A"},
    ]
    mapping = BoqImportColumnMapping(
        item_no_column="Item No", description_column="Description", uom_column="Unit",
        quantity_column="Quantity", parent_column="Section",
    )
    result = parse_boq_rows(raw_rows, mapping)
    assert result.error_count == 0
    by_item_no = {r.item_no: r for r in result.rows}
    assert by_item_no["A1"].parent_item_no == "A"


def test_missing_item_no_is_a_row_error() -> None:
    raw_rows = [{"Item No": "", "Description": "No code", "Unit": "m", "Quantity": "1"}]
    result = parse_boq_rows(raw_rows, _DEFAULT_MAPPING)
    assert result.error_count == 1
    assert "item_no is required" in result.rows[0].errors


def test_missing_description_is_a_row_error() -> None:
    raw_rows = [{"Item No": "1.1", "Description": "", "Unit": "m", "Quantity": "1"}]
    result = parse_boq_rows(raw_rows, _DEFAULT_MAPPING)
    assert result.error_count == 1
    assert "description is required" in result.rows[0].errors


def test_non_numeric_quantity_is_a_row_error() -> None:
    raw_rows = [{"Item No": "1.1", "Description": "Excavation", "Unit": "m3", "Quantity": "twenty-five"}]
    result = parse_boq_rows(raw_rows, _DEFAULT_MAPPING)
    assert result.error_count == 1
    assert "not a number" in result.rows[0].errors[0]


def test_quantity_with_thousands_separator_parses_correctly() -> None:
    # A root item_no (no dot) -- no parent to resolve, isolating this test
    # to just the quantity-parsing behavior.
    raw_rows = [{"Item No": "1", "Description": "Fencing", "Unit": "m", "Quantity": "1,234.5"}]
    result = parse_boq_rows(raw_rows, _DEFAULT_MAPPING)
    assert result.error_count == 0
    assert result.rows[0].boq_quantity == pytest.approx(1234.5)


def test_duplicate_item_no_is_a_row_error_on_both_rows() -> None:
    raw_rows = [
        {"Item No": "1.1", "Description": "First", "Unit": "m", "Quantity": "1"},
        {"Item No": "1.1", "Description": "Duplicate", "Unit": "m", "Quantity": "2"},
    ]
    result = parse_boq_rows(raw_rows, _DEFAULT_MAPPING)
    assert result.error_count == 2
    assert all("duplicate item_no" in r.errors[0] for r in result.rows)


def test_unresolvable_parent_reference_is_a_row_error() -> None:
    raw_rows = [{"Item No": "9.1", "Description": "Orphan", "Unit": "m", "Quantity": "1"}]
    # "9" (the inferred parent from dot-numbering) never appears in the file.
    result = parse_boq_rows(raw_rows, _DEFAULT_MAPPING)
    assert result.error_count == 1
    assert "parent item_no '9' not found" in result.rows[0].errors[0]


def test_self_parent_reference_is_a_row_error() -> None:
    raw_rows = [{"Item No": "A", "Description": "Weird", "Unit": "", "Quantity": "", "Section": "A"}]
    mapping = BoqImportColumnMapping(
        item_no_column="Item No", description_column="Description", uom_column="Unit",
        quantity_column="Quantity", parent_column="Section",
    )
    result = parse_boq_rows(raw_rows, mapping)
    assert any("cannot be its own parent" in e for e in result.rows[0].errors)


def test_circular_parent_reference_is_detected() -> None:
    raw_rows = [
        {"Item No": "A", "Description": "First", "Unit": "", "Quantity": "", "Section": "B"},
        {"Item No": "B", "Description": "Second", "Unit": "", "Quantity": "", "Section": "A"},
    ]
    mapping = BoqImportColumnMapping(
        item_no_column="Item No", description_column="Description", uom_column="Unit",
        quantity_column="Quantity", parent_column="Section",
    )
    result = parse_boq_rows(raw_rows, mapping)
    assert result.error_count == 2
    assert all("circular parent reference" in r.errors[0] for r in result.rows)


def test_unsupported_file_extension_raises() -> None:
    with pytest.raises(ValidationAppError, match="Unsupported"):
        parse_boq_file(b"whatever", "boq.pdf", _DEFAULT_MAPPING)


def test_blank_row_without_optional_columns_is_still_valid() -> None:
    # No uom_column/quantity_column mapped at all -- a minimal BOQ that's
    # just codes and descriptions.
    raw_rows = [{"Code": "1", "Text": "A root item"}]
    mapping = BoqImportColumnMapping(item_no_column="Code", description_column="Text")
    result = parse_boq_rows(raw_rows, mapping)
    assert result.error_count == 0
    assert result.rows[0].uom is None
    assert result.rows[0].boq_quantity is None
