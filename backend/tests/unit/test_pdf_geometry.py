"""Module B Phase 4a: vector PDF geometry extraction. Synthetic PDFs built
with reportlab (already a dependency -- see app/cli.py::simulate_quotes),
mirroring test_dxf_geometry.py's "build a real file, read it back through
the production parser" convention rather than mocking pdfplumber."""

from __future__ import annotations

import io

from reportlab.lib.colors import red
from reportlab.pdfgen import canvas

from app.takeoff.pdf import PdfLayerRule, index_pdf_geometry


def _pdf_with_shapes() -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(400, 400))

    # Enough real text on the page to clear the raster threshold.
    c.drawString(20, 380, "Sheet 1 of 1 - a synthetic drawing with real vector content on it")

    c.setStrokeColor(red)
    c.setLineWidth(2)
    c.setDash([4, 2])
    c.line(10, 10, 100, 10)  # red, dashed, width 2

    c.setStrokeColorRGB(0, 0, 0)
    c.setLineWidth(0.5)
    c.setDash([])
    c.line(10, 200, 10, 300)  # black, solid, thin

    c.setStrokeColor(red)
    c.setDash([4, 2])
    c.rect(50, 50, 40, 30, stroke=1, fill=0)  # red, dashed
    c.save()
    return buf.getvalue()


def _raster_pdf() -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(200, 200))
    c.line(0, 0, 200, 200)  # geometry present, but no real text at all
    c.save()
    return buf.getvalue()


def test_extracts_lines_and_rect_with_no_mapping_rules():
    data = _pdf_with_shapes()
    result = index_pdf_geometry(data)
    assert list(result.keys()) == ["page-1"]
    entities = result["page-1"]
    kinds = [e.entity_type for e in entities]
    assert "line" in kinds
    assert "lwpolyline" in kinds  # the rect
    assert all(e.layer == "UNMAPPED" for e in entities)  # no rules configured


def test_maps_layer_by_stroke_colour_and_line_width():
    data = _pdf_with_shapes()
    rules = [
        PdfLayerRule(target_layer="RED-DASHED", stroke_color="#ff0000", dash_pattern="dashed", priority=1),
        PdfLayerRule(target_layer="THIN-BLACK", stroke_color="#000000", max_line_width=1.0, priority=2),
    ]
    result = index_pdf_geometry(data, rules)
    entities = result["page-1"]
    lines = [e for e in entities if e.entity_type == "line"]
    assert {e.layer for e in lines} == {"RED-DASHED", "THIN-BLACK"}


def test_raster_page_is_skipped_not_guessed():
    data = _raster_pdf()
    result = index_pdf_geometry(data)
    assert result["page-1"] == []


def test_rect_is_a_closed_four_vertex_polyline():
    data = _pdf_with_shapes()
    entities = index_pdf_geometry(data)["page-1"]
    rects = [e for e in entities if e.entity_type == "lwpolyline"]
    assert len(rects) == 1
    assert rects[0].closed is True
    assert len(rects[0].vertices) == 4
