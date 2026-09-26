from __future__ import annotations

import io
from dataclasses import dataclass, field

import ezdxf

from app.takeoff.geometry.entities import GeometricEntity

# ezdxf $INSUNITS codes -> human-readable unit names
_INSUNITS = {
    0: "unitless", 1: "in", 2: "ft", 4: "mm", 5: "cm", 6: "m",
    9: "us_survey_ft", 14: "dm",
}

_TITLE_BLOCK_NAME_HINTS = ("TITLE", "TB", "SHEET", "TITLEBLOCK")


def _read_dxf_document(data: bytes):
    """Decodes and parses raw DXF bytes into an ezdxf document.

    Must go through `io.TextIOWrapper(..., newline=None)` (universal
    newlines), NOT `io.StringIO(data.decode(...))` -- a real DXF file is
    CRLF-terminated (confirmed against ezdxf's own writer output on disk),
    and `ezdxf.read()` expects `readline()` to hand back lines with the
    line terminator already stripped the way a real text-mode file does.
    Feeding it a StringIO wrapping an already-decoded string leaves each
    line's trailing "\\r" attached (StringIO only special-cases "\\n"), which
    silently corrupts DXF's line-based group-code/value parsing -- ezdxf
    doesn't raise, it just returns a near-empty document (entitydb an order
    of magnitude smaller than the real file, modelspace entity count 0).
    Caught by feeding this a real saved-to-disk DXF file (CRLF) end-to-end
    through the actual ingestion pipeline; every unit test fixture up to
    that point built its DXF bytes via `doc.write(io.StringIO())`, which
    never produces CRLF in the first place and so never exercised this."""
    return ezdxf.read(io.TextIOWrapper(io.BytesIO(data), encoding="utf-8", errors="replace", newline=None))


@dataclass(slots=True)
class DxfTextEntity:
    entity_type: str  # text | mtext | attrib
    layer: str | None
    block_name: str | None
    text_value: str
    bbox: tuple[float, float, float, float] | None
    handle: str | None


@dataclass(slots=True)
class DxfLayoutInfo:
    layout_name: str
    units: str
    layer_names: list[str] = field(default_factory=list)
    text_entities: list[DxfTextEntity] = field(default_factory=list)
    title_block_candidate_text: str = ""


def index_dxf(data: bytes) -> list[DxfLayoutInfo]:
    """Harvests modelspace + paperspace layouts: $INSUNITS, layer names, and
    TEXT/MTEXT/ATTRIB entities (geometric entities -- LINE, LWPOLYLINE, etc.
    -- are intentionally not walked here; see takeoff/geometry/ for that
    extension point, gated behind TAKEOFF_PERSIST_GEOMETRY)."""
    doc = _read_dxf_document(data)
    insunits = doc.header.get("$INSUNITS", 0)
    units = _INSUNITS.get(insunits, "unitless")
    layer_names = [layer.dxf.name for layer in doc.layers]

    layouts: list[DxfLayoutInfo] = []
    for layout in doc.layouts:
        info = DxfLayoutInfo(layout_name=layout.name, units=units, layer_names=layer_names)
        title_block_fragments: list[str] = []

        for entity in layout:
            dxftype = entity.dxftype()
            if dxftype == "TEXT":
                value = entity.dxf.text
                bbox = None
                try:
                    x, y, *_ = entity.dxf.insert
                    bbox = (x, y, x, y)
                except Exception:  # noqa: BLE001
                    pass
                info.text_entities.append(
                    DxfTextEntity("text", entity.dxf.layer, None, value, bbox, entity.dxf.handle)
                )
            elif dxftype == "MTEXT":
                value = entity.plain_text() if hasattr(entity, "plain_text") else entity.text
                info.text_entities.append(
                    DxfTextEntity("mtext", entity.dxf.layer, None, value, None, entity.dxf.handle)
                )
            elif dxftype == "INSERT":
                block_name = entity.dxf.name
                is_title_block_candidate = any(h in block_name.upper() for h in _TITLE_BLOCK_NAME_HINTS)
                for attrib in getattr(entity, "attribs", []):
                    info.text_entities.append(
                        DxfTextEntity(
                            "attrib", attrib.dxf.layer, block_name, attrib.dxf.text, None, attrib.dxf.handle
                        )
                    )
                    if is_title_block_candidate:
                        title_block_fragments.append(f"{attrib.dxf.tag}: {attrib.dxf.text}")
            elif dxftype == "DIMENSION":
                try:
                    value = entity.dxf.text or ""
                except Exception:  # noqa: BLE001
                    value = ""
                if value:
                    info.text_entities.append(
                        DxfTextEntity("dimension", entity.dxf.layer, None, value, None, entity.dxf.handle)
                    )

        info.title_block_candidate_text = "\n".join(title_block_fragments)
        layouts.append(info)

    return layouts


