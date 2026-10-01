"""Cost estimate per call. Rates are USD per million tokens and are an
ESTIMATE for budgeting only (the provider's invoice is authoritative). The
table is deliberately small: unknown models fall back to a conservative
default so a budget cap is never silently bypassed by an unlisted model.
Local/mock providers cost 0.

Cached input: some providers (Qwen, OpenAI-compatible APIs) report how many prompt tokens were served from their
cache (`usage.prompt_tokens_details.cached_tokens`) and bill those at a lower rate. Those tokens are priced at the
model's cached rate; models without a listed cached rate pay the full input rate for them (the cautious reading)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class Rate:
    input: Decimal
    output: Decimal
    cached: Decimal | None = None  # None: cached tokens cost the full input rate
    # False: the numbers are not yet checked against a real invoice (shown as "unverified" wherever cost is shown).
    verified: bool = True

    @property
    def cached_rate(self) -> Decimal:
        return self.input if self.cached is None else self.cached


_RATES: dict[str, Rate] = {
    "haiku": Rate(Decimal("1"), Decimal("5")),
    "sonnet": Rate(Decimal("3"), Decimal("15")),
    "opus": Rate(Decimal("5"), Decimal("25")),
    "fable": Rate(Decimal("5"), Decimal("25")),
    "gpt-4o-mini": Rate(Decimal("0.15"), Decimal("0.6")),
    "gpt-4o": Rate(Decimal("2.5"), Decimal("10")),
    # Alibaba Model Studio, international, pay-as-you-go, 2026-10. flash: measured from the owner's invoice.
    "qwen3.7-flash": Rate(Decimal("0.03"), Decimal("0.13"), Decimal("0.006"), verified=True),
    # plus: NOT yet checked against an invoice. Alibaba's published international price (input 0.40, output 1.20 per
    # million tokens; cached input at 20% of input). UNVERIFIED until the first real plus call is compared with the bill.
    "qwen3.7-plus": Rate(Decimal("0.40"), Decimal("1.20"), Decimal("0.08"), verified=False),
}
_DEFAULT = Rate(Decimal("5"), Decimal("25"))
_MILLION = Decimal(1_000_000)


def rate_for(model: str) -> Rate:
    m = model.lower()
    return next((r for key, r in sorted(_RATES.items(), key=lambda kv: -len(kv[0])) if key in m), _DEFAULT)


def is_unverified(model: str) -> bool:
    """True when the rate used for this model is a published or default price, not one checked against an invoice."""
    r = rate_for(model)
    return (not r.verified) or r is _DEFAULT


def estimate_cost_usd(provider: str, model: str, tokens_in: int, tokens_out: int, tokens_cached: int = 0) -> Decimal:
    """`tokens_in` is the whole prompt (cached tokens included), as providers report it."""
    if provider in ("local_vllm", "mock"):
        return Decimal("0")
    rate = rate_for(model)
    cached = max(0, min(tokens_cached, tokens_in))
    fresh = tokens_in - cached
    cost = (Decimal(fresh) * rate.input + Decimal(cached) * rate.cached_rate + Decimal(tokens_out) * rate.output) / _MILLION
    return cost.quantize(Decimal("0.000001"))
