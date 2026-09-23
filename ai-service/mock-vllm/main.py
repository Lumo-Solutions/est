"""Minimal OpenAI-compatible mock of vLLM's /v1/chat/completions.

Lets the Module B ingestion pipeline run end-to-end (title-block extraction,
scale disambiguation) without a GPU. Returns placeholder values shaped to
satisfy whatever JSON Schema the caller requested via guided decoding, so
downstream Pydantic validation succeeds. Swap the real `vllm` service back in
by pointing VLLM_API_BASE at it — the request/response contract is identical.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict

app = FastAPI(title="mock-vllm")


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="allow")
    role: str
    content: Any = None


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    model: str = "mock-model"
    messages: list[ChatMessage] = []
    temperature: float | None = None
    max_tokens: int | None = None
    response_format: dict[str, Any] | None = None
    extra_body: dict[str, Any] | None = None
    guided_json: dict[str, Any] | None = None


def _placeholder_for(schema: dict[str, Any]) -> Any:
    schema_type = schema.get("type")
    if schema_type == "object" or "properties" in schema:
        props = schema.get("properties", {})
        return {name: _placeholder_for(sub) for name, sub in props.items()}
    if schema_type == "array":
        return []
    if schema_type == "number":
        return schema.get("default", 0.5)
    if schema_type == "integer":
        return schema.get("default", 0)
    if schema_type == "boolean":
        return schema.get("default", False)
    if schema_type in ("string", None):
        enum = schema.get("enum")
        if enum:
            return enum[0]
        return "MOCK-VALUE"
    return None


def _extract_schema(req: ChatCompletionRequest) -> dict[str, Any] | None:
    if req.guided_json:
        return req.guided_json
    if req.extra_body and req.extra_body.get("guided_json"):
        return req.extra_body["guided_json"]
    if req.response_format:
        json_schema = req.response_format.get("json_schema")
        if json_schema and json_schema.get("schema"):
            return json_schema["schema"]
    return None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/models")
def list_models() -> dict[str, Any]:
    return {
        "object": "list",
        "data": [
            {
                "id": "Qwen/Qwen2.5-VL-7B-Instruct",
                "object": "model",
                "owned_by": "mock-vllm",
            }
        ],
    }


@app.post("/v1/chat/completions")
def chat_completions(req: ChatCompletionRequest) -> dict[str, Any]:
    schema = _extract_schema(req)
    content = json.dumps(_placeholder_for(schema)) if schema else "MOCK-VALUE"

    return {
        "id": f"chatcmpl-mock-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": req.model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }
