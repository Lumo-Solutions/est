"""Regression test for the "JsonDecimal sweep" gap carried forward from
Phase 10 (docs/build-log.md, "Known gaps carried forward" -- "JsonDecimal's
fix is applied only to settlement.py/approvals.py; every other Decimal-typed
response schema in the codebase likely has the same string-not-number bug").

app/schemas/common.py's JsonDecimal exists because pydantic v2 serializes a
bare `Decimal` field to JSON as a STRING ("123.45"), but every frontend type
in frontend/src/types/api.ts declares these fields `number` -- a page that
does arithmetic or `.toFixed()` on one crashes. Found live via Phase 2 UI QA:
QuotationOut, QuotationLineItemOut, QuotationExclusionFlagOut,
BidLevelingCellOut and QuotationTotalOut (all real, already-shipped fields
used by QuoteReviewPage/BidLevelingPage) still used bare `Decimal`;
ContractVariationOut/OutturnCostObservationOut (Module E, no frontend yet)
had the same latent bug. All fixed to JsonDecimal alongside this test.

This is a static/introspection check across every schemas module rather than
a per-endpoint test, so a future response field added anywhere in
app/schemas can't silently reintroduce the same string-not-number bug.
"""

from __future__ import annotations

import importlib
import pkgutil
from decimal import Decimal
from typing import get_args

from pydantic.functional_serializers import PlainSerializer

import app.schemas
from app.schemas.common import ORMModel


def _import_every_schema_module() -> None:
    for module_info in pkgutil.iter_modules(app.schemas.__path__):
        importlib.import_module(f"app.schemas.{module_info.name}")


def _every_orm_model_subclass() -> set[type[ORMModel]]:
    _import_every_schema_module()
    seen: set[type[ORMModel]] = set()
    frontier = list(ORMModel.__subclasses__())
    while frontier:
        cls = frontier.pop()
        if cls in seen:
            continue
        seen.add(cls)
        frontier.extend(cls.__subclasses__())
    return seen


def _mentions_decimal(annotation: object) -> bool:
    return annotation is Decimal or "decimal.Decimal" in str(annotation)


def _flatten_metadata(annotation: object) -> list[object]:
    """Walks a (possibly Optional-wrapped) annotation and collects every
    Annotated[...] metadata item found anywhere inside it -- e.g. for
    `Annotated[Decimal, PlainSerializer(...)] | None`, `typing.get_args` on
    the outer Union only yields its two members (the Annotated type and
    NoneType); the PlainSerializer itself is one level deeper, inside
    `get_args` of that Annotated member."""
    found: list[object] = []
    for arg in get_args(annotation):
        found.append(arg)
        found.extend(get_args(arg))
    return found


def _has_json_float_serializer(field_info) -> bool:
    candidates = list(field_info.metadata) + _flatten_metadata(field_info.annotation)
    return any(isinstance(item, PlainSerializer) for item in candidates)


def test_every_orm_response_schema_decimal_field_uses_json_decimal():
    offending: list[str] = []
    for cls in _every_orm_model_subclass():
        for name, field_info in cls.model_fields.items():
            if not _mentions_decimal(field_info.annotation):
                continue
            if not _has_json_float_serializer(field_info):
                offending.append(f"{cls.__module__}.{cls.__qualname__}.{name}")

    assert offending == [], (
        "Response schema field(s) use a bare Decimal instead of JsonDecimal "
        f"(app/schemas/common.py): {sorted(offending)}. A bare Decimal on a "
        "response model (ORMModel subclass) serializes to JSON as a string, "
        "but frontend/src/types/api.ts declares these fields `number` -- "
        "swap to JsonDecimal."
    )
