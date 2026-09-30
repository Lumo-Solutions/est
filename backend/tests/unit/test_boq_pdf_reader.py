"""Deterministic PDF BOQ reader against generated bills (no model, no DB)."""

from __future__ import annotations

from app.boq.pdf_reader import read_pdf_boq
from app.demo.boq_pdf import BoqItem, build_boq_pdf, build_scanned_pdf, sample_items


def _rows(pages):
    return [r for p in pages for r in p.rows]


def test_reads_every_item_across_pages_with_wrapped_descriptions():
    items = sample_items()
    pages = read_pdf_boq(build_boq_pdf(items))
    rows = _rows(pages)
    by_no = {r.item_no: r for r in rows}
    assert set(by_no) == {i.item_no for i in items}
    r = by_no["1.1"]
    assert r.uom == "m3" and r.quantity == 1250.0
    assert r.description.startswith("Excavate in all types of soil") and r.description.endswith("approved tip")
    assert by_no["1"].uom is None and by_no["1"].description == "EARTHWORKS"  # heading, no qty
    assert by_no["2.46"].uom == "nr" and by_no["2.46"].quantity == 12.0
    assert len({r.page for r in rows}) >= 3  # really multi-page
    assert all(p.status in ("table", "skipped_collection") for p in pages)


def test_forward_lines_and_collection_page_are_not_rows():
    pages = read_pdf_boq(build_boq_pdf(sample_items()))
    text = " ".join(r.description.lower() for r in _rows(pages))
    assert "brought forward" not in text and "carried forward" not in text and "carried to summary" not in text
    assert pages[-1].status == "skipped_collection"


def test_header_only_on_first_page_still_reads_later_pages():
    pages = read_pdf_boq(build_boq_pdf(sample_items(), repeat_header=False))
    assert sum(len(p.rows) for p in pages) == len(sample_items())


def test_rows_carry_page_and_bbox_provenance():
    rows = _rows(read_pdf_boq(build_boq_pdf(sample_items())))
    r = next(r for r in rows if r.item_no == "2.10")
    x0, top, x1, bottom = r.bbox
    assert 0 <= x0 < x1 <= r.page_size[0] and 0 <= top < bottom <= r.page_size[1]
    assert r.source == "table" and r.page >= 1


def test_scanned_page_is_flagged_for_ai_not_guessed():
    pages = read_pdf_boq(build_scanned_pdf(sample_items()[:5]))
    assert [p.status for p in pages] == ["needs_ai"] and not pages[0].rows


def test_unparseable_text_page_is_flagged_for_ai():
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    import io

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, invariant=1)
    c.drawString(60, 700, "Some narrative text with no table at all.")
    c.showPage()
    c.save()
    assert read_pdf_boq(buf.getvalue())[0].status == "needs_ai"


def test_quantities_with_thousands_separators():
    pages = read_pdf_boq(build_boq_pdf([BoqItem("1.1", "Big earthwork item", "m3", 12345.5, 2.0)], collection=False))
    assert _rows(pages)[0].quantity == 12345.5
