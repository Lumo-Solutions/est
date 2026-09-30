"""Typed failures of the AI gateway. Every caller already has a rules-based
fallback; these exist so it can tell the user *why* the AI step was skipped."""

from __future__ import annotations


class AIError(Exception):
    code = "ai_error"


class AINotConfigured(AIError):
    """External provider selected but no key/base URL/model: 'AI not configured'."""

    code = "ai_not_configured"


class AIDisabledForTenant(AIError):
    """Tenant switch is off, or the project opted out of external AI."""

    code = "ai_not_allowed"


class AIBudgetExceeded(AIError):
    code = "ai_budget_exceeded"

    def __init__(self, scope: str, spent: object, cap: object) -> None:
        super().__init__(f"AI {scope} budget reached (spent {spent} of {cap} USD)")
        self.scope = scope
        self.spent = spent
        self.cap = cap


class AIRateLimited(AIError):
    code = "ai_rate_limited"


class AIProviderError(AIError):
    """The provider call failed for good (after retries) or returned unusable output."""

    code = "ai_provider_error"


class AITransientError(AIProviderError):
    """Retryable: timeout, connection error, 429, 5xx."""


class AIOutputInvalid(AIProviderError):
    code = "ai_output_invalid"
