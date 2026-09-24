from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.takeoff.geometry.entities import GeometricEntity
from app.takeoff.geometry.pipe_network import PipeNetworkTopologyExtractor


def _sheet(units: str = "m") -> SimpleNamespace:
    return SimpleNamespace(units=units)


def _manhole(handle: str, position: tuple[float, float]) -> GeometricEntity:
    return GeometricEntity("insert_node", "UTIL-STRUCT", handle, [position], block_name="MH-STD")


def _pipe(handle: str, start: tuple[float, float], end: tuple[float, float], attributes: dict[str, str] | None = None) -> GeometricEntity:
    return GeometricEntity("lwpolyline", "SEWER-PIPE", handle, [start, end], attributes=attributes or {})


def test_pipe_run_between_two_manholes_10m() -> None:
    # Two manholes 10m apart, one straight pipe run connecting them exactly
    # -- pipe length = 10.0 m, network total = 10.0 m, 2 nodes, 1 edge.
    mh1 = _manhole("N1", (0.0, 0.0))
    mh2 = _manhole("N2", (0.0, 10.0))
    pipe = _pipe("P1", (0.0, 0.0), (0.0, 10.0), attributes={"DIAMETER": "300", "MATERIAL": "PVC"})

    measurements = PipeNetworkTopologyExtractor().extract(_sheet("m"), [mh1, mh2, pipe])

    run = next(m for m in measurements if m.kind == "pipe_run_length_m")
    assert run.value == pytest.approx(10.0)
    assert run.metadata["from_node"] == "N1"
    assert run.metadata["to_node"] == "N2"
    assert run.metadata["diameter"] == "300"
    assert run.metadata["material"] == "PVC"

    total = next(m for m in measurements if m.kind == "pipe_network_total_length_m")
    assert total.value == pytest.approx(10.0)
    assert total.metadata == {"node_count": 2, "edge_count": 1}


def test_pipe_run_bent_polyline_sums_segments() -> None:
    # An L-shaped pipe run: (0,0)->(6,0) [6m] then (6,0)->(6,8) [8m] ->
    # total length 14.0 m (not the 10.0 m straight-line distance between
    # its endpoints).
    mh1 = _manhole("N1", (0.0, 0.0))
    mh2 = _manhole("N2", (6.0, 8.0))
    pipe = _pipe("P1", (0.0, 0.0), (6.0, 0.0))
    pipe.vertices = [(0.0, 0.0), (6.0, 0.0), (6.0, 8.0)]

    measurements = PipeNetworkTopologyExtractor().extract(_sheet("m"), [mh1, mh2, pipe])
    run = next(m for m in measurements if m.kind == "pipe_run_length_m")
    assert run.value == pytest.approx(14.0)


def test_pipe_endpoint_within_tolerance_still_snaps() -> None:
    # Manhole at (0,0); pipe actually starts at (0.4, 0.0) -- drawn to the
    # manhole's rim, not its exact centre. Default snap tolerance is 1.0 m,
    # so this must still resolve to the manhole, not a dangling end.
    mh = _manhole("N1", (0.0, 0.0))
    pipe = _pipe("P1", (0.4, 0.0), (0.4, 10.0))
    measurements = PipeNetworkTopologyExtractor().extract(_sheet("m"), [mh, pipe])
    run = next(m for m in measurements if m.kind == "pipe_run_length_m")
    assert run.metadata["from_node"] == "N1"


def test_pipe_dangling_end_beyond_tolerance_has_no_node() -> None:
    # Nearest manhole is 50 m from the pipe's far end -- well beyond the
    # 1.0 m default tolerance -- so that end must be reported as unconnected
    # rather than snapped to the wrong node.
    mh1 = _manhole("N1", (0.0, 0.0))
    mh2 = _manhole("N2", (0.0, 60.0))
    pipe = _pipe("P1", (0.0, 0.0), (0.0, 10.0))
    measurements = PipeNetworkTopologyExtractor().extract(_sheet("m"), [mh1, mh2, pipe])
    run = next(m for m in measurements if m.kind == "pipe_run_length_m")
    assert run.metadata["from_node"] == "N1"
    assert run.metadata["to_node"] is None


def test_no_pipes_produces_no_measurements() -> None:
    mh = _manhole("N1", (0.0, 0.0))
    assert PipeNetworkTopologyExtractor().extract(_sheet("m"), [mh]) == []


def test_ignores_insert_nodes_not_matching_node_block_hints() -> None:
    not_a_manhole = GeometricEntity("insert_node", "FURNITURE", "F1", [(0.0, 0.0)], block_name="DESK")
    pipe = _pipe("P1", (0.0, 0.0), (0.0, 10.0))
    measurements = PipeNetworkTopologyExtractor().extract(_sheet("m"), [not_a_manhole, pipe])
    run = next(m for m in measurements if m.kind == "pipe_run_length_m")
    assert run.metadata["from_node"] is None
    assert run.metadata["to_node"] is None


def test_pipe_ambiguous_node_match_is_flagged_not_picked_silently() -> None:
    # Two manholes near the same pipe end: N1 at 0.2m away, N2 at 0.5m away
    # -- both within the default 1.0m tolerance. The nearest (N1) is still
    # reported as the best guess, but the match must be flagged ambiguous
    # with both candidates recorded, and confidence must drop (halved from
    # the un-ambiguous base of 0.7 to 0.35) -- never a silent pick.
    n1 = _manhole("N1", (0.0, 0.2))
    n2 = _manhole("N2", (0.0, 0.5))
    far_node = _manhole("N3", (0.0, 10.0))  # unambiguous match for the other end
    pipe = _pipe("P1", (0.0, 0.0), (0.0, 10.0))

    measurements = PipeNetworkTopologyExtractor().extract(_sheet("m"), [n1, n2, far_node, pipe])
    run = next(m for m in measurements if m.kind == "pipe_run_length_m")

    assert run.metadata["from_node"] == "N1"
    assert run.metadata["from_node_ambiguous"] is True
    assert run.metadata["from_node_candidates"] == ["N1", "N2"]
    assert "to_node_ambiguous" not in run.metadata
    assert run.confidence == pytest.approx(0.35)


def test_pipe_unambiguous_match_has_no_ambiguity_metadata() -> None:
    mh1 = _manhole("N1", (0.0, 0.0))
    mh2 = _manhole("N2", (0.0, 10.0))
    pipe = _pipe("P1", (0.0, 0.0), (0.0, 10.0))
    measurements = PipeNetworkTopologyExtractor().extract(_sheet("m"), [mh1, mh2, pipe])
    run = next(m for m in measurements if m.kind == "pipe_run_length_m")
    assert "from_node_ambiguous" not in run.metadata
    assert "to_node_ambiguous" not in run.metadata
    assert run.confidence == pytest.approx(0.7)
