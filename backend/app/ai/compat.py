"""`extract_json`: the drop-in replacement for the old
app.integrations.vllm.extract_json, so the existing callers (intake
classifier, title block, scale hint, C2 quote extraction) keep their call
shape and their tests keep monkeypatching the same name. Everything now goes
through the AIGateway."""

from __future__ import annotations

from typing import Any

from app.ai.errors import AIError
from app.ai.gateway import AIGateway, AIMeta
from app.ai.provider import CLASSIFY, EXTRACT, VISION, ImageInput
from app.core.config import Settings, get_settings


class AIExtractionError(AIError):
    """Kept for callers that catch a single failure type."""


_KIND_FOR_TASK = {
    "intake_classify": CLASSIFY,
    "scale_hint": CLASSIFY,
    "title_block": VISION,
    "quotation_extract": VISION,
}


def _gateway(settings: Settings) -> AIGateway:
    from app.ai.factory import default_gateway

    return default_gateway(settings)


def _image_from_data_url(url: str) -> ImageInput:
    import base64

    header, _, b64 = url.partition(",")
    mime = header.split(":", 1)[1].split(";", 1)[0] if ":" in header else "image/png"
    return ImageInput(base64.b64decode(b64), mime)


async def extract_json(
    *,
    system_prompt: str,
    user_prompt: str,
    json_schema: dict[str, Any],
    image_data_url: str | None = None,
    image_data_urls: list[str] | None = None,
    max_tokens: int = 512,
    settings: Settings | None = None,
    task: str = "extract",
    meta: AIMeta | None = None,
    prompt_version: str = "1",
) -> dict[str, Any]:
    settings = settings or get_settings()
    urls = list(image_data_urls or ([image_data_url] if image_data_url else []))
    images = [_image_from_data_url(u) for u in urls]
    kind = _KIND_FOR_TASK.get(task, VISION if images else EXTRACT)
    if task == "intake_classify" and images:
        kind = VISION  # text is the classify model's job; images (scans, drawing sheets) need the vision model
    result = await _gateway(settings).run(
        task=task,
        kind=kind,
        system=system_prompt,
        user=user_prompt,
        schema=json_schema,
        images=images,
        max_tokens=max_tokens,
        prompt_version=prompt_version,
        meta=meta,
    )
    return result.data
