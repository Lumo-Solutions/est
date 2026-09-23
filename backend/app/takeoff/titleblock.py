from __future__ import annotations

import base64

from pydantic import BaseModel

from app.integrations.vllm import extract_json
from app.takeoff.prompts import load_schema, render_prompt

_DISCIPLINES = {"civil", "structural", "mep", "architectural", "landscape", "other"}


class TitleBlockResult(BaseModel):
    drawing_number: str | None = None
    sheet_title: str | None = None
    revision: str | None = None
    issue_date: str | None = None
    discipline: str | None = None
    scale_text: str | None = None
    project_name: str | None = None
    client_name: str | None = None
    confidence: float = 0.0
    raw: dict = {}


async def extract_title_block(
    *, candidate_text: str, image_png: bytes | None, sheet_context: dict | None = None
) -> TitleBlockResult:
    """Calls vLLM (real or mock) with the title_block.j2 prompt, constrained
    to title_block.schema.json via guided decoding. Text-only when
    image_png is None; text+image (Qwen2.5-VL vision path) otherwise."""
    system_prompt, user_prompt = render_prompt(
        "title_block.j2",
        candidate_text=candidate_text,
        has_image=image_png is not None,
        sheet_context=sheet_context or {},
    )
    schema = load_schema("title_block.schema.json")

    image_data_url = None
    if image_png is not None:
        b64 = base64.b64encode(image_png).decode("ascii")
        image_data_url = f"data:image/png;base64,{b64}"

    raw = await extract_json(
        system_prompt=system_prompt, user_prompt=user_prompt, json_schema=schema, image_data_url=image_data_url
    )

    discipline = raw.get("discipline")
    if discipline not in _DISCIPLINES:
        discipline = None

    return TitleBlockResult(
        drawing_number=raw.get("drawing_number"),
        sheet_title=raw.get("sheet_title"),
        revision=raw.get("revision"),
        issue_date=raw.get("issue_date"),
        discipline=discipline,
        scale_text=raw.get("scale_text"),
        project_name=raw.get("project_name"),
        client_name=raw.get("client_name"),
        confidence=float(raw.get("confidence") or 0.0),
        raw=raw,
    )
