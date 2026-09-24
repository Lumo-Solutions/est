from __future__ import annotations

import math

import pytest

from app.takeoff.geometry.entities import GeometricEntity
from app.takeoff.geometry.geometry_math import (
    arc_length,
    bulge_included_angle,
    bulge_radius,
    bulge_segment_area_correction,
    bulge_segment_length,
    composite_trench_volume,
    cumulative_stations,
    polyline_length,
    prismoidal_volume,
    shoelace_area,
    stitch_chains,
    trapezoidal_cross_section_area,
    trench_segment_volume,
)

# ---------------------------------------------------------------------------
# polyline_length / cumulative_stations (straight segments)
# ---------------------------------------------------------------------------


def test_polyline_length_3_4_5_triangle() -> None:
    # Classic 3-4-5 right triangle: (0,0)->(3,0) is 3, (3,0)->(3,4) is 4,
    # hypotenuse would be 5 but we're summing the two legs, not cutting the
    # corner -- total = 3 + 4 = 7.
    length = polyline_length([(0.0, 0.0), (3.0, 0.0), (3.0, 4.0)])
    assert length == pytest.approx(7.0)


def test_polyline_length_closed_adds_return_leg() -> None:
    # Same two legs (3 + 4 = 7) plus the closing hypotenuse back to the
    # start: sqrt(3^2 + 4^2) = 5. Total perimeter = 7 + 5 = 12.
    length = polyline_length([(0.0, 0.0), (3.0, 0.0), (3.0, 4.0)], closed=True)
    assert length == pytest.approx(12.0)


def test_cumulative_stations() -> None:
    # Same 3-4-5 legs: station 0 at the start, 3 after the first leg,
    # 3 + 4 = 7 at the end.
    stations = cumulative_stations([(0.0, 0.0), (3.0, 0.0), (3.0, 4.0)])
    assert stations == pytest.approx([0.0, 3.0, 7.0])


# ---------------------------------------------------------------------------
# bulge (LWPOLYLINE arc-segment) geometry
# ---------------------------------------------------------------------------


def test_bulge_included_angle_of_one_is_a_semicircle() -> None:
    # DXF convention: bulge = tan(theta/4). bulge=1.0 -> theta = 4*atan(1)
    # = 4 * (pi/4) = pi radians = 180 degrees (a semicircle). Cross-checked
    # against ezdxf's own ezdxf.math.bulge_to_arc((0,0),(10,0),1.0), which
    # reports center=(5,0), radius=5.0, sweeping 180 degrees -- exactly
    # this test's numbers.
    theta = bulge_included_angle(1.0)
    assert theta == pytest.approx(math.pi)


def test_bulge_radius_matches_ezdxf_semicircle_example() -> None:
    # Chord (0,0)-(10,0), bulge=1.0 -> theta=pi (see above).
    # r = chord / (2*sin(theta/2)) = 10 / (2*sin(pi/2)) = 10 / 2 = 5.0,
    # matching ezdxf.math.bulge_to_arc's radius=5.0 for the same input.
    r = bulge_radius(chord_length=10.0, included_angle=math.pi)
    assert r == pytest.approx(5.0)


def test_bulge_segment_length_semicircle() -> None:
    # Same semicircle: radius 5, included angle pi -> arc length =
    # r * theta = 5 * pi = 15.70796...
    length = bulge_segment_length((0.0, 0.0), (10.0, 0.0), bulge=1.0)
    assert length == pytest.approx(5.0 * math.pi)
    assert length == pytest.approx(15.707963, abs=1e-5)


def test_bulge_segment_length_zero_bulge_is_straight_line() -> None:
    assert bulge_segment_length((0.0, 0.0), (3.0, 4.0), bulge=0.0) == pytest.approx(5.0)


