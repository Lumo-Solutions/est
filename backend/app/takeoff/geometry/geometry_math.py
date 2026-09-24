"""Pure geometry/numerical-integration math shared by the extractors. No
DXF, DB, or Measurement types here on purpose -- everything in this module
takes and returns plain floats/tuples so it can be hand-checked and unit
tested in complete isolation from the rest of the pipeline.

All lengths/areas/volumes here are in whatever unit the caller's input
coordinates are in (native drawing units, or metres if the caller already
converted) -- this module never does unit conversion, see units.py for that.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from app.takeoff.geometry.entities import GeometricEntity, Point


def distance(a: Point, b: Point) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


# ---------------------------------------------------------------------------
# Bulge (LWPOLYLINE arc-segment) geometry
# ---------------------------------------------------------------------------
#
# DXF convention: a vertex's "bulge" is tan(included_angle / 4) for the arc
# replacing the straight edge from that vertex to the next one. Positive
# bulge sweeps counter-clockwise from the first point to the second;
# negative sweeps clockwise. bulge == 0.0 is a straight edge. Verified
# against ezdxf's own `ezdxf.math.bulge_to_arc()` (see tests/unit/
# test_geometry_math.py) rather than assumed.


def bulge_included_angle(bulge: float) -> float:
    return 4.0 * math.atan(bulge)


def bulge_radius(chord_length: float, included_angle: float) -> float:
    if included_angle == 0.0:
        return 0.0
    return chord_length / (2.0 * math.sin(included_angle / 2.0))


def bulge_segment_length(p1: Point, p2: Point, bulge: float) -> float:
    """Length of the edge from p1 to p2, as a straight line if bulge == 0.0,
    or as the circular arc the bulge describes otherwise."""
    if bulge == 0.0:
        return distance(p1, p2)
    theta = bulge_included_angle(bulge)
    r = bulge_radius(distance(p1, p2), theta)
    return abs(r * theta)


def bulge_segment_area_correction(p1: Point, p2: Point, bulge: float) -> float:
    """Signed area of the circular segment between the chord p1->p2 and the
    arc the bulge describes -- the amount to add to a straight-edge
    (shoelace) polygon area when this edge is actually that arc. Sign
    follows the bulge/theta sign directly (same traversal direction used by
    the shoelace sum this feeds into); see `shoelace_area`."""
    if bulge == 0.0:
        return 0.0
    theta = bulge_included_angle(bulge)
    r = bulge_radius(distance(p1, p2), theta)
    return 0.5 * r * r * (theta - math.sin(theta))


def polyline_length(vertices: list[Point], closed: bool = False, bulges: list[float] | None = None) -> float:
    if len(vertices) < 2:
        return 0.0
    bulges = bulges if bulges is not None else [0.0] * len(vertices)
    total = sum(bulge_segment_length(vertices[i], vertices[i + 1], bulges[i]) for i in range(len(vertices) - 1))
    if closed:
        total += bulge_segment_length(vertices[-1], vertices[0], bulges[-1])
    return total


def cumulative_stations(vertices: list[Point], bulges: list[float] | None = None) -> list[float]:
    """Running distance-along-chain at each vertex, starting at 0.0."""
    bulges = bulges if bulges is not None else [0.0] * len(vertices)
    stations = [0.0]
    for i in range(1, len(vertices)):
        stations.append(stations[-1] + bulge_segment_length(vertices[i - 1], vertices[i], bulges[i - 1]))
    return stations


def arc_length(radius: float, start_angle_deg: float, end_angle_deg: float) -> float:
    """DXF ARC entities always sweep counter-clockwise from start_angle to
    end_angle; identical angles is a degenerate (zero-length) arc, not a
    full circle -- a full circle is a CIRCLE entity, never an ARC."""
    span_deg = (end_angle_deg - start_angle_deg) % 360.0
    return radius * math.radians(span_deg)


def entity_length(entity: GeometricEntity) -> float:
    if entity.entity_type in ("line", "lwpolyline"):
        return polyline_length(entity.vertices, entity.closed, entity.bulges or None)
    if entity.entity_type == "arc" and entity.radius is not None:
        return arc_length(entity.radius, entity.start_angle_deg or 0.0, entity.end_angle_deg or 0.0)
    return 0.0


# ---------------------------------------------------------------------------
# Chain stitching (alignments / corridor boundaries)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Chain:
    vertices: list[Point]
    # bulges[i] is the arc from vertices[i] to vertices[i+1]; always
    # len(vertices) - 1 long (chains built by stitching open entities are
    # never themselves "closed", so there's no wrap-around edge to store a
    # bulge for).
    bulges: list[float] = field(default_factory=list)
    entity_ids: list[str] = field(default_factory=list)


def _entity_bulges(e: GeometricEntity) -> list[float]:
    if e.bulges:
        return list(e.bulges[: len(e.vertices) - 1])
    return [0.0] * (len(e.vertices) - 1)


def stitch_chains(entities: list[GeometricEntity], tolerance: float) -> list[Chain]:
    """Greedily merges LINE/LWPOLYLINE entities whose endpoints coincide
    within `tolerance` (native units) into continuous chains, preserving
    each segment's bulge (arc) so downstream length/stationing/area math
    stays exact for curved alignments -- not just polylines with straight
    segments.

    Assumptions (see AlignmentExtractor/CorridorAreaExtractor docstrings for
    the layer-scoping that must happen *before* calling this):
    - Non-branching: if more than two entity endpoints meet at one point
      (a junction/T), stitching greedily merges the first matching pair it
      finds and stops there -- the result may depend on entity order. Fine
      for a single road/utility centreline; not a substitute for a real
      topological graph (see pipe_network.py, which builds one instead of
      stitching, precisely because pipe networks branch).
    - Direction-agnostic: a chain is reversed as needed to align endpoints.
      Reversing negates and reverses the bulge list too (traversing an arc
      backwards sweeps the opposite way), so a reversed segment's curvature
      still describes the same physical arc.
    """
    chains: list[Chain | None] = [
        Chain(vertices=list(e.vertices), bulges=_entity_bulges(e), entity_ids=[e.handle] if e.handle else [])
        for e in entities
        if e.entity_type in ("line", "lwpolyline") and len(e.vertices) >= 2
    ]

    merged = True
    while merged:
        merged = False
        for i in range(len(chains)):
            a = chains[i]
            if a is None:
                continue
            for j in range(len(chains)):
                if i == j:
                    continue
                b = chains[j]
                if b is None:
                    continue
                if distance(a.vertices[-1], b.vertices[0]) <= tolerance:
                    a.vertices.extend(b.vertices[1:])
                    a.bulges.extend(b.bulges)
                    a.entity_ids.extend(b.entity_ids)
                    chains[j] = None
                    merged = True
                elif distance(a.vertices[-1], b.vertices[-1]) <= tolerance:
                    a.vertices.extend(reversed(b.vertices[:-1]))
                    a.bulges.extend(-x for x in reversed(b.bulges))
                    a.entity_ids.extend(b.entity_ids)
                    chains[j] = None
                    merged = True

    return [c for c in chains if c is not None]


# ---------------------------------------------------------------------------
# Polygon area (shoelace, with optional per-edge bulges)
# ---------------------------------------------------------------------------


def shoelace_area(vertices: list[Point], bulges: list[float] | None = None) -> float:
    """Unsigned area of the closed polygon traced by `vertices` (edge i runs
    from vertices[i] to vertices[(i+1) % n]), via the shoelace formula, with
    an optional per-edge bulge replacing the straight edge with a circular
    arc (see bulge_segment_area_correction). Works for any winding order; a
    polygon that self-intersects gives a meaningless result, same as plain
    shoelace always has. Fewer than 3 vertices only has area when bulges
    give it one -- e.g. 2 points joined by two opposing arcs traces a lens
    or a full circle (see test_shoelace_area_two_semicircles_is_a_full_circle)
    -- so this doesn't special-case n < 3 to zero the way a
    straight-edges-only implementation would.
    """
    n = len(vertices)
    if n < 2:
        return 0.0
    bulges = bulges if bulges is not None else [0.0] * n
    signed = 0.0
    correction = 0.0
    for i in range(n):
        x1, y1 = vertices[i]
        x2, y2 = vertices[(i + 1) % n]
        signed += x1 * y2 - x2 * y1
        correction += bulge_segment_area_correction(vertices[i], vertices[(i + 1) % n], bulges[i])
    return abs(signed / 2.0 + correction)


# ---------------------------------------------------------------------------
# Trench cross-section area + prismoidal volume
# ---------------------------------------------------------------------------


def trapezoidal_cross_section_area(top_width: float, bottom_width: float, depth: float) -> float:
    """Area of a trapezoidal trench cross-section; reduces to width*depth
    for a rectangular trench (top_width == bottom_width)."""
    return depth * (top_width + bottom_width) / 2.0


def prismoidal_volume(length: float, area1: float, area_mid: float, area2: float) -> float:
    """The prismoidal formula: V = L/6 * (A1 + 4*Am + A2), exact for any
    solid whose cross-sectional area varies as at most a quadratic function
    of distance along `length`. Requires `area_mid` to be the actual
    cross-section area at the midpoint of `length` -- callers that
    synthesize a midpoint (no real survey at that station) should build it
    from averaged *dimensions*, not averaged *areas*; see
    `trench_segment_volume`, which does this for trenches."""
    return length / 6.0 * (area1 + 4.0 * area_mid + area2)


def trench_segment_volume(
    length: float,
    top1: float, bottom1: float, depth1: float,
    top2: float, bottom2: float, depth2: float,
) -> float:
    """Prismoidal volume of a trench run between two real cross-sections,
    with the middle cross-section synthesized by averaging each *dimension*
    (top width, bottom width, depth) between the two ends -- not by
    averaging the two end areas, which double-counts the trapezoid's own
    nonlinearity and is a less accurate approximation. This needs only the
    two real end sections and works for any `length`, so unevenly-spaced
    stations along a trench run need no special-casing (unlike a composite
    Simpson's-rule scheme over cross-section *areas*, which is only exact
    for equally-spaced stations -- that approach was tried first and
    replaced with this one for exactly that reason)."""
    a1 = trapezoidal_cross_section_area(top1, bottom1, depth1)
    a2 = trapezoidal_cross_section_area(top2, bottom2, depth2)
    am = trapezoidal_cross_section_area(
        (top1 + top2) / 2.0, (bottom1 + bottom2) / 2.0, (depth1 + depth2) / 2.0
    )
    return prismoidal_volume(length, a1, am, a2)


def composite_trench_volume(sections: list[tuple[float, float, float, float]]) -> float:
    """Total trench volume across a series of (station, top_width,
    bottom_width, depth) cross-sections, in any order and at any spacing:
    sorts by station, then sums `trench_segment_volume` over every
    consecutive pair. Requires at least 2 sections (one section has no
    length to integrate over)."""
    if len(sections) < 2:
        raise ValueError("need at least 2 cross-sections to compute a volume")

    ordered = sorted(sections, key=lambda s: s[0])
    total = 0.0
    for (s1, t1, b1, d1), (s2, t2, b2, d2) in zip(ordered, ordered[1:], strict=False):
        total += trench_segment_volume(s2 - s1, t1, b1, d1, t2, b2, d2)
    return total
