"""AI reading of what is PRINTED on a drawing sheet (docs/ai-plan.md §4).

Returns title-block fields, scale notes, legend, schedule rows and
dimension/quantity annotations with the sheet page and a bounding box. These are
READ values, never measurements: geometry measurement stays deterministic. The
result is stored as ``drawing_annotations`` rows (source='ai') and later offered
to the drawing<->BOQ verification as one kind of evidence, always labelled.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.ai.gateway import AIGateway, AIMeta
from app.ai.provider import VISION, ImageInput
from app.takeoff.prompts import load_schema, render_prompt

AI_CONFIDENCE_CAP = 0.85
SHEET_TEXT_CHARS = 8_000
PROMPT_VERSION = "1"
_KINDS = {"length", "area", "volume", "count", "diameter", "level", "other"}


@dataclass(slots=True)
class ReadAnnotation:
    text: str
    kind: str
    value: float | None
    unit: str | None
    material: str | None
    bbox: list[float] | None


@dataclass(slots=True)
class SheetReading:
    annotations: list[ReadAnnotation] = field(default_factory=list)
    notes: dict[str, Any] = field(default_factory=dict)  # title_block, scale_notes, legend, schedule
    confidence: float = 0.0
    ai_call_id: Any = None


def _clean_bbox(bbox: Any) -> list[float] | None:
    if isinstance(bbox, list) and len(bbox) == 4 and all(isinstance(v, (int, float)) and 0.0 <= v <= 1.0 for v in bbox):
        return [float(v) for v in bbox]
    return None


def parse_reading(raw: dict[str, Any]) -> SheetReading:
    anns: list[ReadAnnotation] = []
    for a in raw.get("annotations", []):
        text = (a.get("text") or "").strip()
        if not text:
            continue
        kind = a.get("kind") if a.get("kind") in _KINDS else "other"
        value = a.get("value")
        anns.append(
            ReadAnnotation(
                text=text[:500], kind=kind, value=float(value) if isinstance(value, (int, float)) else None,
                unit=(a.get("unit") or None), material=((a.get("material") or None) and a["material"][:128]),
                bbox=_clean_bbox(a.get("bbox")),
            )
        )
    notes = {
        "title_block": raw.get("title_block") or {},
        "scale_notes": [str(s)[:200] for s in raw.get("scale_notes", [])][:20],
        "legend": raw.get("legend", [])[:200],
        "schedule": [[str(c)[:120] for c in row][:20] for row in raw.get("schedule", [])[:300]],
    }
    return SheetReading(anns, notes, min(float(raw.get("confidence") or 0.6), AI_CONFIDENCE_CAP))


async def read_sheet(
    gateway: AIGateway, *, page_number: int, sheet_text: str, image_png: bytes | None, meta: AIMeta | None = None
) -> SheetReading:
    system, user = render_prompt(
        "drawing_annotations.j2", page_number=page_number, sheet_text=(sheet_text or "")[:SHEET_TEXT_CHARS],
        has_image=image_png is not None,
    )
    result = await gateway.run(
        task="drawing_annotations", kind=VISION, system=system, user=user,
        schema=load_schema("drawing_annotations.schema.json"),
        images=[ImageInput(image_png, "image/png")] if image_png else [], max_tokens=4096,
        prompt_version=PROMPT_VERSION, meta=meta,
    )
    reading = parse_reading(result.data)
    reading.ai_call_id = result.call_id
    return reading
