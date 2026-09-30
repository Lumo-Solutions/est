"""Deterministic, fixture-driven provider: the default for tests and the
keyless dev stack. A per-task handler (registered by fixtures, see
app/ai/mock_fixtures.py) returns the recorded answer; with no handler the
answer is the smallest schema-valid instance, so every code path still runs.
Not external: no governance, no cost."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.ai.provider import AIProvider, AIRequest, ProviderResult
from app.ai.schema_util import minimal_instance

Handler = Callable[[AIRequest], dict[str, Any]]

_HANDLERS: dict[str, Handler] = {}


def register_mock_handler(task: str, handler: Handler) -> None:
    _HANDLERS[task] = handler


def clear_mock_handlers() -> None:
    _HANDLERS.clear()


class MockProvider(AIProvider):
    name = "mock"
    external = False
    supports_pdf = True

    def __init__(self) -> None:
        self.calls: list[AIRequest] = []

    async def _complete(self, req: AIRequest) -> ProviderResult:
        self.calls.append(req)
        handler = _HANDLERS.get(req.task)
        data = handler(req) if handler else minimal_instance(req.schema)
        return ProviderResult(
            data=data,
            tokens_in=(len(req.system) + len(req.user)) // 4,
            tokens_out=len(str(data)) // 4,
            model="mock",
        )