def test_bulge_segment_area_correction_two_semicircles_make_a_full_circle() -> None:
    # A "circle" drawn as 2 vertices, both with bulge=1.0 (each edge a
    # semicircle of radius 5, chord 10): the area correction for a single
    # semicircle relative to its (zero-length-effectively, since the chord
    # coincides with the polygon's degenerate 2-point "edge") straight
    # chord is the full semicircle-disk area added on: for theta=pi,
    # sin(pi)=0, so correction = 0.5 * r^2 * (theta - sin(theta))
    # = 0.5 * 25 * pi = 12.5*pi. Two of these (one per semicircle) sum to
    # 25*pi -- exactly a full circle of radius 5 (pi*r^2 = 25*pi). Verified
    # end-to-end in test_shoelace_area_two_semicircles_is_a_full_circle.
    correction = bulge_segment_area_correction((0.0, 0.0), (10.0, 0.0), bulge=1.0)
    assert correction == pytest.approx(12.5 * math.pi)


def test_polyline_length_with_bulges_mixes_straight_and_arc_segments() -> None:
    # First segment (0,0)->(10,0) is a semicircle bulge (length 5*pi, see
    # above); second segment (10,0)->(20,0) is straight (length 10).
    # Total = 5*pi + 10 = 25.70796...
    length = polyline_length([(0.0, 0.0), (10.0, 0.0), (20.0, 0.0)], bulges=[1.0, 0.0])
    assert length == pytest.approx(5.0 * math.pi + 10.0)


def test_cumulative_stations_with_bulge() -> None:
    # Same two segments as above: station 0 at the start, 5*pi after the
    # semicircle, 5*pi + 10 at the end.
    stations = cumulative_stations([(0.0, 0.0), (10.0, 0.0), (20.0, 0.0)], bulges=[1.0, 0.0])
    assert stations == pytest.approx([0.0, 5.0 * math.pi, 5.0 * math.pi + 10.0])


# ---------------------------------------------------------------------------
# arc_length (DXF ARC entities -- independent of LWPOLYLINE bulges)
# ---------------------------------------------------------------------------


def test_arc_length_quarter_circle() -> None:
    # Quarter circle, radius 10: arc length = radius * (pi/2) = 10 * 1.5708 = 15.70796...
    length = arc_length(radius=10.0, start_angle_deg=0.0, end_angle_deg=90.0)
    assert length == pytest.approx(10.0 * math.pi / 2.0)
    assert length == pytest.approx(15.707963, abs=1e-5)


def test_arc_length_wraps_across_zero_degrees() -> None:
    # DXF arcs sweep counter-clockwise from start to end; start=350,
    # end=10 sweeps through 0 for a 20-degree span, not -340.
    # length = radius * radians(20) = 5 * 0.349066 = 1.745329...
    length = arc_length(radius=5.0, start_angle_deg=350.0, end_angle_deg=10.0)
    assert length == pytest.approx(5.0 * math.radians(20.0))
    assert length == pytest.approx(1.745329, abs=1e-5)


def test_arc_length_degenerate_equal_angles_is_zero() -> None:
    assert arc_length(radius=10.0, start_angle_deg=45.0, end_angle_deg=45.0) == 0.0


# ---------------------------------------------------------------------------
# stitch_chains
# ---------------------------------------------------------------------------


def _line(handle: str, start: tuple[float, float], end: tuple[float, float], layer: str = "C-ROAD-CL") -> GeometricEntity:
    return GeometricEntity("line", layer, handle, [start, end])


def test_stitch_chains_merges_two_lines_end_to_end() -> None:
    # Line A: (0,0)-(3,0) length 3. Line B: (3,0)-(3,4) length 4.
    # B's start coincides with A's end exactly -> one merged chain,
    # total length 3 + 4 = 7, matching the 3-4-5-triangle fixture above.
    a = _line("A", (0.0, 0.0), (3.0, 0.0))
    b = _line("B", (3.0, 0.0), (3.0, 4.0))
    chains = stitch_chains([a, b], tolerance=1e-6)
    assert len(chains) == 1
    chain = chains[0]
    assert chain.vertices == [(0.0, 0.0), (3.0, 0.0), (3.0, 4.0)]
    assert polyline_length(chain.vertices) == pytest.approx(7.0)
    assert set(chain.entity_ids) == {"A", "B"}


