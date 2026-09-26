"""Module B Phase 4c: clustered typology recognition -- pure detection
logic (no DB/session types here, same separation as app/boq/
reconciliation.py). Two independent detection strategies, per
docs/module-b-phase4-plan.md §4c:

- DXF: instances of the same block reference are trivially "the same
  unit" regardless of placement/rotation (that's what a block reference
  IS) -- group by GeometricEntity.block_name directly. The geometric
  signature (bbox aspect ratio, entity count, total edge length -- see
  InstanceSignature, computed once per block_name by app.takeoff.dxf::
  index_dxf_geometry from the block DEFINITION's own local geometry, not
  any one instance's placed/rotated/scaled content -- deliberately
  rotation-invariant this way, see that function's docstring) is a
  cross-drawing consistency check, not the primary key: within one DXF
  document every instance of a block_name is, by construction, identical;
  the same block_name defined with genuinely different geometry in a
  *different* uploaded drawing (block names are only unique within one
  DXF document) is split into its own outlier group rather than silently
  folded in or silently dropped.
- PDF: no block references exist at all, so grouping is by a normalised
  geometry hash instead: entities are first clustered into spatially
  separate "regions" by bbox proximity (cluster_by_proximity), then each
  region's own vertices are translated so its centroid is the origin,
  rounded to a tolerance grid sized as a percentage of the region's own
  bounding-box diagonal (self-scaling -- a 5% grid means something very
  different for a 2m unit than a 200m site), and hashed. Regions across
  the whole project whose hashes match become one cluster's instances.
  Translation-only, deliberately NOT rotation-invariant (matches the plan
  doc's literal scope) -- two PDF-drawn copies of the same unit rotated
  differently from each other will hash differently and will NOT be
  detected as the same cluster; only translated (and, since Y is never
  mirrored, non-reflected) copies match. Real rotation-invariant hashing
  (PCA alignment or a rotation search) is a materially harder problem,
  explicitly out of scope for this bounded first implementation.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

from app.takeoff.geometry.entities import GeometricEntity, Point


@dataclass(frozen=True, slots=True)
class InstanceSignature:
    bbox_aspect_ratio: float  # width / height of the instance's own bounding box; 0.0 when degenerate (no extent)
    entity_count: int
    total_edge_length: float


def _entity_bbox(e: GeometricEntity) -> tuple[float, float, float, float] | None:
    points: list[Point] = list(e.vertices)
    if e.center is not None and e.radius is not None:
        cx, cy = e.center
        points.extend([(cx - e.radius, cy - e.radius), (cx + e.radius, cy + e.radius)])
    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def union_bbox(entities: list[GeometricEntity]) -> tuple[float, float, float, float] | None:
    boxes = [b for e in entities if (b := _entity_bbox(e)) is not None]
    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def signature_from_entities(entities: list[GeometricEntity]) -> InstanceSignature:
    """Computed once (DXF: from a block's virtual_entities() content;
    PDF: from one detected region's own entities) and compared with a
    tolerance band, never recomputed on the fly per comparison."""
    from app.takeoff.geometry.geometry_math import entity_length

    bbox = union_bbox(entities)
    if bbox is None:
        aspect_ratio = 0.0
    else:
        width, height = bbox[2] - bbox[0], bbox[3] - bbox[1]
        aspect_ratio = (width / height) if height > 0 else 0.0
    total_length = sum(entity_length(e) for e in entities)
    return InstanceSignature(bbox_aspect_ratio=aspect_ratio, entity_count=len(entities), total_edge_length=total_length)


def signatures_match(a: InstanceSignature, b: InstanceSignature, tolerance_pct: float) -> bool:
    """Within `tolerance_pct` on both continuous fields; entity_count must
    match exactly (a count isn't a "close enough" quantity)."""
    if a.entity_count != b.entity_count:
        return False

    def _within(x: float, y: float) -> bool:
        if x == 0.0 and y == 0.0:
            return True
        base = max(abs(x), abs(y))
        return abs(x - y) <= base * (tolerance_pct / 100.0)

    return _within(a.bbox_aspect_ratio, b.bbox_aspect_ratio) and _within(a.total_edge_length, b.total_edge_length)


@dataclass(frozen=True, slots=True)
class DxfInstanceGroup:
    key: str  # block_name, or "{block_name}#outlier-{n}" for a signature outlier
    # The actual matched insert_node GeometricEntity objects (same Python
    # objects the caller passed in, by reference) -- not just their handle
    # strings, since a bare handle isn't safely unique across more than
    # one Drawing/DrawingSheet in a project (ezdxf allocates handles per
    # document); the caller resolves each back to its own (sheet_id,
    # DrawingEntity row) via object identity, same as PdfRegionGroup.regions.
    entities: list[GeometricEntity]


def group_dxf_instances_by_block(
    insert_entities: list[GeometricEntity], tolerance_pct: float = 2.0
) -> list[DxfInstanceGroup]:
    """`insert_entities` are entity_type == "insert_node" rows (across
    however many sheets the caller already gathered) whose `attributes`
    dict carries the stringified signature app.takeoff.dxf::
    index_dxf_geometry computed (see that module's INSERT branch) --
    entities missing a usable signature (couldn't resolve the block
    definition, e.g. an XREF) are skipped entirely, never guessed at.
    Only groups with 2+ surviving instances are returned -- a lone
    instance isn't a "repeating typology" yet."""
    by_block: dict[str, list[tuple[GeometricEntity, InstanceSignature]]] = {}
    for e in insert_entities:
        if e.entity_type != "insert_node" or not e.block_name or not e.handle:
            continue
        sig = _signature_from_attributes(e.attributes)
        if sig is None:
            continue
        by_block.setdefault(e.block_name, []).append((e, sig))

    groups: list[DxfInstanceGroup] = []
    for block_name, entries in by_block.items():
        # Greedily bucket by signature match against each bucket's first
        # member -- same "first match wins, never guess" convention as
        # the rest of this package's layer-hint matching.
        buckets: list[list[tuple[GeometricEntity, InstanceSignature]]] = []
        for entry in entries:
            _, sig = entry
            placed = False
            for bucket in buckets:
                if signatures_match(bucket[0][1], sig, tolerance_pct):
                    bucket.append(entry)
                    placed = True
                    break
            if not placed:
                buckets.append([entry])
        buckets.sort(key=len, reverse=True)
        for i, bucket in enumerate(buckets):
            if len(bucket) < 2:
                continue
            key = block_name if i == 0 else f"{block_name}#outlier-{i}"
            groups.append(DxfInstanceGroup(key=key, entities=[e for e, _ in bucket]))
    return groups


def _signature_from_attributes(attributes: dict[str, str]) -> InstanceSignature | None:
    try:
        return InstanceSignature(
            bbox_aspect_ratio=float(attributes["__sig_bbox_aspect_ratio"]),
            entity_count=int(attributes["__sig_entity_count"]),
            total_edge_length=float(attributes["__sig_total_edge_length"]),
        )
    except (KeyError, ValueError):
        return None


# --------------------------------------------------------------------------
# PDF: spatial region clustering + normalised geometry hash
# --------------------------------------------------------------------------


def cluster_by_proximity(entities: list[GeometricEntity], gap_tolerance: float) -> list[list[GeometricEntity]]:
    """Union-find over entity bounding boxes: two entities are in the same
    region if their (gap_tolerance-expanded) bboxes overlap. Entities with
    no computable bbox (arcs with no center/radius, degenerate) are each
    their own singleton region."""
    n = len(entities)
    boxes = [_entity_bbox(e) for e in entities]
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    for i in range(n):
        if boxes[i] is None:
            continue
        for j in range(i + 1, n):
            if boxes[j] is None:
                continue
            bi, bj = boxes[i], boxes[j]
            if (
                bi[0] - gap_tolerance <= bj[2] and bj[0] - gap_tolerance <= bi[2]
                and bi[1] - gap_tolerance <= bj[3] and bj[1] - gap_tolerance <= bi[3]
            ):
                union(i, j)

    regions: dict[int, list[GeometricEntity]] = {}
    for i, e in enumerate(entities):
        regions.setdefault(find(i), []).append(e)
    return list(regions.values())


def normalized_geometry_hash(region: list[GeometricEntity], grid_tolerance_pct: float = 5.0) -> str | None:
    """None when the region has no computable extent (nothing to hash) --
    never a placeholder/degenerate hash that could accidentally collide
    with a real one."""
    bbox = union_bbox(region)
    if bbox is None:
        return None
    cx, cy = (bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0
    diagonal = ((bbox[2] - bbox[0]) ** 2 + (bbox[3] - bbox[1]) ** 2) ** 0.5
    if diagonal == 0.0:
        return None
    grid = diagonal * (grid_tolerance_pct / 100.0)

    def _round(v: float) -> int:
        return round(v / grid)

    vertex_cells: list[tuple[int, int]] = []
    arc_signatures: list[tuple[int, int, int]] = []
    type_counts: dict[str, int] = {}
    for e in region:
        type_counts[e.entity_type] = type_counts.get(e.entity_type, 0) + 1
        for x, y in e.vertices:
            vertex_cells.append((_round(x - cx), _round(y - cy)))
        if e.center is not None and e.radius is not None:
            arc_signatures.append((_round(e.center[0] - cx), _round(e.center[1] - cy), _round(e.radius)))

    # Rounding vertices against a grid proportional to THIS region's own
    # diagonal is, by construction, scale-invariant on its own (for any
    # two similar shapes, corner/grid works out to the same constant
    # regardless of absolute size -- verified against a real false-match
    # this caught: a 10x10 and a 6x6 square hashed identically before this
    # was added). A log-scale bucket of the diagonal itself breaks that
    # self-cancellation: two regions within grid_tolerance_pct% of each
    # other's absolute size still land in the same (or an adjacent-then-
    # rounded-to-equal) bucket, but genuinely different sizes don't,
    # without needing any external/fixed reference scale.
    scale_bucket = round(math.log(diagonal) / math.log1p(grid_tolerance_pct / 100.0))

    payload = repr((scale_bucket, sorted(vertex_cells), sorted(arc_signatures), sorted(type_counts.items())))
    return hashlib.sha256(payload.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class PdfRegionGroup:
    key: str  # the geometry hash
    regions: list[list[GeometricEntity]]  # each element is one detected region's entity list


def group_pdf_regions_by_hash(
    entities_by_sheet: dict[object, list[GeometricEntity]], *, proximity_gap: float, grid_tolerance_pct: float = 5.0
) -> list[PdfRegionGroup]:
    """`entities_by_sheet` keys by whatever the caller uses to identify a
    sheet (a UUID, typically) -- proximity clustering (cluster_by_proximity)
    runs separately PER SHEET, since two different sheets/pages have
    independent coordinate spaces and could coincidentally overlap in
    raw coordinates; only the resulting regions' *hashes* are compared
    across sheets. Only groups with 2+ regions are returned -- a lone
    region isn't a repeating typology yet, same convention as
    group_dxf_instances_by_block."""
    regions: list[list[GeometricEntity]] = []
    for sheet_entities in entities_by_sheet.values():
        regions.extend(cluster_by_proximity(sheet_entities, proximity_gap))
    by_hash: dict[str, list[list[GeometricEntity]]] = {}
    for region in regions:
        h = normalized_geometry_hash(region, grid_tolerance_pct)
        if h is None:
            continue
        by_hash.setdefault(h, []).append(region)
    return [PdfRegionGroup(key=h, regions=rs) for h, rs in by_hash.items() if len(rs) >= 2]
