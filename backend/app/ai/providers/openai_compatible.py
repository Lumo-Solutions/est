"""Any OpenAI-style /chat/completions endpoint with `response_format`
JSON-schema output and image_url input. External: governance applies."""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.ai.errors import AIProviderError, AITransientError
from app.ai.provider import AIProvider, AIRequest, ProviderResult
from app.core.config import Settings

_TRANSIENT = {408, 409, 425, 429, 500, 502, 503, 504, 529}


class OpenAICompatibleProvider(AIProvider):
    name = "openai_compatible"
    external = True

    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._settings = settings
        self._transport = transport

    def is_configured(self) -> bool:
        s = self._settings
        return bool(s.ai_api_key.get_secret_value() and s.ai_base_url and (s.ai_model or s.ai_model_classify))

    def _payload(self, req: AIRequest) -> dict[str, Any]:
        user_content: Any = req.user
        if req.images:
            user_content = [{"type": "text", "text": req.user}] + [
                {"type": "image_url", "image_url": {"url": img.data_url()}} for img in req.images
            ]
        body = {
            "model": req.model,
            "temperature": 0,
            "max_tokens": req.max_tokens,
            "messages": [{"role": "system", "content": req.system}, {"role": "user", "content": user_content}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": req.task[:60], "schema": _clean_schema(req.schema), "strict": False},
            },
        }
        extra = _extra_body(self._settings.ai_extra_body)
        # The request's own fields win: AI_EXTRA_BODY adds provider switches, it does not replace the call.
        return {**extra, **body}

    async def _complete(self, req: AIRequest) -> ProviderResult:
        s = self._settings
        url = s.ai_base_url.rstrip("/") + "/chat/completions"
        headers = {"Authorization": f"Bearer {s.ai_api_key.get_secret_value()}", "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=req.timeout_s, transport=self._transport) as client:
                resp = await client.post(url, headers=headers, json=self._payload(req))
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise AITransientError(type(exc).__name__) from exc
        if resp.status_code in _TRANSIENT:
            raise AITransientError(f"HTTP {resp.status_code}")
        if resp.status_code >= 400:
            raise AIProviderError(f"HTTP {resp.status_code}: {_safe_error(resp)}")
        body = resp.json()
        try:
            content = body["choices"][0]["message"]["content"]
            data = json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise AIProviderError("provider returned no valid JSON content") from exc
        usage = body.get("usage") or {}
        return ProviderResult(
            data=data,
            tokens_in=int(usage.get("prompt_tokens") or 0),
            tokens_out=int(usage.get("completion_tokens") or 0),
            model=body.get("model") or req.model,
            tokens_cached=_cached_tokens(usage),
        )


def _extra_body(raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _cached_tokens(usage: dict[str, Any]) -> int:
    """Prompt tokens served from the provider's cache. Qwen / OpenAI-compatible: usage.prompt_tokens_details.cached_tokens
    (some gateways put `cached_tokens` or `prompt_cache_hit_tokens` at the top level)."""
    details = usage.get("prompt_tokens_details") or {}
    raw = details.get("cached_tokens") if isinstance(details, dict) else None
    if raw is None:
        raw = usage.get("cached_tokens", usage.get("prompt_cache_hit_tokens"))
    try:
        return max(0, int(raw or 0))
    except (TypeError, ValueError):
        return 0


def _clean_schema(schema: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in schema.items() if k not in ("$schema", "$id")}


def _safe_error(resp: httpx.Response) -> str:
    try:
        err = resp.json().get("error")
        msg = err.get("message") if isinstance(err, dict) else str(err)
    except Exception:  # noqa: BLE001
        msg = resp.text
    return (msg or "")[:300]
