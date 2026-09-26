"""AlignmentExtractor (road/utility centreline length + stationing) and
CorridorAreaExtractor (area of the strip between a matched left/right
boundary pair), per the intended algorithms documented in the original
stubs (see git history of geometry/stubs.py).

Layer matching, chain stitching, and side-pairing are all naming
conventions, not something derivable from DXF structure alone -- there is
no universal CAD standard for "this layer is a road centreline". The
defaults live in `geometry/config.py`, not here -- see that module's
docstring for why.
"""

from __future__ import annotations

from collections.abc import Iterable

from app.takeoff.geometry.base import Measurement
from app.takeoff.geometry.config import DEFAULT_GEOMETRY_CONFIG, AlignmentConfig, CorridorConfig
from app.takeoff.geometry.entities import GeometricEntity
from app.takeoff.geometry.geometry_math import (
    Chain,
    cumulative_stations,
    shoelace_area,
    stitch_chains,
)
from app.takeoff.geometry.units import sheet_scale_factor


def _sheet_units(sheet: object) -> str:
    return getattr(sheet, "units", None) or "unitless"


class AlignmentExtractor:
    """Road/utility centreline length + stationing.

    Algorithm: filter LINE/LWPOLYLINE entities to layers matching
    `config.layer_hints`, group by exact layer name (different layers are
    never stitched together -- two alignments that happen to touch, e.g. a
    road centreline crossing a sewer centreline, must not merge into one
    chain), stitch each layer's entities into chains (see
    `geometry_math.stitch_chains`, which preserves LWPOLYLINE bulges so
    curved alignment segments -- fillets, roundabouts -- contribute their
    true arc length, not the straight chord), and report each resulting
    chain's total length plus cumulative station intervals.

    Snap tolerance is specified in metres and converted to native units
    per-sheet; when the drawing's units are unrecognized ("unitless",
    $INSUNITS=0) the tolerance is used as a raw native-unit value instead
    (no way to convert it) and the resulting Measurement's confidence is
    lowered accordingly.
    """

    capability = "alignment"

    def __init__(self, config: AlignmentConfig = DEFAULT_GEOMETRY_CONFIG.alignment) -> None:
        self.config = config
        self._layer_hints = tuple(h.upper() for h in config.layer_hints)

    def supports(self, sheet: object) -> bool:
        return True

    def _matching_layers(self, entities: Iterable[GeometricEntity]) -> dict[str, list[GeometricEntity]]:
        by_layer: dict[str, list[GeometricEntity]] = {}
        for e in entities:
            if e.entity_type not in ("line", "lwpolyline") or not e.layer:
                continue
            if any(hint in e.layer.upper() for hint in self._layer_hints):
                by_layer.setdefault(e.layer, []).append(e)
        return by_layer

    def extract(self, sheet: object, entities: list[GeometricEntity]) -> list[Measurement]:
        unit = _sheet_units(sheet)
        factor = sheet_scale_factor(unit, getattr(sheet, "scale_ratio", None))
        confidence = 1.0 if factor is not None else 0.3
        native_tolerance = self.config.snap_tolerance_m / factor if factor else self.config.snap_tolerance_m

        measurements: list[Measurement] = []
        for layer, layer_entities in self._matching_layers(entities).items():
            for chain in stitch_chains(layer_entities, native_tolerance):
                measurements.append(self._measurement(layer, chain, factor, unit, confidence))
        return measurements

    @staticmethod
    def _measurement(layer: str, chain: Chain, factor: float | None, unit: str, confidence: float) -> Measurement:
        stations_native = cumulative_stations(chain.vertices, chain.bulges)
        length_native = stations_native[-1] if stations_native else 0.0
        length_m = length_native * factor if factor else length_native
        stations_m = [s * factor for s in stations_native] if factor else stations_native
        return Measurement(
            kind="alignment_length_m",
            value=length_m,
            unit="m" if factor else unit,
            source_entity_ids=[h for h in chain.entity_ids if h],
            confidence=confidence,
            metadata={"layer": layer, "vertex_count": len(chain.vertices), "station_intervals_m": stations_m},
        )


