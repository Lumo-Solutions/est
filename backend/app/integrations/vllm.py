from __future__ import annotations

import json
from typing import Any

from openai import APIConnectionError, APITimeoutError, AsyncOpenAI, InternalServerError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from app.core.config import Settings, get_settings


def _client(settings: Settings) -> AsyncOpenAI:
    return AsyncOpenAI(
        base_url=settings.vllm_api_base, api_key=settings.vllm_api_key, timeout=settings.vllm_timeout_s
    )


class VllmExtractionError(Exception):
    pass


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(initial=1, max=10),
    retry=retry_if_exception_type((APITimeoutError, APIConnectionError, InternalServerError)),
)
async def extract_json(
    *,
    system_prompt: str,
    user_prompt: str,
    json_schema: dict[str, Any],
    image_data_url: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Calls the OpenAI-compatible /v1/chat/completions endpoint (real vLLM
    or the mock -- see ai-service/mock-vllm) with guided JSON decoding, and
    returns the parsed+validated response object. Text-only or
    text+image (Qwen2.5-VL) depending on whether image_data_url is given."""
    settings = settings or get_settings()
    client = _client(settings)

    user_content: Any = user_prompt
    if image_data_url:
        user_content = [
            {"type": "text", "text": user_prompt},
            {"type": "image_url", "image_url": {"url": image_data_url}},
        ]

    response = await client.chat.completions.create(
        model=settings.vllm_model,
        temperature=0,
        max_tokens=512,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        extra_body={"guided_json": json_schema},
    )
    content = response.choices[0].message.content
    if not content:
        raise VllmExtractionError("Empty completion from vLLM")
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise VllmExtractionError(f"vLLM did not return valid JSON: {exc}") from exc
