"""Shared geometric-entity representation used by every extractor in this
package. `app.takeoff.dxf.index_dxf_geometry()` builds these from a live
ezdxf document (the production path); tests build them directly by hand,
which is what makes the hand-computed fixtures in tests/unit/test_*_geometry
possible without a real DXF file on disk.

Coordinates are always `(x, y)` pairs in the drawing's native units (see
`units.py`) -- this package does not model Z / 3D geometry at all: trench
depth and cross-section dimensions are read from explicit width/depth
attributes, not from 3D entity coordinates, and alignments/pipe networks are
treated as planar.
"""

from __future__ import annotations

from dataclasses import dataclass, field

Point = tuple[float, float]


@dataclass(slots=True)
class GeometricEntity:
    entity_type: str  # "line" | "lwpolyline" | "arc" | "insert_node"
    layer: str | None
    handle: str | None
    vertices: list[Point] = field(default_factory=list)
    closed: bool = False
    # LWPOLYLINE bulge per vertex (DXF convention: bulges[i] is the arc
    # replacing the straight edge from vertices[i] to vertices[i+1]; the
    # segment is a straight line when bulges[i] == 0.0). Always the same
    # length as `vertices` when populated -- the last entry is only
    # meaningful when `closed` is True (arc closing back to vertices[0]).
    # Empty for entity types that carry no curvature (LINE, INSERT).
    bulges: list[float] = field(default_factory=list)
    block_name: str | None = None
    attributes: dict[str, str] = field(default_factory=dict)
    # ARC-only fields (DXF angle convention: degrees, counter-clockwise from
    # the positive X axis).
    center: Point | None = None
    radius: float | None = None
    start_angle_deg: float | None = None
    end_angle_deg: float | None = None
