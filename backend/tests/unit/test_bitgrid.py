"""The optical code that lets the mock AI provider 'read' the synthetic scanned BOQ page, checked through a
real PDF render (the same path production uses), so it cannot silently rot."""

from __future__ import annotations

from app.demo import bitgrid
from app.demo.boq_pdf import BoqItem, build_scanned_pdf, sample_items
from app.takeoff.pdf import render_page_png


def test_roundtrip_in_memory():
    payload = {"rows": [{"item_no": "1.1", "description": "Excavate soil", "unit": "m3", "quantity": 120.5}]}
    img = bitgrid.encode(payload, 1240)
    assert bitgrid.decode(img) == payload


def test_survives_a_real_pdf_render():
    items = sample_items()[:9] + [BoqItem("9", "Unicode dash \u2013 and quotes \"x\"", "nr", 3.0)]
    png = render_page_png(build_scanned_pdf(items), 0)
    got = bitgrid.decode(png)
    assert got is not None and [r["item_no"] for r in got["rows"]] == [i.item_no for i in items]
    assert got["rows"][0]["description"] == items[0].description and got["rows"][1]["quantity"] == 1250.0


def test_an_unmarked_page_decodes_to_none():
    from PIL import Image

    assert bitgrid.decode(Image.new("L", (1240, 300), 255)) is None
    assert bitgrid.decode(render_page_png(build_scanned_pdf(sample_items()[:3], embed_answer=False), 0)) is None
