"""Cost estimate per call. Rates are USD per million tokens and are an
ESTIMATE for budgeting only (the provider's invoice is authoritative). The
table is deliberately small: unknown models fall back to a conservative
default so a budget cap is never silently bypassed by an unlisted model.
Local/mock providers cost 0."""

from __future__ import annotations

from decimal import Decimal

# (input_per_mtok, output_per_mtok)
_RATES: dict[str, tuple[Decimal, Decimal]] = {
    "haiku": (Decimal("1"), Decimal("5")),
    "sonnet": (Decimal("3"), Decimal("15")),
    "opus": (Decimal("5"), Decimal("25")),
    "fable": (Decimal("5"), Decimal("25")),
    "gpt-4o-mini": (Decimal("0.15"), Decimal("0.6")),
    "gpt-4o": (Decimal("2.5"), Decimal("10")),
}
_DEFAULT = (Decimal("5"), Decimal("25"))
_MILLION = Decimal(1_000_000)


def estimate_cost_usd(provider: str, model: str, tokens_in: int, tokens_out: int) -> Decimal:
    if provider in ("local_vllm", "mock"):
        return Decimal("0")
    m = model.lower()
    rate = next((r for key, r in sorted(_RATES.items(), key=lambda kv: -len(kv[0])) if key in m), _DEFAULT)
    cost = (Decimal(tokens_in) * rate[0] + Decimal(tokens_out) * rate[1]) / _MILLION
    return cost.quantize(Decimal("0.000001"))
