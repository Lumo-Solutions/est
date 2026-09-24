from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from app.takeoff.geometry.alignment import AlignmentExtractor, CorridorAreaExtractor
from app.takeoff.geometry.entities import GeometricEntity


def _sheet(units: str = "m") -> SimpleNamespace:
    return SimpleNamespace(units=units)


def _line(handle: str, layer: str, start: tuple[float, float], end: tuple[float, float]) -> GeometricEntity:
    return GeometricEntity("line", layer, handle, [start, end])


def _polyline(
    handle: str, layer: str, vertices: list[tuple[float, float]], bulges: list[float] | None = None
) -> GeometricEntity:
    return GeometricEntity("lwpolyline", layer, handle, vertices, bulges=bulges or [])


# ---------------------------------------------------------------------------
# AlignmentExtractor
# ---------------------------------------------------------------------------


def test_alignment_length_single_polyline_3_4_5_triangle() -> None:
    # Vertices (0,0)->(3,0)->(3,4): legs of length 3 and 4 -> total 7.0 m
    # (drawing units = "m", so a 1:1 conversion factor -- no scaling).
    entity = _polyline("P1", "C-ROAD-CL", [(0.0, 0.0), (3.0, 0.0), (3.0, 4.0)])
    measurements = AlignmentExtractor().extract(_sheet("m"), [entity])
    assert len(measurements) == 1
    m = measurements[0]
    assert m.kind == "alignment_length_m"
    assert m.value == pytest.approx(7.0)
    assert m.unit == "m"
    assert m.confidence == 1.0
    assert m.metadata["station_intervals_m"] == pytest.approx([0.0, 3.0, 7.0])


def test_alignment_length_stitches_two_lines_on_same_layer() -> None:
    # Same 3-4-5 legs, but drawn as two separate LINE entities on the
    # alignment layer that must be stitched end-to-end: 3 + 4 = 7.0 m.
    a = _line("A", "ALIGNMENT-1", (0.0, 0.0), (3.0, 0.0))
    b = _line("B", "ALIGNMENT-1", (3.0, 0.0), (3.0, 4.0))
    measurements = AlignmentExtractor().extract(_sheet("m"), [a, b])
    assert len(measurements) == 1
    assert measurements[0].value == pytest.approx(7.0)
    assert set(measurements[0].source_entity_ids) == {"A", "B"}


def test_alignment_length_converts_millimeters_to_meters() -> None:
    # Same geometry as the 3-4-5 case but drawn in millimetres (a drawing
    # modeled at full mm precision): 3000mm + 4000mm = 7000mm native ->
    # 7000 * 0.001 = 7.0 m.
    entity = _polyline("P1", "C-ROAD-CL", [(0.0, 0.0), (3000.0, 0.0), (3000.0, 4000.0)])
    measurements = AlignmentExtractor().extract(_sheet("mm"), [entity])
    assert measurements[0].value == pytest.approx(7.0)
    assert measurements[0].unit == "m"


def test_alignment_ignores_non_matching_layers() -> None:
    entity = _polyline("P1", "A-DOOR-FRAME", [(0.0, 0.0), (3.0, 0.0)])
    measurements = AlignmentExtractor().extract(_sheet("m"), [entity])
    assert measurements == []


def test_alignment_does_not_stitch_across_different_layers() -> None:
    # Two entities whose endpoints coincide, but on two different alignment
    # layers (e.g. a road centreline crossing a sewer centreline) -- must
    # stay two separate chains of length 3.0 m each, not merge into one.
    a = _line("A", "C-ROAD-CL", (0.0, 0.0), (3.0, 0.0))
    b = _line("B", "C-SEWER-CL", (3.0, 0.0), (3.0, 4.0))
    measurements = AlignmentExtractor().extract(_sheet("m"), [a, b])
    assert len(measurements) == 2
    assert {round(m.value, 3) for m in measurements} == {3.0, 4.0}


def test_alignment_unitless_drawing_has_low_confidence() -> None:
    entity = _polyline("P1", "C-ROAD-CL", [(0.0, 0.0), (3.0, 0.0)])
    measurements = AlignmentExtractor().extract(_sheet("unitless"), [entity])
    assert measurements[0].unit == "unitless"
    assert measurements[0].confidence == 0.3
    assert measurements[0].value == pytest.approx(3.0)  # raw native magnitude, unconverted


def test_alignment_length_with_curved_segment_bulge() -> None:
    # A road centreline with a straight run then a curved fillet:
    #   (0,0) -> (10,0): straight, 10.0 m
    #   (10,0) -> (20,0): bulge=1.0 -> a semicircular arc, radius 5
    #     (chord=10, r = chord/(2*sin(pi/2)) = 10/2 = 5),
    #     arc length = r*pi = 5*pi = 15.70796...
    # Total length = 10.0 + 5*pi = 25.70796...
    entity = _polyline("P1", "C-ROAD-CL", [(0.0, 0.0), (10.0, 0.0), (20.0, 0.0)], bulges=[0.0, 1.0])
    measurements = AlignmentExtractor().extract(_sheet("m"), [entity])
    assert len(measurements) == 1
    m = measurements[0]
    assert m.value == pytest.approx(10.0 + 5.0 * math.pi)
    assert m.value == pytest.approx(25.707963, abs=1e-5)
    # Stationing must reflect the arc length at the curved segment, not the
    # 10.0 m straight-line chord distance between (10,0) and (20,0).
    assert m.metadata["station_intervals_m"] == pytest.approx([0.0, 10.0, 10.0 + 5.0 * math.pi])