def _find_side_pairs(layer_names: Iterable[str], side_suffix_pairs: tuple[tuple[str, str], ...]) -> list[tuple[str, str]]:
    by_upper = {name.upper(): name for name in layer_names}
    used: set[str] = set()
    pairs: list[tuple[str, str]] = []
    for left_suffix, right_suffix in side_suffix_pairs:
        for upper_name, original_name in by_upper.items():
            if upper_name in used or not upper_name.endswith(left_suffix):
                continue
            base = upper_name[: -len(left_suffix)]
            right_upper = base + right_suffix
            if right_upper in by_upper and right_upper not in used:
                pairs.append((original_name, by_upper[right_upper]))
                used.add(upper_name)
                used.add(right_upper)
    return pairs


class CorridorAreaExtractor:
    """Area of the strip between a matched left/right boundary pair.

    Pairing is purely a layer-naming convention (`-L`/`-R`, `_LEFT`/
    `_RIGHT`, ...; see `config.side_suffix_pairs`) -- there is no geometric
    "which side is left" detection. Each side is stitched into chains
    independently (via the same `stitch_chains` used by AlignmentExtractor,
    so curved boundaries carry their bulges through); a pair is only
    measured when each side stitches to *exactly one* chain -- an ambiguous
    pair (multiple candidate chains on a side) is silently skipped rather
    than guessed at.

    Area comes from `shoelace_area` on the closed polygon formed by the
    left chain, a straight closing edge, the right chain reversed, and
    another straight closing edge back to the start -- not a
    vertex-by-vertex triangulation. This means the two sides no longer need
    matching vertex counts or aligned stationing (an earlier triangulation
    approach did require both, since it paired left[i] with right[i]
    directly); shoelace only needs both chains, in order, to trace a
    simple (non-self-intersecting) polygon once joined. The two closing
    edges at the ends of the corridor are always assumed straight -- a
    curved end-cap isn't modeled.
    """

    capability = "corridor_area"

    def __init__(self, config: CorridorConfig = DEFAULT_GEOMETRY_CONFIG.corridor) -> None:
        self.config = config

    def supports(self, sheet: object) -> bool:
        return True

    def extract(self, sheet: object, entities: list[GeometricEntity]) -> list[Measurement]:
        unit = _sheet_units(sheet)
        factor = sheet_scale_factor(unit, getattr(sheet, "scale_ratio", None))
        # Lower baseline confidence than AlignmentExtractor: pairing sides
        # by layer-name suffix is a heuristic on top of an already-heuristic
        # layer match, not a direct read of the geometry.
        confidence = 0.8 if factor is not None else 0.25
        native_tolerance = self.config.snap_tolerance_m / factor if factor else self.config.snap_tolerance_m

        by_layer: dict[str, list[GeometricEntity]] = {}
        for e in entities:
            if e.entity_type not in ("line", "lwpolyline") or not e.layer:
                continue
            by_layer.setdefault(e.layer, []).append(e)

        measurements: list[Measurement] = []
        for left_layer, right_layer in _find_side_pairs(by_layer.keys(), self.config.side_suffix_pairs):
            left_chains = stitch_chains(by_layer[left_layer], native_tolerance)
            right_chains = stitch_chains(by_layer[right_layer], native_tolerance)
            if len(left_chains) != 1 or len(right_chains) != 1:
                continue
            left, right = left_chains[0], right_chains[0]

            polygon_vertices = [*left.vertices, *reversed(right.vertices)]
            polygon_bulges = [
                *left.bulges,
                0.0,  # closing edge: left's last vertex -> right's last vertex
                *(-b for b in reversed(right.bulges)),
                0.0,  # closing edge: right's first vertex -> left's first vertex
            ]
            area_native = shoelace_area(polygon_vertices, polygon_bulges)
            area_m2 = area_native * factor * factor if factor else area_native
            measurements.append(
                Measurement(
                    kind="corridor_area_m2",
                    value=area_m2,
                    unit="m2" if factor else unit,
                    source_entity_ids=[h for h in (*left.entity_ids, *right.entity_ids) if h],
                    confidence=confidence,
                    metadata={
                        "left_layer": left_layer,
                        "right_layer": right_layer,
                        "left_vertex_count": len(left.vertices),
                        "right_vertex_count": len(right.vertices),
                    },
                )
            )
        return measurements