def test_stitch_chains_merges_reversed_entity() -> None:
    # Line B is drawn "backwards" -- (3,4)-(3,0) -- but its endpoint (3,0)
    # still coincides with A's end (3,0), so the chain must be reversed
    # internally to keep vertices contiguous: same 7.0 total length.
    a = _line("A", (0.0, 0.0), (3.0, 0.0))
    b = _line("B", (3.0, 4.0), (3.0, 0.0))
    chains = stitch_chains([a, b], tolerance=1e-6)
    assert len(chains) == 1
    assert polyline_length(chains[0].vertices) == pytest.approx(7.0)


def test_stitch_chains_leaves_disconnected_entities_separate() -> None:
    # B starts 100 units away from A's end -- far outside any reasonable
    # tolerance -- so these must stay two separate chains.
    a = _line("A", (0.0, 0.0), (3.0, 0.0))
    b = _line("B", (103.0, 0.0), (103.0, 4.0))
    chains = stitch_chains([a, b], tolerance=1e-6)
    assert len(chains) == 2


def test_stitch_chains_respects_tolerance() -> None:
    # B starts 0.02 units from A's end. Tolerance 0.05 merges them;
    # tolerance 0.01 does not.
    a = _line("A", (0.0, 0.0), (3.0, 0.0))
    b = _line("B", (3.02, 0.0), (3.02, 4.0))
    assert len(stitch_chains([a, b], tolerance=0.05)) == 1
    assert len(stitch_chains([a, b], tolerance=0.01)) == 2


def test_stitch_chains_reversal_negates_and_reverses_bulges() -> None:
    # A: straight (0,0)-(10,0), no bulge. B: (20,0)-(10,0) with bulge=1.0
    # on the vertex at (20,0) -- i.e. the real arc is (20,0)->(10,0), a
    # semicircle. B's endpoint (10,0) touches A's endpoint (10,0), so B
    # must be reversed to append after A; reversing negates the bulge
    # (arc traversed the other way) but the arc's length is unaffected by
    # direction: total length = 10 (straight) + 5*pi (semicircle).
    a = GeometricEntity("line", "C-ROAD-CL", "A", [(0.0, 0.0), (10.0, 0.0)])
    b = GeometricEntity("lwpolyline", "C-ROAD-CL", "B", [(20.0, 0.0), (10.0, 0.0)], bulges=[1.0, 0.0])
    chains = stitch_chains([a, b], tolerance=1e-6)
    assert len(chains) == 1
    chain = chains[0]
    assert chain.vertices == [(0.0, 0.0), (10.0, 0.0), (20.0, 0.0)]
    assert chain.bulges == pytest.approx([0.0, -1.0])
    assert polyline_length(chain.vertices, bulges=chain.bulges) == pytest.approx(10.0 + 5.0 * math.pi)


# ---------------------------------------------------------------------------
# shoelace_area
# ---------------------------------------------------------------------------


def test_shoelace_area_rectangle() -> None:
    # A 10m x 3m rectangle, vertices in CCW order.
    rect = [(0.0, 0.0), (10.0, 0.0), (10.0, 3.0), (0.0, 3.0)]
    assert shoelace_area(rect) == pytest.approx(30.0)


def test_shoelace_area_is_winding_independent() -> None:
    # Same rectangle, vertices in CW order (reversed) -- area magnitude is
    # the same either way (shoelace_area returns the unsigned area).
    rect_cw = [(0.0, 0.0), (0.0, 3.0), (10.0, 3.0), (10.0, 0.0)]
    assert shoelace_area(rect_cw) == pytest.approx(30.0)


def test_shoelace_area_trapezoid_matches_left_right_corridor_case() -> None:
    # Left edge along y=0 from x=0 to x=10 (flat). Right edge goes from
    # (0,3) to (10,5) -- width tapers from 3m to 5m over the 10m run.
    # Polygon: left forward + right reversed = (0,0),(10,0),(10,5),(0,3).
    # Trapezoid area = average_width * length = ((3+5)/2) * 10 = 40 m^2.
    polygon = [(0.0, 0.0), (10.0, 0.0), (10.0, 5.0), (0.0, 3.0)]
    assert shoelace_area(polygon) == pytest.approx(40.0)


