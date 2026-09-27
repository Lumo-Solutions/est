from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict
from pydantic.functional_serializers import PlainSerializer


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# Use this (never bare `Decimal`) on any RESPONSE schema field -- FastAPI's
# jsonable_encoder(), when the top-level object is a pydantic BaseModel
# instance (which every response_model is), calls that model's own
# `model_dump(mode="json")` rather than recursing field-by-field with its
# own Decimal handling. Pydantic v2's JSON mode serializes Decimal as a
# STRING by default (`"7.995"`, not `7.995`), unlike jsonable_encoder()
# applied to a bare Decimal or a plain dict (which does produce a JSON
# number) -- confirmed empirically; this is not documented as obviously as
# it should be. Every frontend type in src/types/api.ts declares these
# fields `number`, so a plain `Decimal` field silently ships a string
# instead and crashes the first `.toFixed()`/arithmetic call on it (found
# via SettlementPage.tsx's SimulationSliders while building a real,
# non-mocked Playwright test for Phase 10 -- see docs/build-log.md). Money/
# percentage REQUEST fields (input schemas) are unaffected either way and
# don't need this -- pydantic parses a JSON number or a numeric string into
# Decimal identically -- so only use it for fields a response_model
# actually returns.
JsonDecimal = Annotated[Decimal, PlainSerializer(lambda v: float(v), return_type=float, when_used="json")]


class Page(ORMModel):
    items: list
    total: int
    limit: int
    offset: int
