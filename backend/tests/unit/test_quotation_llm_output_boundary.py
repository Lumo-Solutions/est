"""SRS requirement #3: the vision-LLM only extracts into a strict JSON
schema, and nothing it returns can trigger any action (sending mail,
changing status, approving anything). See
app/procurement/quotation_extraction.py and
ai-service/schemas/quotation_extraction.schema.json."""

from __future__ import annotations

import json
from pathlib import Path

from app.procurement.quotation_extraction import ExtractedExclusion, ExtractedLineItem, QuotationExtractionResult

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[3] / "ai-service" / "schemas" / "quotation_extraction.schema.json"
)
_FORBIDDEN_FIELD_SUBSTRINGS = ("action", "status", "approve", "send", "boq_line_item_id", "email", "role", "token")


def _all_property_names(schema: dict) -> set[str]:
    names: set[str] = set()

    def _walk(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "properties" and isinstance(value, dict):
                    names.update(value.keys())
                _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(schema)
    return names


def test_schema_has_no_field_that_could_name_an_action_or_a_boq_line_item():
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    names = _all_property_names(schema)
    for forbidden in _FORBIDDEN_FIELD_SUBSTRINGS:
        matches = {n for n in names if forbidden in n.lower()}
        assert not matches, f"schema field(s) {matches} could be mistaken for an actionable field (matched {forbidden!r})"


def test_schema_forbids_additional_properties_at_every_object_level():
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))

    def _walk(node: object) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node.get("additionalProperties") is False, f"object schema missing additionalProperties: false: {node.get('description', node)}"
            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(schema)


def test_pydantic_models_only_carry_extraction_fields():
    assert set(ExtractedLineItem.model_fields) == {
        "vendor_item_text", "vendor_description_text", "unit_price", "quantity", "extended_price_stated", "remarks_text",
    }
    assert set(ExtractedExclusion.model_fields) == {"flag_text", "source_quote_text"}
    assert set(QuotationExtractionResult.model_fields) == {
        "currency", "vat_inclusive", "line_items", "exclusions", "confidence",
    }


def test_a_malicious_extra_field_in_the_llm_response_is_silently_dropped_not_acted_on():
    """Simulates a compromised/hallucinating vLLM response that includes
    fields outside the guided-JSON schema (guided decoding should prevent
    this, but this is defense in depth) -- validation must never raise on
    unexpected keys, and the extra data must never surface on the model."""
    raw = {
        "currency": "AED",
        "vat_inclusive": None,
        "line_items": [
            {
                "vendor_description_text": "Excavation",
                "action": "mark_rfq_accepted",
                "boq_line_item_id": "11111111-1111-1111-1111-111111111111",
            }
        ],
        "exclusions": [],
        "confidence": 0.9,
        "send_email_to": "attacker@example.com",
    }
    result = QuotationExtractionResult.model_validate(raw)
    assert not hasattr(result, "send_email_to")
    assert not hasattr(result.line_items[0], "action")
    assert not hasattr(result.line_items[0], "boq_line_item_id")
    assert result.line_items[0].vendor_description_text == "Excavation"
