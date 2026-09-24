"""Per-project configuration for the geometry extractors.

Every layer-name hint, DXF attribute tag, and tolerance an extractor uses is
a naming/drawing convention, not something derivable from DXF structure --
different clients (and even different disciplines within one client) name
their alignment/pipe/trench layers differently. None of that belongs
hard-coded inside an extractor class; it lives here instead, as plain,
serializable dataclasses with the current best-guess defaults, so a real
per-project override (once there's a settings store to read one from -- see
docs/takeoff-pipeline.md's Phase 2b/3 notes) is just constructing a
different `GeometryExtractionConfig` and passing it to the extractors,
never editing extractor code.

`register_geometry_extractors()` in `stubs.py` (and today, that's the only
production call site) registers extractors built from
`DEFAULT_GEOMETRY_CONFIG` -- the module-level registry has no notion of
"per project" yet, so it can only ever hold one, default-configured
instance per capability. A caller that needs a project-specific
configuration should construct its own extractor instances directly with a
project's `GeometryExtractionConfig`, bypassing the registry.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class AlignmentConfig:
    layer_hints: tuple[str, ...] = ("ALIGN", "CENTERLINE", "CENTRELINE", "-CL", "_CL")
    snap_tolerance_m: float = 0.01


@dataclass(frozen=True, slots=True)
class CorridorConfig:
    # (left_suffix, right_suffix) pairs tried in order; matching is
    # case-insensitive against the layer name.
    side_suffix_pairs: tuple[tuple[str, str], ...] = (
        ("-L", "-R"),
        ("_L", "_R"),
        ("-LEFT", "-RIGHT"),
        ("_LEFT", "_RIGHT"),
    )
    snap_tolerance_m: float = 0.01


@dataclass(frozen=True, slots=True)
class TrenchConfig:
    layer_hints: tuple[str, ...] = ("TRENCH-XSEC", "TRENCH_XSEC", "TRENCH-SECTION")
    station_attr: str = "STATION"
    width_top_attr: str = "WIDTH_TOP"
    width_bottom_attr: str = "WIDTH_BOTTOM"
    depth_attr: str = "DEPTH"
    trench_id_attr: str = "TRENCH_ID"
    default_trench_id: str = "default"


@dataclass(frozen=True, slots=True)
class PipeNetworkConfig:
    node_block_hints: tuple[str, ...] = ("MH", "MANHOLE", "CHAMBER", "CATCHBASIN", "CB")
    pipe_layer_hints: tuple[str, ...] = ("PIPE", "SEWER", "STORM", "DRAIN")
    # Deliberately much larger than the alignment/corridor tolerance: pipe
    # polylines are commonly drawn to a manhole's rim or a schematic offset,
    # not its exact insertion point.
    snap_tolerance_m: float = 1.0
    diameter_attr: str = "DIAMETER"
    material_attr: str = "MATERIAL"


@dataclass(frozen=True, slots=True)
class GeometryExtractionConfig:
    alignment: AlignmentConfig = field(default_factory=AlignmentConfig)
    corridor: CorridorConfig = field(default_factory=CorridorConfig)
    trench: TrenchConfig = field(default_factory=TrenchConfig)
    pipe_network: PipeNetworkConfig = field(default_factory=PipeNetworkConfig)


DEFAULT_GEOMETRY_CONFIG = GeometryExtractionConfig()
