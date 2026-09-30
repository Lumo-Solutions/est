from __future__ import annotations

from app.ai.provider import (
    CLASSIFY,
    EXTRACT,
    MATCH_RANK,
    TIER_CLASSIFY,
    TIER_REASONING,
    TIER_VISION,
    VISION,
    AIProvider,
)
from app.core.config import Settings

_KIND_TIER = {CLASSIFY: TIER_CLASSIFY, VISION: TIER_VISION, MATCH_RANK: TIER_REASONING, EXTRACT: TIER_REASONING}

_mock_singleton = None


def get_provider(settings: Settings) -> AIProvider:
    name = settings.ai_provider
    if name == "anthropic":
        from app.ai.providers.anthropic import AnthropicProvider

        return AnthropicProvider(settings)
    if name == "openai_compatible":
        from app.ai.providers.openai_compatible import OpenAICompatibleProvider

        return OpenAICompatibleProvider(settings)
    if name == "mock":
        from app.ai.providers.mock import MockProvider

        global _mock_singleton
        if _mock_singleton is None:
            _mock_singleton = MockProvider()
        return _mock_singleton
    from app.ai.providers.local_vllm import LocalVllmProvider

    return LocalVllmProvider(settings)


def resolve_model(settings: Settings, provider_name: str, kind: str, tier: str | None = None) -> str:
    """Model for a call: local vLLM always uses VLLM_MODEL; external providers
    use the per-tier override, falling back to AI_MODEL."""
    if provider_name == "local_vllm":
        return settings.vllm_model
    if provider_name == "mock":
        return "mock"
    tier = tier or _KIND_TIER.get(kind, TIER_REASONING)
    override = {
        TIER_CLASSIFY: settings.ai_model_classify,
        TIER_VISION: settings.ai_model_vision,
        TIER_REASONING: settings.ai_model_reasoning,
    }.get(tier, "")
    return override or settings.ai_model
