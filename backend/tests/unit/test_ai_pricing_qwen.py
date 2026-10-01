"""Qwen rates, cached-input pricing, the unverified plus rate, and which model each kind of call is routed to."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.ai import pricing
from app.ai.provider import CLASSIFY, EXTRACT, MATCH_RANK, VISION
from app.ai.providers.openai_compatible import _cached_tokens
from app.ai.registry import resolve_model
from app.core.config import Settings

_REQUIRED = dict(
    APP_DATABASE_URL="postgresql://x/y", MIGRATOR_DATABASE_URL="postgresql://x/y", S3_ENDPOINT="http://s3.test",
    VLLM_API_BASE="http://vllm.internal:8000/v1",
)


def M(tokens: int) -> Decimal:
    return Decimal(tokens)


def test_flash_uses_the_rates_measured_from_the_invoice():
    r = pricing.rate_for("qwen3.7-flash")
    assert (r.input, r.cached, r.output) == (Decimal("0.03"), Decimal("0.006"), Decimal("0.13")) and r.verified
    # 1M in, 1M out, nothing cached: 0.03 + 0.13
    assert pricing.estimate_cost_usd("openai_compatible", "qwen3.7-flash", 1_000_000, 1_000_000) == Decimal("0.160000")


def test_cached_prompt_tokens_are_billed_at_the_cached_rate():
    full = pricing.estimate_cost_usd("openai_compatible", "qwen3.7-flash", 1_000_000, 0)
    half = pricing.estimate_cost_usd("openai_compatible", "qwen3.7-flash", 1_000_000, 0, tokens_cached=500_000)
    assert full == Decimal("0.030000") and half == Decimal("0.018000")  # 0.5M x 0.03 + 0.5M x 0.006
    # More cached than sent cannot happen; it is clamped, never negative.
    assert pricing.estimate_cost_usd("openai_compatible", "qwen3.7-flash", 1_000, 0, tokens_cached=5_000) == Decimal("0.000006")


def test_plus_is_priced_but_marked_unverified_until_checked_against_a_bill():
    r = pricing.rate_for("qwen3.7-plus")
    assert (r.input, r.output) == (Decimal("0.40"), Decimal("1.20")) and r.verified is False
    assert pricing.is_unverified("qwen3.7-plus") and not pricing.is_unverified("qwen3.7-flash")


def test_unknown_models_keep_the_cautious_default_and_are_unverified():
    unknown = pricing.estimate_cost_usd("openai_compatible", "some-new-model", 1_000_000, 1_000_000)
    assert unknown == Decimal("30.000000")  # the old conservative default: 5 + 25
    assert pricing.is_unverified("some-new-model")
    # cached tokens on a model with no cached rate are charged as normal input (cautious)
    assert pricing.estimate_cost_usd("openai_compatible", "some-new-model", 1_000_000, 0, tokens_cached=1_000_000) == Decimal("5.000000")


def test_local_and_mock_providers_cost_nothing():
    assert pricing.estimate_cost_usd("mock", "qwen3.7-plus", 10**6, 10**6) == 0
    assert pricing.estimate_cost_usd("local_vllm", "x", 10**6, 10**6) == 0


@pytest.mark.parametrize(
    "usage,expected",
    [
        ({"prompt_tokens": 100, "prompt_tokens_details": {"cached_tokens": 64}}, 64),
        ({"prompt_tokens": 100, "cached_tokens": 10}, 10),
        ({"prompt_tokens": 100, "prompt_cache_hit_tokens": 7}, 7),
        ({"prompt_tokens": 100, "prompt_tokens_details": None}, 0),
        ({"prompt_tokens": 100}, 0),
        ({"prompt_tokens_details": {"cached_tokens": "x"}}, 0),
    ],
)
def test_the_cached_token_count_is_read_from_the_usage_fields_qwen_returns(usage, expected):
    assert _cached_tokens(usage) == expected


def test_each_kind_of_call_is_routed_to_its_configured_model():
    s = Settings(AI_PROVIDER="openai_compatible", AI_MODEL="qwen3.7-plus", AI_MODEL_CLASSIFY="qwen3.7-flash",
                 AI_MODEL_VISION="qwen3.7-plus", AI_MODEL_REASONING="qwen3.7-plus", **_REQUIRED)  # type: ignore[arg-type]
    assert resolve_model(s, "openai_compatible", CLASSIFY) == "qwen3.7-flash"  # text classification: the cheap tier
    assert resolve_model(s, "openai_compatible", VISION) == "qwen3.7-plus"  # page images: the vision tier
    assert resolve_model(s, "openai_compatible", EXTRACT) == "qwen3.7-plus"
    assert resolve_model(s, "openai_compatible", MATCH_RANK) == "qwen3.7-plus"
    bare = Settings(AI_PROVIDER="openai_compatible", AI_MODEL="qwen3.7-plus", **_REQUIRED)  # type: ignore[arg-type]
    assert resolve_model(bare, "openai_compatible", CLASSIFY) == "qwen3.7-plus"  # no override: AI_MODEL


@pytest.mark.asyncio
async def test_a_provider_response_with_cached_tokens_is_priced_and_recorded(monkeypatch):
    import httpx

    from app.ai.provider import AIRequest
    from app.ai.providers.openai_compatible import OpenAICompatibleProvider

    body = {
        "model": "qwen3.7-flash", "choices": [{"message": {"content": "{\"ok\": true}"}}],
        "usage": {"prompt_tokens": 2000, "completion_tokens": 100, "prompt_tokens_details": {"cached_tokens": 1500}},
    }
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=body))
    s = Settings(AI_PROVIDER="openai_compatible", AI_MODEL="qwen3.7-flash", AI_API_KEY="k", AI_BASE_URL="http://x/v1", **_REQUIRED)  # type: ignore[arg-type]
    provider = OpenAICompatibleProvider(s, transport=transport)
    result = await provider._complete(AIRequest(task="t", kind=CLASSIFY, model="qwen3.7-flash", system="s", user="u", schema={"type": "object"}))
    assert (result.tokens_in, result.tokens_cached, result.tokens_out) == (2000, 1500, 100)
    cost = pricing.estimate_cost_usd("openai_compatible", result.model, result.tokens_in, result.tokens_out, result.tokens_cached)
    assert cost == Decimal("0.000037")  # 500 x 0.03 + 1500 x 0.006 + 100 x 0.13, per million
