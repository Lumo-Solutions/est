"""TrenchPrismoidalVolumeExtractor: trench excavation volume via the
prismoidal formula, per the algorithm documented in the original stub (see
git history of geometry/stubs.py).

Unlike AlignmentExtractor/CorridorAreaExtractor (which only need layer-name
conventions), this needs cross-section *dimensions* (width/depth), which
DXF geometry alone doesn't carry -- no drawing convention for this existed
anywhere in the codebase before this extractor, so one had to be invented
here. It is deliberately narrow and explicit rather than inferred:

**Convention** (attribute tag names configurable via `config.py`, defaults
below): a cross-section is an INSERT block on a layer matching
`config.layer_hints` (default: any layer name containing "TRENCH-XSEC",
"TRENCH_XSEC", or "TRENCH-SECTION"), carrying ATTRIB tags:

- `STATION`       -- distance along the trench run, in the drawing's native
                     units (numeric text)
- `WIDTH_TOP`, `WIDTH_BOTTOM`, `DEPTH` -- native units (numeric text)
- `TRENCH_ID`     -- optional; groups markers into separate trench runs on
                     the same sheet (default group: "default")

A marker missing or failing to parse any required attribute is skipped
(logged nowhere yet -- there's no per-marker warning channel in this slice),
not defaulted to zero, since a silently-wrong volume is worse than a
missing one. **This convention has not been validated against a real
client drawing** -- flag for review once sample trench cross-section sheets
are available; the prismoidal math itself (`geometry_math.py`) is
convention-independent and fully covered by hand-computed tests regardless.

Uneven station spacing between cross-sections needs no special-casing:
volume is computed pairwise between *every* consecutive pair of real
cross-sections via `geometry_math.trench_segment_volume`, which synthesizes
its own midpoint from averaged dimensions rather than assuming any
particular spacing. An earlier version used a composite Simpson's-rule
scheme over cross-section *areas*, grouping sections into triads -- that
is only exact for equally-spaced stations, so it was replaced.
"""

from __future__ import annotations

from app.takeoff.geometry.base import Measurement
from app.takeoff.geometry.config import DEFAULT_GEOMETRY_CONFIG, TrenchConfig
from app.takeoff.geometry.entities import GeometricEntity
from app.takeoff.geometry.geometry_math import composite_trench_volume
from app.takeoff.geometry.units import meters_per_unit


class TrenchPrismoidalVolumeExtractor:
    capability = "trench_prismoidal_volume"

    def __init__(self, config: TrenchConfig = DEFAULT_GEOMETRY_CONFIG.trench) -> None:
        self.config = config
        self._layer_hints = tuple(h.upper() for h in config.layer_hints)

    def supports(self, sheet: object) -> bool:
        return True

    def extract(self, sheet: object, entities: list[GeometricEntity]) -> list[Measurement]:
        unit = getattr(sheet, "units", None) or "unitless"
        factor = meters_per_unit(unit)
        # Lowest baseline confidence of the four extractors: depends on an
        # unvalidated drawing convention on top of a layer-name heuristic.
        confidence = 0.6 if factor is not None else 0.2

        cfg = self.config
        by_trench: dict[str, list[GeometricEntity]] = {}
        for e in entities:
            if e.entity_type != "insert_node" or not e.layer:
                continue
            if not any(hint in e.layer.upper() for hint in self._layer_hints):
                continue
            trench_id = e.attributes.get(cfg.trench_id_attr, cfg.default_trench_id)
            by_trench.setdefault(trench_id, []).append(e)

        measurements: list[Measurement] = []
        for trench_id, markers in by_trench.items():
            sections: list[tuple[float, float, float, float, str | None]] = []
            for m in markers:
                try:
                    station = float(m.attributes[cfg.station_attr])
                    top = float(m.attributes[cfg.width_top_attr])
                    bottom = float(m.attributes[cfg.width_bottom_attr])
                    depth = float(m.attributes[cfg.depth_attr])
                except (KeyError, ValueError):
                    continue
                sections.append((station, top, bottom, depth, m.handle))

            if len(sections) < 2:
                continue

            sections.sort(key=lambda s: s[0])
            volume_native = composite_trench_volume([(s, t, b, d) for s, t, b, d, _ in sections])
            # station is a native-unit length, area is native-units^2, so
            # the raw product is native-units^3 -- one overall factor**3 to
            # get m^3, not factor then factor**2 separately.
            volume_m3 = volume_native * (factor**3) if factor else volume_native

            measurements.append(
                Measurement(
                    kind="trench_volume_m3",
                    value=volume_m3,
                    unit="m3" if factor else unit,
                    source_entity_ids=[h for *_, h in sections if h],
                    confidence=confidence,
                    metadata={"trench_id": trench_id, "section_count": len(sections)},
                )
            )
        return measurements
