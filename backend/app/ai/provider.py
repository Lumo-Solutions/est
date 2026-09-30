"""The one interface every AI backend implements (docs/ai-plan.md §1).

Callers never use a provider directly; they go through `AIGateway`, which
adds governance, cache, budget and the ai_calls audit row.
"""

from __future__ import annotations

import base64
from collections.abc import Awaitable
from dataclasses import dataclass, field
from typing import Any

from app.ai.errors import AIOutputInvalid
from app.ai.schema_util import clamp_numbers, strip_unknown, validate

# Operation kinds (they differ in labelling / default model tier, not wire path).
CLASSIFY = "classify"
EXTRACT = "extract_structured"
VISION = "vision_extract"
MATCH_RANK = "match_rank"

# Model tiers -> settings attribute.
TIER_CLASSIFY = "classify"
TIER_VISION = "vision"
TIER_REASONING = "reasoning"


@dataclass(frozen=True, slots=True)
class ImageInput:
    data: bytes
    mime: str = "image/png"

    def data_url(self) -> str:
        return f"data:{self.mime};base64,{base64.b64encode(self.data).decode('ascii')}"


@dataclass(slots=True)
class AIRequest:
    task: str
    kind: str
    model: str
    system: str
    user: str
    schema: dict[str, Any]
    images: list[ImageInput] = field(default_factory=list)
    pdf: bytes | None = None
    max_tokens: int = 512
    timeout_s: float = 120.0


@dataclass(slots=True)
class ProviderResult:
    data: dict[str, Any]
    tokens_in: int = 0
    tokens_out: int = 0
    model: str = ""


class AIProvider:
    """Base class. Subclasses implement `_complete`; the four public
    operations share it. `external` marks providers that send data outside
    the deployment boundary (governance applies to those only)."""

    name = "base"
    external = False
    supports_pdf = False

    def is_configured(self) -> bool:
        return True

    async def _complete(self, req: AIRequest) -> ProviderResult:  # pragma: no cover - abstract
        raise NotImplementedError

    async def classify(self, req: AIRequest) -> ProviderResult:
        return await self._checked(req)

    async def extract_structured(self, req: AIRequest) -> ProviderResult:
        return await self._checked(req)

    async def vision_extract(self, req: AIRequest) -> ProviderResult:
        return await self._checked(req)

    async def match_rank(self, req: AIRequest) -> ProviderResult:
        return await self._checked(req)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError(f"{self.name} does not provide embeddings; the local embedder is used")

    async def _checked(self, req: AIRequest) -> ProviderResult:
        """Runs the provider and enforces the schema: unknown keys are
        dropped (AI output has no back door), structural problems raise."""
        result = await self._complete(req)
        cleaned = clamp_numbers(strip_unknown(result.data, req.schema), req.schema)
        problems = validate(cleaned, req.schema)
        if problems:
            raise AIOutputInvalid("; ".join(problems[:5]))
        result.data = cleaned
        return result

    def dispatch(self, req: AIRequest) -> Awaitable[ProviderResult]:
        return {
            CLASSIFY: self.classify,
            EXTRACT: self.extract_structured,
            VISION: self.vision_extract,
            MATCH_RANK: self.match_rank,
        }[req.kind](req)
