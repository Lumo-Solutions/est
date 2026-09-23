"""Registered but disabled extractors for the deferred geometric-intelligence
roadmap. Each documents its intended algorithm and required inputs so a
future implementer has a concrete starting point instead of a blank file.
None of these are wired into the Celery pipeline in this slice."""

from __future__ import annotations

from app.takeoff.geometry.base import GeometryExtractor, Measurement, register


class _NotImplementedExtractor:
    capability: str
    _description: str

    def supports(self, sheet: object) -> bool:
        return False

    def extract(self, sheet: object, entities: list[object]) -> list[Measurement]:
        raise NotImplementedError(self._description)


class AlignmentExtractor(_NotImplementedExtractor):
    """Road/utility centreline alignment measurement.

    Intended algorithm: identify polyline chains on alignment-convention
    layers (client-specific naming, e.g. "C-ROAD-CL", "ALIGNMENT"), stitch
    connected LWPOLYLINE/LINE segments end-to-end within a tolerance, and
    report total length + station intervals. Requires: drawing_entities rows
    with geometry populated (TAKEOFF_PERSIST_GEOMETRY=true) and a per-client
    layer-naming survey before the layer-matching heuristic is worth writing.
    """

    capability = "alignment"
    _description = (
        "AlignmentExtractor is not implemented -- see class docstring for the "
        "intended approach and prerequisites."
    )


class CorridorAreaExtractor(_NotImplementedExtractor):
    """Corridor area (road/utility easement footprint) from paired
    boundary/kerb alignments.

    Intended algorithm: given two roughly-parallel alignment polylines (from
    AlignmentExtractor output or matched layer pairs), triangulate the strip
    between them and sum triangle areas. Requires AlignmentExtractor first.
    """

    capability = "corridor_area"
    _description = "CorridorAreaExtractor is not implemented -- depends on AlignmentExtractor."


class TrenchPrismoidalVolumeExtractor(_NotImplementedExtractor):
    """Trench excavation volume via the prismoidal formula.

    Intended algorithm: V = L/6 * (A1 + 4*Am + A2) across cross-sections
    derived from trench width/depth annotations or a linked cross-section
    detail sheet, applied along an alignment's stationing. Requires
    AlignmentExtractor plus a convention for locating cross-section details
    (typically a separate detail sheet cross-referenced by drawing_number).
    """

    capability = "trench_prismoidal_volume"
    _description = (
        "TrenchPrismoidalVolumeExtractor is not implemented -- needs alignment "
        "stationing and cross-section detail linking first."
    )


class PipeNetworkTopologyExtractor(_NotImplementedExtractor):
    """Pipe network graph (nodes = manholes/chambers, edges = pipe runs).

    Intended algorithm: parse INSERT blocks matching manhole/chamber
    conventions as graph nodes, connect them via nearby pipe-layer polylines
    within a snap tolerance, and attach diameter/material from block
    attributes or adjacent text. Feeds hydraulic/BOQ quantity takeoff later.
    """

    capability = "pipe_network_topology"
    _description = "PipeNetworkTopologyExtractor is not implemented -- see class docstring."


class TypologyClusterExtractor(_NotImplementedExtractor):
    """Repeating villa/unit-type clustering for controlled multiplication.

    Intended algorithm: cluster INSERT block instances (or bounded entity
    groups) by geometric similarity (shape signature + dimensions) across
    sheets, group into "master types" with per-instance variant deltas
    (explicit overrides), and support "quantify one, multiply N, flag
    deltas" workflows described in MASTER_SRS.MD Module B. This is the
    largest of the deferred items and likely needs its own design pass.
    """

    capability = "typology_cluster"
    _description = "TypologyClusterExtractor is not implemented -- see class docstring."


def register_stubs() -> None:
    for cls in (
        AlignmentExtractor,
        CorridorAreaExtractor,
        TrenchPrismoidalVolumeExtractor,
        PipeNetworkTopologyExtractor,
        TypologyClusterExtractor,
    ):
        register(cls())  # type: ignore[arg-type]


register_stubs()
