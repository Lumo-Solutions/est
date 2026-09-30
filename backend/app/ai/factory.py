"""One place that builds the default AIGateway for application code. The eval harness and tests install an
override (a gateway with an in-memory store, no database) so production code paths can be exercised without
the governance tables."""

from __future__ import annotations

from collections.abc import Callable

from app.ai.gateway import AIGateway, RedisRateLimiter
from app.core.config import Settings, get_settings

_override: Callable[[Settings], AIGateway] | None = None


def set_gateway_override(factory: Callable[[Settings], AIGateway] | None) -> None:
    global _override
    _override = factory


def default_gateway(settings: Settings | None = None) -> AIGateway:
    settings = settings or get_settings()
    if _override is not None:
        return _override(settings)
    limiter = None
    if settings.ai_provider not in ("local_vllm", "mock"):
        limiter = RedisRateLimiter(settings.redis_url, settings.ai_rate_limit_per_min)
    return AIGateway(settings=settings, rate_limiter=limiter)
