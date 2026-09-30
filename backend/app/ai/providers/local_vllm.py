"""Self-hosted vLLM (the default; SRS §1.1 compliant). Guided JSON decoding
through the OpenAI-compatible endpoint, exactly as the platform did before
the provider layer existed."""

from __future__ import annotations

import json

from openai import APIConnectionError, APITimeoutError, AsyncOpenAI, InternalServerError

from app.ai.errors import AIProviderError, AITransientError
from app.ai.provider import AIProvider, AIRequest, ProviderResult
from app.core.config import Settings


class LocalVllmProvider(AIProvider):
    name = "local_vllm"
    external = False

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def _complete(self, req: AIRequest) -> ProviderResult:
        s = self._settings
        client = AsyncOpenAI(base_url=s.vllm_api_base, api_key=s.vllm_api_key, timeout=s.vllm_timeout_s)
        user_content: object = req.user
        if req.images:
            user_content = [{"type": "text", "text": req.user}] + [
                {"type": "image_url", "image_url": {"url": img.data_url()}} for img in req.images
            ]
        try:
            response = await client.chat.completions.create(
                model=req.model,
                temperature=0,
                max_tokens=req.max_tokens,
                messages=[{"role": "system", "content": req.system}, {"role": "user", "content": user_content}],
                extra_body={"guided_json": req.schema},
            )
        except (APITimeoutError, APIConnectionError, InternalServerError) as exc:
            raise AITransientError(str(exc)) from exc
        content = response.choices[0].message.content
        if not content:
            raise AIProviderError("Empty completion from vLLM")
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise AIProviderError(f"vLLM did not return valid JSON: {exc}") from exc
        usage = getattr(response, "usage", None)
        return ProviderResult(
            data=data,
            tokens_in=getattr(usage, "prompt_tokens", 0) or 0,
            tokens_out=getattr(usage, "completion_tokens", 0) or 0,
            model=req.model,
        )
