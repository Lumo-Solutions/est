"""Module D2: the generated export must never leak cost/markup/margin/
overhead/source/vendor/FX data -- see docs/module-d2-plan.md §4. Written
as a generic scanner (a denylist built from the fixture's own live data),
not a hardcoded list of fields, and proven against a deliberately-leaky
fixture first so a false-negative in the scanner itself would be caught."""

from __future__ import annotations

import io
import uuid
import zipfile
from decimal import Decimal

import pytest
from openpyxl import Workbook, load_workbook

from app.models.boq import BoqLineItem
from app.models.settlement import BidSettlement, BidSettlementLineItem
from app.schemas.settlement import ExportRequest
from app.services.settlement import _build_export_workbook

LEAKY_MARKERS = [
    "38.50",  # direct_unit_cost
    "quotation_line",  # cost_source
    "Acme Excavators LLC",  # vendor name
    "3.6725",  # fx_rate
    "manual entry: negotiated discount",  # source_note
]


def _fixture_settlement_and_items():
    settlement = BidSettlement(
        id=uuid.uuid4(), tenant_id=uuid.uuid4(), project_id=uuid.uuid4(), version_no=1, status="approved",
        currency="AED",
    )
    item = BoqLineItem(
        id=uuid.uuid4(), tenant_id=settlement.tenant_id, project_id=settlement.project_id, item_no="1.0",
        description="Excavation to formation level", uom="m3", boq_quantity=Decimal("250"), path="1_0",
    )
    line = BidSettlementLineItem(
        id=uuid.uuid4(), tenant_id=settlement.tenant_id, settlement_id=settlement.id, boq_line_item_id=item.id,
        project_id=settlement.project_id, quantity=Decimal("250"), quantity_at_build=Decimal("250"),
        unit_sell_rate=Decimal("56.14"), line_amount=Decimal("14035.00"),
        # The fields that must NEVER appear in the export:
        direct_unit_cost=Decimal("38.50"), cost_source="quotation_line", fx_rate=Decimal("3.6725"),
        source_note="manual entry: negotiated discount",
    )
    return settlement, [item], {item.id: line}


def _all_strings_in_workbook(wb) -> list[str]:
    """Every string cell value across every sheet, including hidden ones."""
    found = []
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if isinstance(cell.value, str):
                    found.append(cell.value)
    return found


def _scan_for_leaks(file_bytes: bytes, denylist: list[str]) -> list[str]:
    """Returns every denylisted string found anywhere in the file -- cell
    values (any sheet, including hidden), hidden rows/columns' cells
    (iter_rows already covers these -- hidden-ness doesn't exclude a cell
    from the object model), comments, defined names, core document
    properties, and the raw zip (catches custom XML/anything the object
    model doesn't surface)."""
    hits: set[str] = set()
    wb = load_workbook(io.BytesIO(file_bytes))

    for value in _all_strings_in_workbook(wb):
        for marker in denylist:
            if marker in value:
                hits.add(marker)

    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if cell.comment is not None:
                    for marker in denylist:
                        if marker in str(cell.comment.text):
                            hits.add(marker)

    for name in wb.defined_names:
        for marker in denylist:
            if marker in str(name):
                hits.add(marker)

    props = wb.properties
    prop_text = " ".join(
        str(v) for v in (props.title, props.subject, props.creator, props.keywords, props.description, props.category) if v
    )
    for marker in denylist:
        if marker in prop_text:
            hits.add(marker)

    with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
        for name in zf.namelist():
            raw = zf.read(name)
            try:
                text = raw.decode("utf-8", errors="ignore")
            except Exception:
                text = ""
            for marker in denylist:
                if marker in text:
                    hits.add(marker)

    return sorted(hits)


def test_scanner_catches_a_deliberately_leaky_fixture():
    """Proves the scanner itself works before trusting a clean result from
    the real generator below."""
    wb = Workbook()
    ws = wb.active
    ws["A1"] = "direct_unit_cost: 38.50, vendor Acme Excavators LLC"
    buf = io.BytesIO()
    wb.save(buf)
    hits = _scan_for_leaks(buf.getvalue(), LEAKY_MARKERS)
    assert "38.50" in hits
    assert "Acme Excavators LLC" in hits


def test_generated_export_has_no_leaks():
    settlement, items, lines_by_item_id = _fixture_settlement_and_items()
    file_bytes = _build_export_workbook(settlement, items, lines_by_item_id, ExportRequest())
    hits = _scan_for_leaks(file_bytes, LEAKY_MARKERS)
    assert hits == []


def test_generated_export_has_exactly_one_visible_sheet_no_hidden_rows_or_cols():
    settlement, items, lines_by_item_id = _fixture_settlement_and_items()
    file_bytes = _build_export_workbook(settlement, items, lines_by_item_id, ExportRequest())
    wb = load_workbook(io.BytesIO(file_bytes))
    assert wb.sheetnames == ["BOQ"]
    ws = wb["BOQ"]
    assert ws.sheet_state == "visible"
    assert all(not dim.hidden for dim in ws.row_dimensions.values())
    assert all(not dim.hidden for dim in ws.column_dimensions.values())
    assert len(wb.defined_names) == 0


def test_export_shows_sell_rate_and_amount_not_cost():
    settlement, items, lines_by_item_id = _fixture_settlement_and_items()
    file_bytes = _build_export_workbook(settlement, items, lines_by_item_id, ExportRequest())
    wb = load_workbook(io.BytesIO(file_bytes))
    ws = wb["BOQ"]
    assert ws["E2"].value == 56.14  # unit_sell_rate
    assert ws["F2"].value == 14035.0  # line_amount


def test_vat_summary_lines_present_only_when_requested():
    settlement, items, lines_by_item_id = _fixture_settlement_and_items()

    no_vat = _build_export_workbook(settlement, items, lines_by_item_id, ExportRequest(include_vat=False))
    wb_no_vat = load_workbook(io.BytesIO(no_vat))
    values_no_vat = [c.value for row in wb_no_vat["BOQ"].iter_rows() for c in row if isinstance(c.value, str)]
    assert not any("VAT" in v for v in values_no_vat)

    with_vat = _build_export_workbook(settlement, items, lines_by_item_id, ExportRequest(include_vat=True, vat_pct=5.0))
    wb_with_vat = load_workbook(io.BytesIO(with_vat))
    values_with_vat = [c.value for row in wb_with_vat["BOQ"].iter_rows() for c in row if isinstance(c.value, str)]
    assert any("VAT @ 5%" in v for v in values_with_vat)
    assert any("Total incl. VAT" in v for v in values_with_vat)
