"""Native Anthropic Messages API. Schema-constrained output is obtained by
forcing a single tool call whose input_schema is our JSON schema; page
images and PDFs are sent as image/document content blocks. External:
governance applies."""

from __future__ import annotations

import base64
from typing import Any

import httpx

from app.ai.errors import AIProviderError, AITransientError
from app.ai.provider import AIProvider, AIRequest, ProviderResult
from app.core.config import Settings

ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_BASE_URL = "https://api.anthropic.com"
_TRANSIENT = {408, 409, 429, 500, 502, 503, 504, 529}
TOOL_NAME = "record_result"


class AnthropicProvider(AIProvider):
    name = "anthropic"
    external = True
    supports_pdf = True

    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._settings = settings
        self._transport = transport

    def is_configured(self) -> bool:
        s = self._settings
        return bool(s.ai_api_key.get_secret_value() and (s.ai_model or s.ai_model_classify or s.ai_model_vision))

    def _payload(self, req: AIRequest) -> dict[str, Any]:
        content: list[dict[str, Any]] = []
        if req.pdf:
            content.append(
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": base64.b64encode(req.pdf).decode("ascii"),
                    },
                }
            )
        for img in req.images:
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": img.mime,
                        "data": base64.b64encode(img.data).decode("ascii"),
                    },
                }
            )
        content.append({"type": "text", "text": req.user})
        schema = {k: v for k, v in req.schema.items() if k not in ("$schema", "$id")}
        schema.setdefault("type", "object")
        return {
            "model": req.model,
            "max_tokens": req.max_tokens,
            "temperature": 0,
            "system": req.system,
            "messages": [{"role": "user", "content": content}],
            "tools": [
                {
                    "name": TOOL_NAME,
                    "description": "Record the structured result. This is the only way to answer.",
                    "input_schema": schema,
                }
            ],
            "tool_choice": {"type": "tool", "name": TOOL_NAME},
        }

    async def _complete(self, req: AIRequest) -> ProviderResult:
        s = self._settings
        base = (s.ai_base_url or DEFAULT_BASE_URL).rstrip("/")
        headers = {
            "x-api-key": s.ai_api_key.get_secret_value(),
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=req.timeout_s, transport=self._transport) as client:
                resp = await client.post(base + "/v1/messages", headers=headers, json=self._payload(req))
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise AITransientError(type(exc).__name__) from exc
        if resp.status_code in _TRANSIENT:
            raise AITransientError(f"HTTP {resp.status_code}")
        if resp.status_code >= 400:
            raise AIProviderError(f"HTTP {resp.status_code}: {_safe_error(resp)}")
        body = resp.json()
        data = next(
            (
                b.get("input")
                for b in body.get("content", [])
                if b.get("type") == "tool_use" and b.get("name") == TOOL_NAME
            ),
            None,
        )
        if not isinstance(data, dict):
            raise AIProviderError("provider returned no structured result")
        usage = body.get("usage") or {}
        return ProviderResult(
            data=data,
            tokens_in=int(usage.get("input_tokens") or 0),
            tokens_out=int(usage.get("output_tokens") or 0),
            model=body.get("model") or req.model,
        )


def _safe_error(resp: httpx.Response) -> str:
    try:
        err = resp.json().get("error")
        msg = err.get("message") if isinstance(err, dict) else str(err)
    except Exception:  # noqa: BLE001
        msg = resp.text
    return (msg or "")[:300]