def _convert_geometric_entity(entity, handle: str | None) -> GeometricEntity | None:
    """Shared by index_dxf_geometry()'s main per-layout loop and its INSERT
    branch's block-content walk below (Module B Phase 4c) -- same LINE/
    LWPOLYLINE/POLYLINE/ARC handling either way, just fed a different
    entity source (the real layout vs. one INSERT's virtual_entities()).
    `handle` is None for a virtual entity (ezdxf: "these entities ... have
    no handle") -- fine here since virtual entities are only ever used to
    compute a signature, never persisted as their own DrawingEntity row."""
    dxftype = entity.dxftype()
    if dxftype == "LINE":
        start = (entity.dxf.start.x, entity.dxf.start.y)
        end = (entity.dxf.end.x, entity.dxf.end.y)
        return GeometricEntity("line", entity.dxf.layer, handle, [start, end])
    if dxftype == "LWPOLYLINE":
        points = [(float(p[0]), float(p[1]), float(p[2])) for p in entity.get_points("xyb")]
        verts = [(x, y) for x, y, _ in points]
        bulges = [b for _, _, b in points]
        if len(verts) >= 2:
            return GeometricEntity("lwpolyline", entity.dxf.layer, handle, verts, closed=bool(entity.closed), bulges=bulges)
        return None
    if dxftype == "POLYLINE":
        verts = [(v.dxf.location.x, v.dxf.location.y) for v in entity.vertices]
        bulges = [float(getattr(v.dxf, "bulge", 0.0)) for v in entity.vertices]
        if len(verts) >= 2:
            return GeometricEntity("lwpolyline", entity.dxf.layer, handle, verts, closed=bool(entity.is_closed), bulges=bulges)
        return None
    if dxftype == "ARC":
        center = (entity.dxf.center.x, entity.dxf.center.y)
        return GeometricEntity(
            "arc", entity.dxf.layer, handle, [], center=center, radius=entity.dxf.radius,
            start_angle_deg=entity.dxf.start_angle, end_angle_deg=entity.dxf.end_angle,
        )
    if dxftype == "CIRCLE":
        center = (entity.dxf.center.x, entity.dxf.center.y)
        return GeometricEntity(
            "arc", entity.dxf.layer, handle, [], center=center, radius=entity.dxf.radius,
            start_angle_deg=0.0, end_angle_deg=360.0,
        )
    return None


def _block_signature_attributes(block_name: str, doc) -> dict[str, str]:
    """Module B Phase 4c: computed from the block DEFINITION's own local
    (untransformed) geometry -- doc.blocks[block_name] -- not from any one
    INSERT's placed/rotated/scaled content. Deliberately not using ezdxf's
    Insert.virtual_entities() (the per-instance, world-transformed
    content): a bounding-box aspect ratio computed from *rotated* geometry
    is not rotation-invariant (a 10x5 rectangle rotated 90 degrees has a
    5x10 axis-aligned bbox), which would wrongly split two placements of
    the identical block at different rotations into separate typology
    groups -- the plan doc's own "differing only by placement (position/
    rotation) still match" requirement. Computing from the block's own
    local frame instead sidesteps that entirely: every instance sharing a
    block_name gets the identical signature regardless of its own
    placement, by construction (this does mean a *non-uniformly-scaled*
    instance of the same block_name is no longer caught as a signature
    outlier -- an accepted simplification for a first bounded
    implementation; block_name-across-different-uploaded-drawings name
    collisions are still caught, since ezdxf itself disallows duplicate
    block names within one document, so a same-name-different-geometry
    conflict can only arise from two separate files). Only LINE/
    LWPOLYLINE/POLYLINE/ARC/CIRCLE sub-entities contribute (matching
    _convert_geometric_entity's own coverage). Returns {} (no signature --
    app.takeoff.typology::group_dxf_instances_by_block skips these) for a
    block with no convertible content (e.g. purely text/attribute
    definitions) or an unresolvable name."""
    from app.takeoff.typology import signature_from_entities

    try:
        block = doc.blocks[block_name]
    except KeyError:
        return {}
    sub_entities = [g for e in block if (g := _convert_geometric_entity(e, None)) is not None]
    if not sub_entities:
        return {}
    sig = signature_from_entities(sub_entities)
    return {
        "__sig_bbox_aspect_ratio": repr(sig.bbox_aspect_ratio),
        "__sig_entity_count": str(sig.entity_count),
        "__sig_total_edge_length": repr(sig.total_edge_length),
    }