def test_shoelace_area_two_semicircles_is_a_full_circle() -> None:
    # Two points, (-5,0) and (5,0), joined by two bulge=1.0 edges (each a
    # semicircle of radius 5, per test_bulge_segment_area_correction) ->
    # together they trace a full circle of radius 5. Area = pi*r^2 =
    # 25*pi = 78.5398...
    vertices = [(-5.0, 0.0), (5.0, 0.0)]
    bulges = [1.0, 1.0]
    assert shoelace_area(vertices, bulges) == pytest.approx(25.0 * math.pi)


def test_shoelace_area_two_straight_points_have_no_area() -> None:
    # No bulges -> a degenerate 2-point "polygon" with two coincident
    # straight edges has zero area (the circle case above only has area
    # because its edges are arcs, not straight lines).
    assert shoelace_area([(0.0, 0.0), (1.0, 0.0)]) == 0.0


# ---------------------------------------------------------------------------
# trapezoidal_cross_section_area / prismoidal_volume (building blocks)
# ---------------------------------------------------------------------------


def test_trapezoidal_cross_section_area_rectangular() -> None:
    # top == bottom -> reduces to width * depth = 1.2 * 1.0 = 1.2 m^2.
    assert trapezoidal_cross_section_area(1.2, 1.2, 1.0) == pytest.approx(1.2)


def test_trapezoidal_cross_section_area_trapezoid() -> None:
    # (top + bottom) / 2 * depth = (2 + 1) / 2 * 1.5 = 1.5 * 1.5 = 2.25 m^2.
    assert trapezoidal_cross_section_area(2.0, 1.0, 1.5) == pytest.approx(2.25)


def test_prismoidal_volume_hand_worked() -> None:
    # V = L/6 * (A1 + 4*Am + A2) with L=10, A1=2, Am=3, A2=2:
    # 10/6 * (2 + 4*3 + 2) = 1.66667 * (2 + 12 + 2) = 1.66667 * 16 = 26.6667 m^3.
    volume = prismoidal_volume(length=10.0, area1=2.0, area_mid=3.0, area2=2.0)
    assert volume == pytest.approx(26.66667, abs=1e-4)


# ---------------------------------------------------------------------------
# trench_segment_volume / composite_trench_volume (dimension-averaged
# mid-section, per-segment -- works for any spacing)
# ---------------------------------------------------------------------------


def test_trench_segment_volume_hand_worked() -> None:
    # Two real cross-sections, 10m apart:
    #   station 0:  top=2.0, bottom=1.0, depth=1.5 -> A1 = (2+1)/2*1.5 = 2.25 m^2
    #   station 10: top=2.4, bottom=1.2, depth=1.6 -> A2 = (2.4+1.2)/2*1.6 = 2.88 m^2
    # Synthesized midsection from AVERAGED DIMENSIONS (not averaged areas):
    #   top_avg=2.2, bottom_avg=1.1, depth_avg=1.55
    #   Am = (2.2+1.1)/2 * 1.55 = 1.65 * 1.55 = 2.5575 m^2
    # V = L/6 * (A1 + 4*Am + A2) = 10/6 * (2.25 + 4*2.5575 + 2.88)
    #   = 10/6 * (2.25 + 10.23 + 2.88) = 10/6 * 15.36 = 25.6 m^3
    volume = trench_segment_volume(
        length=10.0, top1=2.0, bottom1=1.0, depth1=1.5, top2=2.4, bottom2=1.2, depth2=1.6
    )
    assert volume == pytest.approx(25.6)


