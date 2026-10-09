"""AIGateway: the ONLY way application code reaches a model.

Order of checks for every call (docs/ai-plan.md §1-2):
  1. provider configured?            -> AINotConfigured (external only)
  2. tenant switch / project opt-out -> AIDisabledForTenant (external only, audited as 'blocked')
  3. cache (external only)           -> hit is free, audited as 'cached'
  4. rate limit                      -> AIRateLimited
  5. budget hard stops               -> AIBudgetExceeded (audited as 'blocked')
  6. provider call with backoff      -> AIProviderError
  7. ai_calls row + cache write

Callers get a validated dict (unknown keys already dropped) and must treat it
as a PROPOSAL. Local vLLM and mock are never governed, cached or billed:
nothing leaves the deployment boundary.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

from app.ai.errors import (
    AIBudgetExceeded,
    AIDisabledForTenant,
    AINotConfigured,
    AIProviderError,
    AIRateLimited,
    AITransientError,
)
from app.ai.pricing import estimate_cost_usd
from app.ai.provider import (
    EXTRACT,
    AIProvider,
    AIRequest,
    ImageInput,
    ProviderResult,
)
from app.ai.registry import get_provider, resolve_model
from app.ai.store import AIStore, CacheHit, CallRecord, DbStore
from app.core.config import Settings, get_settings
from app.core.context import RequestContext, current_context


@dataclass(frozen=True, slots=True)
class AIMeta:
    """What the call concerns, for the audit row and the per-project budget."""

    project_id: uuid.UUID | None = None
    entity_type: str | None = None
    entity_id: str | None = None


@dataclass(slots=True)
class AIResult:
    data: dict[str, Any]
    call_id: uuid.UUID
    cached: bool
    provider: str
    model: str
    cost_usd: Decimal
    tokens_in: int = 0
    tokens_out: int = 0


class RateLimiter(Protocol):
    async def allow(self, tenant_id: uuid.UUID) -> bool: ...


class RedisRateLimiter:
    """Fixed one-minute window per tenant. Fails OPEN if Redis is down: a
    rate limiter outage must not take the AI features (and their rules
    fallbacks) offline; the budget caps still bound spend."""

    def __init__(self, url: str, per_minute: int) -> None:
        self._url = url
        self._per_minute = per_minute

    async def allow(self, tenant_id: uuid.UUID) -> bool:
        if self._per_minute <= 0:
            return True
        try:
            import redis.asyncio as redis

            client = redis.from_url(self._url)
            try:
                key = f"ai:rl:{tenant_id}:{int(time.time() // 60)}"
                count = await client.incr(key)
                if count == 1:
                    await client.expire(key, 90)
                return int(count) <= self._per_minute
            finally:
                await client.aclose()
        except Exception:  # noqa: BLE001
            return True


def input_hash(req: AIRequest) -> str:
    doc = {
        "task": req.task,
        "kind": req.kind,
        "system": req.system,
        "user": req.user,
        "schema": req.schema,
        "images": [hashlib.sha256(i.data).hexdigest() for i in req.images],
        "pdf": hashlib.sha256(req.pdf).hexdigest() if req.pdf else None,
        "max_tokens": req.max_tokens,
    }
    return hashlib.sha256(json.dumps(doc, sort_keys=True, default=str).encode()).hexdigest()


class AIGateway:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        store: AIStore | None = None,
        provider: AIProvider | None = None,
        rate_limiter: RateLimiter | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        ctx: RequestContext | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.store: AIStore = store or DbStore()
        self.provider = provider or get_provider(self.settings)
        self.rate_limiter = rate_limiter
        self._sleep = sleep
        self._ctx = ctx

    def status(self) -> dict[str, Any]:
        """Non-secret configuration state, for the admin screen."""
        return {
            "provider": self.provider.name,
            "external": self.provider.external,
            "configured": self.provider.is_configured(),
        }

    async def run(
        self,
        *,
        task: str,
        kind: str = EXTRACT,
        system: str,
        user: str,
        schema: dict[str, Any],
        images: list[ImageInput] | None = None,
        pdf: bytes | None = None,
        tier: str | None = None,
        max_tokens: int = 512,
        prompt_version: str = "1",
        meta: AIMeta | None = None,
    ) -> AIResult:
        ctx = self._ctx or current_context()
        meta = meta or AIMeta()
        provider = self.provider
        s = self.settings
        model = resolve_model(s, provider.name, kind, tier)
        req = AIRequest(
            task=task,
            kind=kind,
            model=model,
            system=system,
            user=user,
            schema=schema,
            images=list(images or []),
            pdf=pdf,
            max_tokens=max_tokens,
            timeout_s=s.ai_timeout_s if provider.external else s.vllm_timeout_s,
        )
        digest = input_hash(req)
        base = dict(
            task=task,
            provider=provider.name,
            model=model,
            prompt_version=prompt_version,
            input_sha256=digest,
            external=provider.external,
            project_id=meta.project_id,
            entity_type=meta.entity_type,
            entity_id=meta.entity_id,
            prompt=f"[system]\n{system}\n\n[user]\n{user}",
        )

        if provider.external:
            if not provider.is_configured():
                raise AINotConfigured("AI not configured")
            if not await self.store.external_allowed(ctx, meta.project_id):
                await self.store.record(ctx, CallRecord(status="blocked", error="external AI not allowed", **base))
                raise AIDisabledForTenant("External AI is not allowed for this tenant or project")
            hit = await self.store.cache_get(ctx, task, digest, model, prompt_version)
            if hit is not None:
                call_id = await self.store.record(
                    ctx, CallRecord(status="cached", response=hit.response, tokens_in=hit.tokens_in,
                                    tokens_out=hit.tokens_out, **base)
                )
                return AIResult(hit.response, call_id, True, provider.name, model, Decimal("0"), hit.tokens_in, hit.tokens_out)

        if self.rate_limiter is not None and not await self.rate_limiter.allow(ctx.tenant_id):
            raise AIRateLimited("AI rate limit reached; try again in a minute")

        month_cap = s.ai_monthly_budget_usd
        project_cap = s.ai_project_budget_usd
        if provider.external and (month_cap is not None or (project_cap is not None and meta.project_id)):
            month_spent, project_spent = await self.store.spend(ctx, meta.project_id)
            exceeded: AIBudgetExceeded | None = None
            if month_cap is not None and month_spent >= Decimal(str(month_cap)):
                exceeded = AIBudgetExceeded("monthly", month_spent, month_cap)
            elif project_cap is not None and meta.project_id and project_spent >= Decimal(str(project_cap)):
                exceeded = AIBudgetExceeded("project", project_spent, project_cap)
            if exceeded is not None:
                await self.store.record(ctx, CallRecord(status="blocked", error=str(exceeded), **base))
                raise exceeded

        started = time.monotonic()
        try:
            result = await self._call_with_retry(req)
        except AIProviderError as exc:
            await self.store.record(
                ctx,
                CallRecord(status="error", error=f"{type(exc).__name__}: {exc}"[:500],
                           latency_ms=int((time.monotonic() - started) * 1000), **base),
            )
            raise
        latency = int((time.monotonic() - started) * 1000)
        cost = estimate_cost_usd(provider.name, model, result.tokens_in, result.tokens_out, result.tokens_cached)
        call_id = await self.store.record(
            ctx,
            CallRecord(status="ok", response=result.data, tokens_in=result.tokens_in, tokens_cached=result.tokens_cached,
                       tokens_out=result.tokens_out, cost_usd=cost, latency_ms=latency, **base),
        )
        if provider.external:
            await self.store.cache_put(
                ctx, task, digest, model, prompt_version, CacheHit(result.data, result.tokens_in, result.tokens_out)
            )
        return AIResult(result.data, call_id, False, provider.name, model, cost, result.tokens_in, result.tokens_out)

    async def _call_with_retry(self, req: AIRequest) -> ProviderResult:
        attempts = max(1, self.settings.ai_max_retries)
        for attempt in range(attempts):
            try:
                return await self.provider.dispatch(req)
            except AITransientError:
                if attempt == attempts - 1:
                    raise
                await self._sleep(min(10.0, (2**attempt) + random.random()))
        raise AIProviderError("unreachable")  # pragma: no cover
