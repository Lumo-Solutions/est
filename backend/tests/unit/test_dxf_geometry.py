from __future__ import annotations

import math
import tempfile
from pathlib import Path

import ezdxf
import pytest

from app.takeoff.dxf import index_dxf, index_dxf_geometry


def _build_dxf_bytes() -> bytes:
    doc = ezdxf.new(setup=True)
    doc.header["$INSUNITS"] = 6  # metres
    msp = doc.modelspace()

    msp.add_line((0.0, 0.0), (3.0, 0.0), dxfattribs={"layer": "C-ROAD-CL"})
    pl = msp.add_lwpolyline([(0.0, 0.0), (10.0, 0.0), (10.0, 5.0)], dxfattribs={"layer": "ROAD-L"})
    pl.closed = True
    # A curved centreline: (0,0)->(10,0) semicircle (bulge=1.0), then
    # (10,0)->(20,0) straight.
    msp.add_lwpolyline(
        [(0.0, 0.0, 0.0, 0.0, 1.0), (10.0, 0.0, 0.0, 0.0, 0.0), (20.0, 0.0, 0.0, 0.0, 0.0)],
        format="xyseb",
        dxfattribs={"layer": "ALIGNMENT-CURVED"},
    )
    msp.add_arc(center=(0.0, 0.0), radius=10.0, start_angle=0.0, end_angle=90.0, dxfattribs={"layer": "CURVE"})

    doc.blocks.new(name="MH-STD")
    insert = msp.add_blockref("MH-STD", (5.0, 5.0), dxfattribs={"layer": "UTIL-STRUCT"})
    insert.add_attrib("DIAMETER", "1200", (5.0, 5.0))

    # saveas() (a real file) rather than doc.write(io.StringIO()) (an
    # in-memory buffer) -- the CRLF path is what production actually
    # ingests (a real DXF file, wherever authored, is CRLF-terminated per
    # the DXF spec) and is exactly what exposed the newline bug
    # _read_dxf_document() now guards against (see its docstring in
    # app/takeoff/dxf.py). A buffer-only fixture would never have caught
    # it. saveas() itself only reliably produces CRLF bytes on Windows,
    # though (it opens the file in default text mode, so a POSIX host's
    # own newline convention -- LF -- comes through instead, silently
    # de-fanging this fixture on Linux, e.g. in CI or the real backend
    # container). Force CRLF explicitly so the fixture exercises the same
    # bytes on every platform, matching a real uploaded file regardless of
    # what OS runs the test.
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "fixture.dxf"
        doc.saveas(path)
        data = path.read_bytes()
        if b"\r\n" not in data:
            data = data.replace(b"\n", b"\r\n")
        return data


def test_fixture_is_crlf_terminated_like_a_real_dxf_file() -> None:
    # Guards the regression test below against silently reverting to an
    # LF-only fixture (e.g. via io.StringIO()) that would stop exercising
    # the CRLF bug entirely while still appearing to pass.
    assert b"\r\n" in _build_dxf_bytes()


def test_index_dxf_survives_crlf_line_endings() -> None:
    # Same CRLF regression as test_index_dxf_geometry_survives_crlf_line_
    # endings below, for index_dxf() (the text-entity harvester) -- both
    # share _read_dxf_document(), but this is a genuinely separate public
    # function and had no test coverage of its own before this.
    layouts = index_dxf(_build_dxf_bytes())
    model = next(layout for layout in layouts if layout.layout_name == "Model")
    assert model.units == "m"
    # The MH-STD INSERT's DIAMETER attrib is the only text-bearing entity
    # in the fixture -- a broken (CRLF-corrupted) parse yields 0 entities
    # entirely, this yields exactly 1.
    assert len(model.text_entities) == 1
    assert model.text_entities[0].text_value == "1200"


