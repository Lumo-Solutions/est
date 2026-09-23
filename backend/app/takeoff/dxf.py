from __future__ import annotations

import io
from dataclasses import dataclass, field

import ezdxf

# ezdxf $INSUNITS codes -> human-readable unit names
_INSUNITS = {
    0: "unitless", 1: "in", 2: "ft", 4: "mm", 5: "cm", 6: "m",
    9: "us_survey_ft", 14: "dm",
}

_TITLE_BLOCK_NAME_HINTS = ("TITLE", "TB", "SHEET", "TITLEBLOCK")


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
    doc = ezdxf.read(io.StringIO(data.decode("utf-8", errors="replace")))
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


def derive_scale_from_units(units: str) -> tuple[float | None, float]:
    """Fallback scale signal when no title-block scale text is found:
    drawings modeled in real-world units (mm/m) at 1:1 in modelspace imply
    scale_ratio=1.0 with low confidence (paperspace viewport scale, not
    modeled here, is the authoritative source and takes precedence when
    present -- see takeoff/scale.py)."""
    if units in ("mm", "m", "cm", "dm"):
        return 1.0, 0.3
    return None, 0.0
