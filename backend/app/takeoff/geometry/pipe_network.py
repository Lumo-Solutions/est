"""PipeNetworkTopologyExtractor: pipe network graph (nodes = manholes/
chambers, edges = pipe runs), per the algorithm documented in the original
stub (see git history of geometry/stubs.py).

Deliberately *not* built on `geometry_math.stitch_chains`: pipe networks
branch (a manhole commonly has 3+ connecting runs), which chain-stitching
assumes doesn't happen (see its docstring). Instead this builds an explicit
node/edge graph: nodes come from INSERT blocks matching a manhole/chamber
naming convention, edges come from pipe-layer polylines whose endpoints are
snapped to the nearest node within tolerance (or left dangling if none is
close enough -- a real condition worth surfacing, not an error).

If *more than one* node falls within tolerance of a pipe endpoint, the
nearest is still reported (so a downstream consumer sees a best guess
rather than nothing), but the match is flagged ambiguous in the
measurement's metadata and the measurement's confidence is halved -- never
picked silently. This matters most right where the default tolerance is
largest (manholes clustered near a junction chamber, all within the 1m
default).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.takeoff.geometry.base import Measurement
from app.takeoff.geometry.config import DEFAULT_GEOMETRY_CONFIG, PipeNetworkConfig
from app.takeoff.geometry.entities import GeometricEntity, Point
from app.takeoff.geometry.geometry_math import distance, polyline_length
from app.takeoff.geometry.units import meters_per_unit


@dataclass(slots=True)
class _Node:
    id: str
    position: Point


@dataclass(slots=True)
class _NodeMatch:
    node: _Node | None
    ambiguous: bool
    candidate_ids: list[str]


class PipeNetworkTopologyExtractor:
    capability = "pipe_network_topology"

    def __init__(self, config: PipeNetworkConfig = DEFAULT_GEOMETRY_CONFIG.pipe_network) -> None:
        self.config = config
        self._node_block_hints = tuple(h.upper() for h in config.node_block_hints)
        self._pipe_layer_hints = tuple(h.upper() for h in config.pipe_layer_hints)

    def supports(self, sheet: object) -> bool:
        return True

    def _nodes(self, entities: list[GeometricEntity]) -> list[_Node]:
        nodes: list[_Node] = []
        for e in entities:
            if e.entity_type != "insert_node" or not e.block_name or not e.vertices:
                continue
            if any(hint in e.block_name.upper() for hint in self._node_block_hints):
                nodes.append(_Node(id=e.handle or f"node-{len(nodes)}", position=e.vertices[0]))
        return nodes

    def _pipes(self, entities: list[GeometricEntity]) -> list[GeometricEntity]:
        return [
            e
            for e in entities
            if e.entity_type in ("line", "lwpolyline")
            and e.layer
            and len(e.vertices) >= 2
            and any(hint in e.layer.upper() for hint in self._pipe_layer_hints)
        ]

    @staticmethod
    def _resolve_node(point: Point, nodes: list[_Node], tolerance: float) -> _NodeMatch:
        within = sorted(((distance(point, n.position), n) for n in nodes), key=lambda dn: dn[0])
        within = [(d, n) for d, n in within if d <= tolerance]
        if not within:
            return _NodeMatch(node=None, ambiguous=False, candidate_ids=[])
        if len(within) == 1:
            return _NodeMatch(node=within[0][1], ambiguous=False, candidate_ids=[])
        return _NodeMatch(node=within[0][1], ambiguous=True, candidate_ids=[n.id for _, n in within])

    def extract(self, sheet: object, entities: list[GeometricEntity]) -> list[Measurement]:
        unit = getattr(sheet, "units", None) or "unitless"
        factor = meters_per_unit(unit)
        base_confidence = 0.7 if factor is not None else 0.25
        native_tolerance = self.config.snap_tolerance_m / factor if factor else self.config.snap_tolerance_m

        nodes = self._nodes(entities)
        pipes = self._pipes(entities)

        measurements: list[Measurement] = []
        total_length_native = 0.0
        for pipe in pipes:
            start = self._resolve_node(pipe.vertices[0], nodes, native_tolerance)
            end = self._resolve_node(pipe.vertices[-1], nodes, native_tolerance)
            length_native = polyline_length(pipe.vertices, bulges=pipe.bulges or None)
            total_length_native += length_native
            length_m = length_native * factor if factor else length_native

            confidence = base_confidence
            if start.ambiguous or end.ambiguous:
                confidence = base_confidence / 2.0

            metadata: dict[str, object] = {
                "layer": pipe.layer,
                "from_node": start.node.id if start.node else None,
                "to_node": end.node.id if end.node else None,
                "diameter": pipe.attributes.get(self.config.diameter_attr),
                "material": pipe.attributes.get(self.config.material_attr),
            }
            if start.ambiguous:
                metadata["from_node_ambiguous"] = True
                metadata["from_node_candidates"] = start.candidate_ids
            if end.ambiguous:
                metadata["to_node_ambiguous"] = True
                metadata["to_node_candidates"] = end.candidate_ids

            measurements.append(
                Measurement(
                    kind="pipe_run_length_m",
                    value=length_m,
                    unit="m" if factor else unit,
                    source_entity_ids=[pipe.handle] if pipe.handle else [],
                    confidence=confidence,
                    metadata=metadata,
                )
            )

        if pipes:
            total_length_m = total_length_native * factor if factor else total_length_native
            measurements.append(
                Measurement(
                    kind="pipe_network_total_length_m",
                    value=total_length_m,
                    unit="m" if factor else unit,
                    source_entity_ids=[],
                    confidence=base_confidence,
                    metadata={"node_count": len(nodes), "edge_count": len(pipes)},
                )
            )
        return measurements