def test_index_dxf_geometry_survives_crlf_line_endings() -> None:
    # A real DXF file's raw bytes decode to CRLF ("\r\n") line endings.
    # ezdxf.read() expects readline() to return lines with the terminator
    # already stripped, the way a real text-mode file does; wrapping an
    # already-decoded string in io.StringIO does NOT do that (StringIO only
    # special-cases "\n"), which leaves a trailing "\r" on every line and
    # silently produces a near-empty document instead of raising -- this
    # DXF has 11 entities in modelspace; a broken reader parses 0.
    geoms = index_dxf_geometry(_build_dxf_bytes())["Model"]
    assert len(geoms) > 0


def test_index_dxf_geometry_harvests_all_supported_types() -> None:
    geoms = index_dxf_geometry(_build_dxf_bytes())["Model"]
    by_type = {}
    for g in geoms:
        by_type.setdefault(g.entity_type, []).append(g)

    assert len(by_type["line"]) == 1
    line = by_type["line"][0]
    assert line.layer == "C-ROAD-CL"
    assert line.vertices == [(0.0, 0.0), (3.0, 0.0)]

    assert len(by_type["lwpolyline"]) == 2
    poly = next(g for g in by_type["lwpolyline"] if g.layer == "ROAD-L")
    assert poly.vertices == [(0.0, 0.0), (10.0, 0.0), (10.0, 5.0)]
    assert poly.closed is True

    assert len(by_type["arc"]) == 1
    arc = by_type["arc"][0]
    assert arc.center == pytest.approx((0.0, 0.0))
    assert arc.radius == pytest.approx(10.0)
    assert arc.start_angle_deg == pytest.approx(0.0)
    assert arc.end_angle_deg == pytest.approx(90.0)

    assert len(by_type["insert_node"]) == 1
    node = by_type["insert_node"][0]
    assert node.layer == "UTIL-STRUCT"
    assert node.block_name == "MH-STD"
    assert node.vertices == [(5.0, 5.0)]
    assert node.attributes == {"DIAMETER": "1200"}

    # Curved LWPOLYLINE: bulge=1.0 on the first vertex harvested correctly.
    curved = next(g for g in by_type["lwpolyline"] if g.layer == "ALIGNMENT-CURVED")
    assert curved.vertices == pytest.approx([(0.0, 0.0), (10.0, 0.0), (20.0, 0.0)])
    assert curved.bulges == pytest.approx([1.0, 0.0, 0.0])


def test_index_dxf_geometry_feeds_alignment_extractor_end_to_end() -> None:
    # Sanity check that harvested geometry plugs straight into an extractor
    # without any adapter code: the LINE on layer C-ROAD-CL is 3.0 m long
    # (matches the ezdxf fixture above), so AlignmentExtractor should report
    # exactly that.
    from types import SimpleNamespace

    from app.takeoff.geometry.alignment import AlignmentExtractor

    geoms = index_dxf_geometry(_build_dxf_bytes())["Model"]
    measurements = AlignmentExtractor().extract(SimpleNamespace(units="m"), geoms)
    by_layer = {m.metadata["layer"]: m.value for m in measurements}
    assert by_layer["C-ROAD-CL"] == pytest.approx(3.0)
    # ALIGNMENT-CURVED: 5*pi (semicircle) + 10.0 (straight run) -- see
    # test_alignment_extractor.py::test_alignment_length_with_curved_segment_bulge
    # for the same fixture's fully worked math.
    assert by_layer["ALIGNMENT-CURVED"] == pytest.approx(5.0 * math.pi + 10.0)


