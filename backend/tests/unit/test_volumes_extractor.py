from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.takeoff.geometry.entities import GeometricEntity
from app.takeoff.geometry.volumes import TrenchPrismoidalVolumeExtractor


def _sheet(units: str = "m") -> SimpleNamespace:
    return SimpleNamespace(units=units)


def _marker(handle: str, station: float, width_top: float, width_bottom: float, depth: float, trench_id: str | None = None) -> GeometricEntity:
    attrs = {
        "STATION": str(station),
        "WIDTH_TOP": str(width_top),
        "WIDTH_BOTTOM": str(width_bottom),
        "DEPTH": str(depth),
    }
    if trench_id is not None:
        attrs["TRENCH_ID"] = trench_id
    return GeometricEntity("insert_node", "TRENCH-XSEC", handle, [(station, 0.0)], block_name="XSEC", attributes=attrs)


def test_trench_volume_three_evenly_spaced_sections_hand_worked() -> None:
    # Three cross-sections along one trench run, all in metres, 5m apart.
    # Volume is computed PER SEGMENT (station 0->5, then 5->10), each using
    # a midsection synthesized from AVERAGED DIMENSIONS of its own two real
    # endpoints -- not a single triad over the whole 0-10 run, and not an
    # average of the two end AREAS. See composite_trench_volume's docstring
    # for why (uneven spacing, covered in the next test, is the reason).
    #
    #   Section @0:  top=2.0, bottom=1.0, depth=1.5 -> A = 2.25 m^2
    #   Section @5:  top=2.4, bottom=1.2, depth=1.6 -> A = 2.88 m^2
    #   Section @10: top=2.0, bottom=1.0, depth=1.5 -> A = 2.25 m^2
    #
    #   Segment 1 (0->5, L=5): Am dims = (top=2.2, bottom=1.1, depth=1.55)
    #     -> Am = (2.2+1.1)/2*1.55 = 1.65*1.55 = 2.5575
    #     V1 = 5/6 * (2.25 + 4*2.5575 + 2.88) = 5/6 * 15.36 = 12.8
    #   Segment 2 (5->10, L=5): mirror of segment 1 by symmetry -> V2 = 12.8
    #
    #   Total = 12.8 + 12.8 = 25.6 m^3
    markers = [
        _marker("M1", 0.0, 2.0, 1.0, 1.5),
        _marker("M2", 5.0, 2.4, 1.2, 1.6),
        _marker("M3", 10.0, 2.0, 1.0, 1.5),
    ]
    measurements = TrenchPrismoidalVolumeExtractor().extract(_sheet("m"), markers)
    assert len(measurements) == 1
    m = measurements[0]
    assert m.kind == "trench_volume_m3"
    assert m.value == pytest.approx(25.6)
    assert m.unit == "m3"
    assert m.metadata == {"trench_id": "default", "section_count": 3}
    assert set(m.source_entity_ids) == {"M1", "M2", "M3"}


def test_trench_volume_uneven_spacing_hand_worked() -> None:
    # Stations 0, 3, 10 -- UNEVEN spacing (3m, then 7m). Per-segment
    # prismoidal handles this with no special-casing, unlike a composite
    # Simpson's-rule scheme over cross-section areas (only exact for
    # equal spacing) -- this is exactly why that approach was replaced.
    #
    #   Section @0:  top=2.0, bottom=1.0, depth=1.5 -> A = 2.25 m^2
    #   Section @3:  top=2.2, bottom=1.1, depth=1.5 -> A = (2.2+1.1)/2*1.5 = 2.475 m^2
    #   Section @10: top=2.0, bottom=1.0, depth=1.5 -> A = 2.25 m^2
    #
    #   Segment 1 (0->3, L=3): Am dims = (top=2.1, bottom=1.05, depth=1.5)
    #     -> Am = (2.1+1.05)/2*1.5 = 1.575*1.5 = 2.3625
    #     V1 = 3/6 * (2.25 + 4*2.3625 + 2.475) = 0.5 * 14.175 = 7.0875
    #   Segment 2 (3->10, L=7): Am dims identical by symmetry -> Am = 2.3625
    #     V2 = 7/6 * (2.475 + 4*2.3625 + 2.25) = 7/6 * 14.175 = 16.5375
    #
    #   Total = 7.0875 + 16.5375 = 23.625 m^3
    markers = [
        _marker("M1", 0.0, 2.0, 1.0, 1.5),
        _marker("M2", 3.0, 2.2, 1.1, 1.5),
        _marker("M3", 10.0, 2.0, 1.0, 1.5),
    ]
    measurements = TrenchPrismoidalVolumeExtractor().extract(_sheet("m"), markers)
    assert len(measurements) == 1
    assert measurements[0].value == pytest.approx(23.625)


def test_trench_volume_converts_millimeter_cross_sections() -> None:
    # Same three evenly-spaced sections as the hand-worked case above, but
    # every dimension (station, widths, depth) is drawn in millimetres
    # instead of metres: 1000x the native values. Volume scales by
    # (1/1000)^3 relative to the native-unit number, i.e. the same 25.6 m^3
    # result once converted.
    markers = [
        _marker("M1", 0.0, 2000.0, 1000.0, 1500.0),
        _marker("M2", 5000.0, 2400.0, 1200.0, 1600.0),
        _marker("M3", 10000.0, 2000.0, 1000.0, 1500.0),
    ]
    measurements = TrenchPrismoidalVolumeExtractor().extract(_sheet("mm"), markers)
    assert measurements[0].value == pytest.approx(25.6, abs=1e-3)


def test_trench_volume_separates_by_trench_id() -> None:
    # Two independent trench runs on the same sheet, each with only 2
    # sections -> average-end-area method per run.
    # Run "A": stations 0 and 10, areas both (1+1)/2*1 = 1.0 m^2 (rectangular,
    # top=bottom=1.0, depth=1.0) -> volume = 10 * (1.0+1.0)/2 = 10.0 m^3.
    # Run "B": stations 0 and 4, areas both 2.0 m^2 (top=bottom=2.0, depth=1.0)
    # -> volume = 4 * (2.0+2.0)/2 = 8.0 m^3.
    markers = [
        _marker("A1", 0.0, 1.0, 1.0, 1.0, trench_id="A"),
        _marker("A2", 10.0, 1.0, 1.0, 1.0, trench_id="A"),
        _marker("B1", 0.0, 2.0, 2.0, 1.0, trench_id="B"),
        _marker("B2", 4.0, 2.0, 2.0, 1.0, trench_id="B"),
    ]
    measurements = TrenchPrismoidalVolumeExtractor().extract(_sheet("m"), markers)
    by_trench = {m.metadata["trench_id"]: m.value for m in measurements}
    assert by_trench == {"A": pytest.approx(10.0), "B": pytest.approx(8.0)}


def test_trench_volume_skips_markers_with_missing_attributes() -> None:
    good = _marker("M1", 0.0, 2.0, 1.0, 1.5)
    bad = GeometricEntity("insert_node", "TRENCH-XSEC", "M2", [(5.0, 0.0)], block_name="XSEC", attributes={"STATION": "5.0"})
    # Only one usable section remains -> not enough to compute a volume.
    assert TrenchPrismoidalVolumeExtractor().extract(_sheet("m"), [good, bad]) == []


def test_trench_volume_ignores_non_matching_layers() -> None:
    marker = _marker("M1", 0.0, 2.0, 1.0, 1.5)
    marker.layer = "A-ANNOTATION"
    assert TrenchPrismoidalVolumeExtractor().extract(_sheet("m"), [marker]) == []
