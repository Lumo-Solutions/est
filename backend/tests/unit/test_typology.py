"""Module B Phase 4c: pure typology-detection logic. See
docs/module-b-phase4-plan.md §4c and app/takeoff/typology.py's module
docstring for the two detection strategies these exercise."""

from __future__ import annotations

from app.takeoff.geometry.entities import GeometricEntity
from app.takeoff.typology import (
    InstanceSignature,
    cluster_by_proximity,
    group_dxf_instances_by_block,
    group_pdf_regions_by_hash,
    normalized_geometry_hash,
    signature_from_entities,
    signatures_match,
)


def _rect(handle: str, x0: float, y0: float, w: float, h: float, *, layer: str = "0") -> GeometricEntity:
    return GeometricEntity(
        "lwpolyline", layer, handle,
        [(x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h)], closed=True,
    )


def _insert(handle: str, block_name: str, sig: InstanceSignature | None) -> GeometricEntity:
    attrs = {}
    if sig is not None:
        attrs = {
            "__sig_bbox_aspect_ratio": repr(sig.bbox_aspect_ratio),
            "__sig_entity_count": str(sig.entity_count),
            "__sig_total_edge_length": repr(sig.total_edge_length),
        }
    return GeometricEntity("insert_node", "0", handle, [(0.0, 0.0)], block_name=block_name, attributes=attrs)


# --------------------------------------------------------------------------
# signature / tolerance matching
# --------------------------------------------------------------------------


def test_signature_from_entities_computes_aspect_ratio_count_and_length():
    rect = _rect("r1", 0, 0, 10, 5)  # perimeter 30, bbox 10x5 -> aspect 2.0
    sig = signature_from_entities([rect])
    assert sig.entity_count == 1
    assert sig.bbox_aspect_ratio == 2.0
    assert sig.total_edge_length == 30.0


def test_signatures_match_within_tolerance_and_rejects_outside_it():
    a = InstanceSignature(bbox_aspect_ratio=2.0, entity_count=1, total_edge_length=30.0)
    close = InstanceSignature(bbox_aspect_ratio=2.01, entity_count=1, total_edge_length=30.3)
    far = InstanceSignature(bbox_aspect_ratio=3.0, entity_count=1, total_edge_length=30.0)
    assert signatures_match(a, close, tolerance_pct=2.0)
    assert not signatures_match(a, far, tolerance_pct=2.0)


def test_signatures_match_requires_exact_entity_count():
    a = InstanceSignature(bbox_aspect_ratio=1.0, entity_count=3, total_edge_length=10.0)
    b = InstanceSignature(bbox_aspect_ratio=1.0, entity_count=4, total_edge_length=10.0)
    assert not signatures_match(a, b, tolerance_pct=50.0)


# --------------------------------------------------------------------------
# DXF: block_name + signature-tolerance grouping
# --------------------------------------------------------------------------


def test_group_dxf_instances_groups_same_block_matching_signature():
    sig = InstanceSignature(bbox_aspect_ratio=2.0, entity_count=4, total_edge_length=30.0)
    entities = [_insert("i1", "VILLA_A", sig), _insert("i2", "VILLA_A", sig), _insert("i3", "VILLA_A", sig)]
    groups = group_dxf_instances_by_block(entities, tolerance_pct=2.0)
    assert len(groups) == 1
    assert groups[0].key == "VILLA_A"
    assert {e.handle for e in groups[0].entities} == {"i1", "i2", "i3"}


def test_group_dxf_instances_splits_signature_outlier_into_its_own_group():
    master_sig = InstanceSignature(bbox_aspect_ratio=2.0, entity_count=4, total_edge_length=30.0)
    outlier_sig = InstanceSignature(bbox_aspect_ratio=5.0, entity_count=4, total_edge_length=30.0)  # same block_name, very different shape
    entities = [
        _insert("i1", "VILLA_A", master_sig), _insert("i2", "VILLA_A", master_sig),
        _insert("i3", "VILLA_A", outlier_sig), _insert("i4", "VILLA_A", outlier_sig),
    ]
    groups = group_dxf_instances_by_block(entities, tolerance_pct=2.0)
    keys = {g.key for g in groups}
    assert "VILLA_A" in keys
    assert any(k.startswith("VILLA_A#outlier-") for k in keys)
    master_group = next(g for g in groups if g.key == "VILLA_A")
    outlier_group = next(g for g in groups if g.key != "VILLA_A")
    assert {e.handle for e in master_group.entities} == {"i1", "i2"}
    assert {e.handle for e in outlier_group.entities} == {"i3", "i4"}


