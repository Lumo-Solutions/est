"""Extension point for the geometric-intelligence roadmap (alignments,
corridor areas, trench prismoidal volumes, pipe network topology, clustered
typology recognition -- MASTER_SRS.MD Module B) that is explicitly deferred
in this slice. See docs/takeoff-pipeline.md for why, and
docs/deploy-deltas.md / the plan's "Recommendation to the user" for the
suggested order of attack.

The shape here is deliberately small: a Protocol + registry, so adding a
real extractor later is "write a class + register it + flip
TAKEOFF_PERSIST_GEOMETRY on", not a redesign of the ingestion pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Measurement:
    kind: str  # e.g. "alignment_length_m", "corridor_area_m2", "trench_volume_m3"
    value: float
    unit: str
    source_entity_ids: list[str]
    confidence: float
    metadata: dict


class GeometryExtractor(Protocol):
    capability: str

    def supports(self, sheet: object) -> bool: ...

    def extract(self, sheet: object, entities: list[object]) -> list[Measurement]: ...


_REGISTRY: dict[str, GeometryExtractor] = {}


def register(extractor: GeometryExtractor) -> None:
    _REGISTRY[extractor.capability] = extractor


def get_registry() -> dict[str, GeometryExtractor]:
    return dict(_REGISTRY)