def index_dxf_geometry(data: bytes) -> dict[str, list[GeometricEntity]]:
    """Harvests LINE, LWPOLYLINE/POLYLINE, ARC, and INSERT (as a point node
    -- its insertion point plus any ATTRIB values, for manhole/chamber and
    trench-cross-section markers) per layout name, for the geometry
    extractors in app.takeoff.geometry. Companion to index_dxf(), which only
    harvests text-bearing entities; kept as a separate pass (re-reading the
    same ezdxf document) rather than merged into index_dxf() so the common,
    always-on text path never pays for parsing geometry it won't use.

    Callers decide whether to call this at all -- it has no opinion on
    TAKEOFF_PERSIST_GEOMETRY; see app.workers.tasks.takeoff.index_sheets.

    Planar assumption: only X/Y is read from any entity (see
    app.takeoff.geometry.entities module docstring) -- OCS/Z data on
    entities drawn outside the XY plane is ignored, which is fine for the
    plan-view civil drawings this targets but would misread a 3D model.
    """
    doc = _read_dxf_document(data)
    result: dict[str, list[GeometricEntity]] = {}
    # Signature computed once per distinct block_name (from the block
    # DEFINITION, not per placement) and reused for every INSERT
    # referencing it, across every layout -- see _block_signature_attributes.
    block_signature_cache: dict[str, dict[str, str]] = {}

    for layout in doc.layouts:
        geoms: list[GeometricEntity] = []
        for entity in layout:
            dxftype = entity.dxftype()
            if dxftype in ("LINE", "LWPOLYLINE", "POLYLINE", "ARC"):
                # get_points() (LWPOLYLINE) returns numpy floats internally --
                # _convert_geometric_entity casts to plain float so the
                # vertex list stays JSON-serializable for the geometry
                # JSONB column.
                converted = _convert_geometric_entity(entity, entity.dxf.handle)
                if converted is not None:
                    geoms.append(converted)
            elif dxftype == "INSERT":
                point = (entity.dxf.insert.x, entity.dxf.insert.y)
                attrs = {a.dxf.tag: a.dxf.text for a in getattr(entity, "attribs", [])}
                # Module B Phase 4c: the block's own geometric signature
                # (see _block_signature_attributes for why this is
                # computed from the block definition, not this instance's
                # own placement/rotation/scale).
                block_name = entity.dxf.name
                if block_name not in block_signature_cache:
                    block_signature_cache[block_name] = _block_signature_attributes(block_name, doc)
                attrs.update(block_signature_cache[block_name])
                geoms.append(
                    GeometricEntity(
                        "insert_node", entity.dxf.layer, entity.dxf.handle, [point],
                        block_name=entity.dxf.name, attributes=attrs,
                    )
                )
            elif dxftype == "DIMENSION":
                # Module B Phase 4a scale cross-check (see takeoff/scale.py::
                # dimension_cross_check_signals): only meaningful when the
                # drafter typed an explicit real-world length override --
                # the default "<>" auto-text's displayed value already
                # depends on the dimension style's own scale factor, which
                # is deliberately not resolved here (see scale.py's module
                # docstring). defpoint2/defpoint3 are the two points the
                # dimension actually measures between (linear/aligned
                # dimensions only -- other dimension subtypes don't define
                # them and are skipped, `getattr` default keeps this
                # tolerant of that).
                text = getattr(entity.dxf, "text", "") or ""
                p2 = getattr(entity.dxf, "defpoint2", None)
                p3 = getattr(entity.dxf, "defpoint3", None)
                if text and text != "<>" and p2 is not None and p3 is not None:
                    geoms.append(
                        GeometricEntity(
                            "dimension", entity.dxf.layer, entity.dxf.handle,
                            [(p2.x, p2.y), (p3.x, p3.y)], attributes={"stated_length": text},
                        )
                    )
        result[layout.name] = geoms

    return result


def derive_scale_from_units(units: str) -> tuple[float | None, float]:
    """Fallback scale signal when no title-block scale text is found:
    drawings modeled in real-world units (mm/m) at 1:1 in modelspace imply
    scale_ratio=1.0 with low confidence (paperspace viewport scale, not
    modeled here, is the authoritative source and takes precedence when
    present -- see takeoff/scale.py)."""
    if units in ("mm", "m", "cm", "dm"):
        return 1.0, 0.3
    return None, 0.0