def test_group_dxf_instances_excludes_lone_instances_and_missing_signatures():
    sig = InstanceSignature(bbox_aspect_ratio=1.0, entity_count=1, total_edge_length=5.0)
    entities = [
        _insert("lone", "SOLO_BLOCK", sig),  # only one instance of this block -- not a repeating typology
        _insert("no_sig", "UNRESOLVED_BLOCK", None),  # signature couldn't be computed (e.g. unresolvable XREF)
        _insert("no_sig2", "UNRESOLVED_BLOCK", None),
    ]
    groups = group_dxf_instances_by_block(entities, tolerance_pct=2.0)
    assert groups == []


# --------------------------------------------------------------------------
# PDF: proximity clustering + normalised geometry hash
# --------------------------------------------------------------------------


def test_cluster_by_proximity_groups_touching_entities_and_separates_distant_ones():
    near_a = _rect("a", 0, 0, 10, 10)
    near_b = _rect("b", 10.5, 0, 10, 10)  # 0.5 gap from `near_a`
    far = _rect("c", 1000, 1000, 10, 10)
    regions = cluster_by_proximity([near_a, near_b, far], gap_tolerance=1.0)
    region_handle_sets = [{e.handle for e in r} for r in regions]
    assert {"a", "b"} in region_handle_sets
    assert {"c"} in region_handle_sets
    assert len(regions) == 2


def test_normalized_geometry_hash_is_translation_invariant_but_shape_sensitive():
    square = [_rect("s1", 0, 0, 10, 10)]
    same_square_translated = [_rect("s2", 500, 500, 10, 10)]
    different_rect = [_rect("r1", 0, 0, 10, 20)]

    h1 = normalized_geometry_hash(square)
    h2 = normalized_geometry_hash(same_square_translated)
    h3 = normalized_geometry_hash(different_rect)
    assert h1 is not None and h2 is not None
    assert h1 == h2
    assert h1 != h3


def test_normalized_geometry_hash_distinguishes_similar_shapes_at_different_scale():
    """Regression: rounding vertices against a grid proportional to the
    region's OWN diagonal is, on its own, scale-invariant by construction
    (for any two similar shapes, corner/grid reduces to the same constant
    regardless of absolute size) -- a 10x10 and a 6x6 square hashed
    identically before the log-scale bucket was added to break that
    self-cancellation."""
    big_square = [_rect("big", 0, 0, 10, 10)]
    small_square = [_rect("small", 0, 0, 6, 6)]
    assert normalized_geometry_hash(big_square) != normalized_geometry_hash(small_square)


def test_normalized_geometry_hash_none_for_degenerate_region():
    point = [GeometricEntity("line", "0", "p1", [(5.0, 5.0), (5.0, 5.0)])]
    assert normalized_geometry_hash(point) is None


def test_group_pdf_regions_by_hash_matches_across_sheets_and_excludes_lone_regions():
    sheet_1_entities = [_rect("s1a", 0, 0, 10, 10), _rect("s1b", 500, 500, 6, 6)]  # two separate regions on sheet 1
    sheet_2_entities = [_rect("s2a", 100, 100, 10, 10)]  # same shape as s1a, translated, on a different sheet
    groups = group_pdf_regions_by_hash(
        {"sheet-1": sheet_1_entities, "sheet-2": sheet_2_entities}, proximity_gap=1.0, grid_tolerance_pct=5.0
    )
    assert len(groups) == 1
    matched_handles = {e.handle for region in groups[0].regions for e in region}
    assert matched_handles == {"s1a", "s2a"}  # s1b (a different, lone shape) never appears