def test_alignment_length_pure_semicircle_polyline() -> None:
    # A single semicircular curve, no straight segments: (0,0) -> (10,0)
    # with bulge=1.0 -> radius 5, length = 5*pi = 15.70796...
    entity = _polyline("P1", "ALIGNMENT-CURVE", [(0.0, 0.0), (10.0, 0.0)], bulges=[1.0])
    measurements = AlignmentExtractor().extract(_sheet("m"), [entity])
    assert measurements[0].value == pytest.approx(5.0 * math.pi)


# ---------------------------------------------------------------------------
# CorridorAreaExtractor
# ---------------------------------------------------------------------------


def test_corridor_area_rectangle_from_paired_left_right_layers() -> None:
    # ROAD-L runs along y=0 from x=0 to x=10; ROAD-R runs along y=3 -- a
    # 10m x 3m strip, area = 30 m^2 (same rectangle as the pure-math test).
    left = _polyline("L1", "ROAD-L", [(0.0, 0.0), (10.0, 0.0)])
    right = _polyline("R1", "ROAD-R", [(0.0, 3.0), (10.0, 3.0)])
    measurements = CorridorAreaExtractor().extract(_sheet("m"), [left, right])
    assert len(measurements) == 1
    m = measurements[0]
    assert m.kind == "corridor_area_m2"
    assert m.value == pytest.approx(30.0)
    assert m.unit == "m2"
    assert m.metadata == {
        "left_layer": "ROAD-L",
        "right_layer": "ROAD-R",
        "left_vertex_count": 2,
        "right_vertex_count": 2,
    }


def test_corridor_area_handles_different_vertex_counts() -> None:
    # Left has 2 vertices, right has 3 -- shoelace (unlike the earlier
    # vertex-by-vertex triangulation this replaced) doesn't need matching
    # counts, only that the two boundaries, joined end to end, trace a
    # simple polygon. Both boundaries are still straight and at constant
    # width 3m over a 10m run -> same 30 m^2 rectangle, now with an extra
    # (collinear, non-area-changing) vertex on the right side.
    left = _polyline("L1", "ROAD-L", [(0.0, 0.0), (10.0, 0.0)])
    right = _polyline("R1", "ROAD-R", [(0.0, 3.0), (5.0, 3.0), (10.0, 3.0)])
    measurements = CorridorAreaExtractor().extract(_sheet("m"), [left, right])
    assert len(measurements) == 1
    assert measurements[0].value == pytest.approx(30.0)
    assert measurements[0].metadata["left_vertex_count"] == 2
    assert measurements[0].metadata["right_vertex_count"] == 3


def test_corridor_area_curved_boundary() -> None:
    # Left boundary: straight (0,0)->(20,0). Right boundary: straight chord
    # (0,5)->(20,5) but replaced by a semicircular arc (bulge=-1.0) that
    # bulges AWAY from the left boundary (outward), like a corridor that
    # widens into a semicircular bulb along one side.
    #   Base (straight-edged) rectangle: 20m x 5m = 100 m^2.
    #   Chord length 20, bulge magnitude 1.0 -> radius = 20/(2*sin(pi/2)) = 10.
    #   Since the chord's endpoints are diametrically opposite (chord ==
    #   2*radius), the "circular segment" added is exactly a full semicircle:
    #   area = 0.5 * r^2 * (theta - sin(theta)) = 0.5*100*(pi - 0) = 50*pi.
    #   Total = 100 + 50*pi = 257.0796...
    # (Confirmed against the running implementation -- see PR discussion:
    # the opposite bulge sign here would curve the arc INTO the corridor,
    # which for a semicircle this large overshoots past the left boundary
    # entirely and produces a self-intersecting polygon; this fixture uses
    # the sign that keeps the boundary simple.)
    left = _polyline("L1", "ROAD-L", [(0.0, 0.0), (20.0, 0.0)])
    right = _polyline("R1", "ROAD-R", [(0.0, 5.0), (20.0, 5.0)], bulges=[-1.0, 0.0])
    measurements = CorridorAreaExtractor().extract(_sheet("m"), [left, right])
    assert len(measurements) == 1
    assert measurements[0].value == pytest.approx(100.0 + 50.0 * math.pi)
    assert measurements[0].value == pytest.approx(257.0796, abs=1e-3)


def test_corridor_area_no_pair_found_returns_empty() -> None:
    left = _polyline("L1", "ROAD-CENTERLINE", [(0.0, 0.0), (10.0, 0.0)])
    assert CorridorAreaExtractor().extract(_sheet("m"), [left]) == []


def test_corridor_area_skips_ambiguous_multiple_chains_per_side() -> None:
    # Two disconnected segments on the "left" layer (not stitchable into
    # one chain) -- ambiguous, must be skipped rather than guessed at.
    left_a = _polyline("LA", "ROAD-L", [(0.0, 0.0), (10.0, 0.0)])
    left_b = _polyline("LB", "ROAD-L", [(100.0, 0.0), (110.0, 0.0)])
    right = _polyline("R1", "ROAD-R", [(0.0, 3.0), (10.0, 3.0)])
    assert CorridorAreaExtractor().extract(_sheet("m"), [left_a, left_b, right]) == []
