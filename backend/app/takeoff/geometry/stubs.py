"""Registered but disabled extractors for the deferred geometric-intelligence
roadmap. AlignmentExtractor, CorridorAreaExtractor,
TrenchPrismoidalVolumeExtractor, and PipeNetworkTopologyExtractor have real
implementations now -- see alignment.py, volumes.py, pipe_network.py, and
`register_geometry_extractors()` below. TypologyClusterExtractor remains
here: it's the largest of the deferred items and explicitly called out (see
its docstring) as needing its own design pass before implementation."""

from __future__ import annotations

from app.takeoff.geometry.alignment import AlignmentExtractor, CorridorAreaExtractor
from app.takeoff.geometry.base import Measurement, register
from app.takeoff.geometry.pipe_network import PipeNetworkTopologyExtractor
from app.takeoff.geometry.volumes import TrenchPrismoidalVolumeExtractor


class TypologyClusterExtractor:
    """Repeating villa/unit-type clustering for controlled multiplication.

    Intended algorithm: cluster INSERT block instances (or bounded entity
    groups) by geometric similarity (shape signature + dimensions) across
    sheets, group into "master types" with per-instance variant deltas
    (explicit overrides), and support "quantify one, multiply N, flag
    deltas" workflows described in MASTER_SRS.MD Module B. This is the
    largest of the deferred items and likely needs its own design pass.
    """

    capability = "typology_cluster"

    def supports(self, sheet: object) -> bool:
        return False

    def extract(self, sheet: object, entities: list[object]) -> list[Measurement]:
        raise NotImplementedError(
            "TypologyClusterExtractor is not implemented -- see class docstring."
        )


def register_stubs() -> None:
    register(TypologyClusterExtractor())  # type: ignore[arg-type]


def register_geometry_extractors() -> None:
    """Registers every implemented extractor (Phase 2). Called alongside
    register_stubs() from geometry/__init__.py so importing the package is
    enough to populate the full registry."""
    for extractor in (
        AlignmentExtractor(),
        CorridorAreaExtractor(),
        TrenchPrismoidalVolumeExtractor(),
        PipeNetworkTopologyExtractor(),
    ):
        register(extractor)  # type: ignore[arg-type]


register_stubs()
register_geometry_extractors()
