"""Source DXFs for the DWG conversion tests, and a measurement summary used to
compare a DXF with the DXF that came back from DXF -> DWG -> DXF.

`build_dwg_fixtures.py` turns each source into a DWG with the real ODA
converter (make dwg-fixtures); the tests then check that what the pipeline
extracts from the round-tripped DXF matches what it extracts from the
original, within tolerance. Handles/GUIDs/timestamps legitimately change on a
round trip, so nothing here compares them.
"""

from __future__ import annotations

import os
import tempfile
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import ezdxf

from app.intake.sample_pack import _dxf as _intake_dxf
from app.takeoff.dxf import index_dxf, index_dxf_geometry
from app.takeoff.geometry import stubs as _stubs  # noqa: F401 -- registers the extractors
from app.takeoff.geometry.base import get_registry

FIXTURE_DIR = Path(__file__).parent / "dwg"


def _save(doc) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "src.dxf")
        doc.saveas(path)
        data = Path(path).read_bytes()
    return data if b"\r\n" in data else data.replace(b"\n", b"\r\n")


def takeoff_basic() -> bytes:
    """The geometry fixture tests/unit/test_dxf_geometry.py already uses:
    a line, a closed polyline, a curved (bulge) polyline, an arc, and a block
    insert with an attribute."""
    doc = ezdxf.new(setup=True)
    doc.header["$INSUNITS"] = 6  # metres
    msp = doc.modelspace()
    msp.add_line((0.0, 0.0), (3.0, 0.0), dxfattribs={"layer": "C-ROAD-CL"})
    pl = msp.add_lwpolyline([(0.0, 0.0), (10.0, 0.0), (10.0, 5.0)], dxfattribs={"layer": "ROAD-L"})
    pl.closed = True
    msp.add_lwpolyline(
        [(0.0, 0.0, 0.0, 0.0, 1.0), (10.0, 0.0, 0.0, 0.0, 0.0), (20.0, 0.0, 0.0, 0.0, 0.0)],
        format="xyseb",
        dxfattribs={"layer": "ALIGNMENT-CURVED"},
    )
    msp.add_arc(center=(0.0, 0.0), radius=10.0, start_angle=0.0, end_angle=90.0, dxfattribs={"layer": "CURVE"})
    doc.blocks.new(name="MH-STD")
    insert = msp.add_blockref("MH-STD", (5.0, 5.0), dxfattribs={"layer": "UTIL-STRUCT"})
    insert.add_attrib("DIAMETER", "1200", (5.0, 5.0))
    return _save(doc)


def civil_site() -> bytes:
    """A small civil sheet that exercises every registered extractor: a
    stitched road centreline (with a curve), a left/right boundary pair
    (corridor area), a sewer run between two manholes (pipe network) and
    trench cross-section markers (prismoidal volume). Metres, plus a text
    title block."""
    doc = ezdxf.new(setup=True)
    doc.header["$INSUNITS"] = 6
    for name in ("C-ROAD-CL", "ROAD-L", "ROAD-R", "SEWER-PIPE", "UTIL-STRUCT", "TRENCH-XSEC", "TITLE"):
        if name not in doc.layers:
            doc.layers.add(name)
    msp = doc.modelspace()
    # Road centreline: two lines and a bulged polyline that join end to end.
    msp.add_line((0.0, 0.0), (40.0, 0.0), dxfattribs={"layer": "C-ROAD-CL"})
    msp.add_lwpolyline(
        [(40.0, 0.0, 0.0, 0.0, 0.5), (60.0, 0.0, 0.0, 0.0, 0.0), (60.0, 30.0, 0.0, 0.0, 0.0)],
        format="xyseb", dxfattribs={"layer": "C-ROAD-CL"},
    )
    # Corridor: parallel left/right boundaries 8 m apart, 100 m long.
    msp.add_lwpolyline([(0.0, 4.0), (100.0, 4.0)], dxfattribs={"layer": "ROAD-L"})
    msp.add_lwpolyline([(0.0, -4.0), (100.0, -4.0)], dxfattribs={"layer": "ROAD-R"})
    # Sewer: two manholes 25 m apart, a bent 25 + 15 m run between them.
    doc.blocks.new(name="MH-STD")
    for x, y in ((0.0, 20.0), (25.0, 35.0)):
        msp.add_blockref("MH-STD", (x, y), dxfattribs={"layer": "UTIL-STRUCT"})
    msp.add_lwpolyline([(0.0, 20.0), (25.0, 20.0), (25.0, 35.0)], dxfattribs={"layer": "SEWER-PIPE"})
    # Trench cross-sections: station / top width / bottom width / depth.
    doc.blocks.new(name="XSEC")
    for station, top, bottom, depth in ((0, 2.0, 1.0, 1.5), (10, 2.2, 1.2, 1.8), (20, 2.4, 1.4, 2.1)):
        ref = msp.add_blockref("XSEC", (float(station), -10.0), dxfattribs={"layer": "TRENCH-XSEC"})
        for tag, val in (("STATION", station), ("WIDTH_TOP", top), ("WIDTH_BOTTOM", bottom), ("DEPTH", depth)):
            ref.add_attrib(tag, str(val), (float(station), -10.0))
    for i, line in enumerate(("DRAWING NO: C-201", "REV: B", "SCALE 1:500", "TITLE: SITE SERVICES")):
        msp.add_text(line, dxfattribs={"insert": (120.0, -10.0 - i * 4), "height": 2.5, "layer": "TITLE"})
    return _save(doc)


def intake_sheet() -> bytes:
    """The DXF the tender-intake sample pack already uses (title block text +
    a fan of lines)."""
    return _intake_dxf("C-101", "A", "SITE PLAN", "civil", "C-ROAD-CL")


SOURCES: dict[str, Callable[[], bytes]] = {
    "takeoff_basic": takeoff_basic,
    "civil_site": civil_site,
    "intake_sheet": intake_sheet,
}


def _sheet_for(layout) -> SimpleNamespace:
    # What index_sheets persists for a DXF layout (units from $INSUNITS; no
    # title-block scale, so the extractors work in native units -> metres).
    return SimpleNamespace(units=layout.units, scale_ratio=None)


def summarize(dxf: bytes) -> dict:
    """Everything the pipeline would extract from a DXF, reduced to values
    that must survive a DWG round trip: entity counts per (type, layer), text
    per layout, total polyline length, and every geometry-extractor
    measurement (capability, kind, value, layer)."""
    layouts = {layout.layout_name: layout for layout in index_dxf(dxf)}
    geometry = index_dxf_geometry(dxf)
    out: dict[str, dict] = {}
    for name, entities in geometry.items():
        layout = layouts.get(name)
        measurements = []
        for extractor in get_registry().values():
            sheet = _sheet_for(layout) if layout else SimpleNamespace(units=None, scale_ratio=None)
            if not extractor.supports(sheet):
                continue
            for m in extractor.extract(sheet, entities):
                measurements.append((extractor.capability, m.kind, float(m.value), (m.metadata or {}).get("layer")))
        out[name] = {
            "units": layout.units if layout else None,
            "entity_counts": Counter((e.entity_type, e.layer) for e in entities),
            "text": sorted(t.text_value for t in (layout.text_entities if layout else []) if t.text_value),
            "vertex_total": sum(len(e.vertices) for e in entities),
            "measurements": sorted(measurements, key=lambda t: (t[0], t[1], t[3] or "", t[2])),
        }
    return out