def test_composite_trench_volume_three_evenly_spaced_sections() -> None:
    # Stations 0, 5, 10, each 5m apart -- two segments, each identical to
    # half of the hand-worked case above by symmetry:
    #   Segment 1 (0->5): A1=2.25 (top=2,bottom=1,depth=1.5),
    #                      A2=2.88 (top=2.4,bottom=1.2,depth=1.6)
    #                      Am dims: top=2.2,bottom=1.1,depth=1.55 -> Am=2.5575
    #                      V1 = 5/6 * (2.25 + 4*2.5575 + 2.88) = 5/6*15.36 = 12.8
    #   Segment 2 (5->10): A1=2.88, A2=2.25 (mirror of segment 1)
    #                      Am dims identical by symmetry -> Am=2.5575
    #                      V2 = 5/6 * (2.88 + 4*2.5575 + 2.25) = 5/6*15.36 = 12.8
    #   Total = 12.8 + 12.8 = 25.6 m^3
    volume = composite_trench_volume(
        [(0.0, 2.0, 1.0, 1.5), (5.0, 2.4, 1.2, 1.6), (10.0, 2.0, 1.0, 1.5)]
    )
    assert volume == pytest.approx(25.6)


def test_composite_trench_volume_uneven_spacing() -> None:
    # Stations 0, 3, 10 -- UNEVEN spacing (3m then 7m) -- per-segment
    # prismoidal needs no special-casing for this, unlike a composite
    # Simpson's-rule scheme over areas (which requires equal spacing to be
    # exact).
    #   Section @0:  top=2.0, bottom=1.0, depth=1.5 -> A = 2.25 m^2
    #   Section @3:  top=2.2, bottom=1.1, depth=1.5 -> A = (2.2+1.1)/2*1.5 = 2.475 m^2
    #   Section @10: top=2.0, bottom=1.0, depth=1.5 -> A = 2.25 m^2
    #
    #   Segment 1 (0->3, L=3):
    #     Am dims: top=(2.0+2.2)/2=2.1, bottom=(1.0+1.1)/2=1.05, depth=1.5
    #     Am = (2.1+1.05)/2*1.5 = 1.575*1.5 = 2.3625
    #     V1 = 3/6 * (2.25 + 4*2.3625 + 2.475) = 0.5 * (2.25+9.45+2.475)
    #        = 0.5 * 14.175 = 7.0875
    #
    #   Segment 2 (3->10, L=7):
    #     Am dims: top=(2.2+2.0)/2=2.1, bottom=(1.1+1.0)/2=1.05, depth=1.5
    #     Am = 2.3625 (same as segment 1's, by symmetry of the chosen numbers)
    #     V2 = 7/6 * (2.475 + 4*2.3625 + 2.25) = 7/6 * (2.475+9.45+2.25)
    #        = 7/6 * 14.175 = 16.5375
    #
    #   Total = 7.0875 + 16.5375 = 23.625 m^3
    volume = composite_trench_volume(
        [(0.0, 2.0, 1.0, 1.5), (3.0, 2.2, 1.1, 1.5), (10.0, 2.0, 1.0, 1.5)]
    )
    assert volume == pytest.approx(23.625)


def test_composite_trench_volume_two_sections_is_a_single_segment() -> None:
    # Only 2 sections -> exactly one call to trench_segment_volume; no
    # separate "2-section" code path.
    #   Station 0: top=bottom=1.0, depth=1.0 -> A=1.0 (rectangular)
    #   Station 10: same dims -> A=1.0
    #   Am dims == same dims too (averaging identical values changes
    #   nothing) -> Am=1.0
    #   V = 10/6 * (1.0 + 4*1.0 + 1.0) = 10/6 * 6.0 = 10.0 m^3
    volume = composite_trench_volume([(0.0, 1.0, 1.0, 1.0), (10.0, 1.0, 1.0, 1.0)])
    assert volume == pytest.approx(10.0)


def test_composite_trench_volume_sorts_out_of_order_input() -> None:
    # Same 3-station evenly-spaced case as above, fed in shuffled order --
    # must sort by station internally and still get 25.6 m^3.
    volume = composite_trench_volume(
        [(10.0, 2.0, 1.0, 1.5), (0.0, 2.0, 1.0, 1.5), (5.0, 2.4, 1.2, 1.6)]
    )
    assert volume == pytest.approx(25.6)


def test_composite_trench_volume_requires_at_least_two_sections() -> None:
    with pytest.raises(ValueError):
        composite_trench_volume([(0.0, 2.0, 1.0, 1.5)])