def test_index_dxf_geometry_harvests_dimension_with_explicit_text() -> None:
    """Module B Phase 4a scale cross-check (app.takeoff.scale::
    dimension_cross_check_signals) -- only a DIMENSION with an explicit
    (non-auto) text override becomes a "dimension" GeometricEntity; the
    default auto ("<>") text is intentionally skipped (see scale.py's
    module docstring)."""
    doc = ezdxf.new(setup=True)
    msp = doc.modelspace()
    dim = msp.add_linear_dim(base=(0.0, 5.0), p1=(0.0, 0.0), p2=(10.0, 0.0), dimstyle="EZDXF", text="5.000")
    dim.render()
    auto_dim = msp.add_linear_dim(base=(0.0, 15.0), p1=(0.0, 10.0), p2=(10.0, 10.0), dimstyle="EZDXF")
    auto_dim.render()

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "fixture.dxf"
        doc.saveas(path)
        data = path.read_bytes()

    geoms = index_dxf_geometry(data)["Model"]
    dimensions = [g for g in geoms if g.entity_type == "dimension"]
    assert len(dimensions) == 1  # the auto-text one is skipped
    assert dimensions[0].attributes["stated_length"] == "5.000"
    assert dimensions[0].vertices == [(0.0, 0.0), (10.0, 0.0)]


def test_index_dxf_geometry_computes_insert_signature_from_block_content() -> None:
    """Module B Phase 4c: the signature comes from the block DEFINITION's
    own local (untransformed) geometry -- not the insertion point, and not
    any one instance's placed/rotated content -- so two placements of the
    same 10x5 rectangle block at different positions/rotations get
    IDENTICAL signatures, and a different-shaped block does not. See
    app.takeoff.typology::group_dxf_instances_by_block, the consumer."""
    doc = ezdxf.new(setup=True)
    msp = doc.modelspace()

    villa_a = doc.blocks.new(name="VILLA_A")
    villa_a.add_lwpolyline([(0.0, 0.0), (10.0, 0.0), (10.0, 5.0), (0.0, 5.0)], close=True)  # perimeter 30, aspect 2.0

    villa_b = doc.blocks.new(name="VILLA_B")
    villa_b.add_lwpolyline([(0.0, 0.0), (20.0, 0.0), (20.0, 5.0), (0.0, 5.0)], close=True)  # perimeter 50, aspect 4.0

    msp.add_blockref("VILLA_A", (0.0, 0.0))
    msp.add_blockref("VILLA_A", (100.0, 0.0), dxfattribs={"rotation": 90.0})  # same block, rotated placement
    msp.add_blockref("VILLA_B", (200.0, 0.0))

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "fixture.dxf"
        doc.saveas(path)
        data = path.read_bytes()

    geoms = index_dxf_geometry(data)["Model"]
    inserts = {g.vertices[0]: g for g in geoms if g.entity_type == "insert_node"}
    a1 = inserts[(0.0, 0.0)]
    a2 = inserts[(100.0, 0.0)]
    b1 = inserts[(200.0, 0.0)]

    for node in (a1, a2, b1):
        assert node.attributes["__sig_entity_count"] == "1"

    assert float(a1.attributes["__sig_bbox_aspect_ratio"]) == pytest.approx(2.0)
    assert float(a1.attributes["__sig_total_edge_length"]) == pytest.approx(30.0)
    # Rotated placement: the signature comes from the block DEFINITION's
    # own local (untransformed) geometry, not this instance's own
    # placement -- so a rotated placement's signature is IDENTICAL to an
    # unrotated one of the same block, not just similar. A signature
    # computed from this instance's own rotated/world-transformed content
    # instead would have given a 5x10 (aspect 0.5) bbox here, wrongly
    # splitting these two into separate typology groups below.
    assert a2.attributes == a1.attributes
    assert float(b1.attributes["__sig_bbox_aspect_ratio"]) == pytest.approx(4.0)
    assert float(b1.attributes["__sig_total_edge_length"]) == pytest.approx(50.0)

    from app.takeoff.typology import group_dxf_instances_by_block

    groups = group_dxf_instances_by_block([a1, a2, b1], tolerance_pct=2.0)
    assert len(groups) == 1  # VILLA_B has only one placement -- not a repeating typology yet
    assert groups[0].key == "VILLA_A"
    assert {e.handle for e in groups[0].entities} == {a1.handle, a2.handle}
