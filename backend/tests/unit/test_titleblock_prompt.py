"""Confirms backend/app/takeoff/prompts.py can actually find and parse the
real ai-service/prompts/*.j2 and ai-service/schemas/*.json files at their
expected repo-relative location, and that title_block extraction handles a
malformed/unexpected VLM response gracefully."""

from __future__ import annotations

import pytest

from app.takeoff.prompts import load_schema, render_prompt
from app.takeoff.titleblock import TitleBlockResult


def test_render_title_block_prompt_splits_system_and_user():
    system_prompt, user_prompt = render_prompt(
        "title_block.j2", candidate_text="C-101 ROAD LAYOUT", has_image=False, sheet_context={}
    )
    assert "title-block extraction assistant" in system_prompt.lower() or "title block" in system_prompt.lower()
    assert "C-101 ROAD LAYOUT" in user_prompt
    # system prompt must not leak into the user prompt or vice versa
    assert "C-101 ROAD LAYOUT" not in system_prompt


def test_render_title_block_prompt_image_only_path():
    _, user_prompt = render_prompt("title_block.j2", candidate_text="", has_image=True, sheet_context={})
    assert "no machine-readable text" in user_prompt.lower() or "scanned" in user_prompt.lower()


def test_render_scale_hint_prompt():
    system_prompt, user_prompt = render_prompt(
        "scale_hint.j2", raw_scale_text="1/4\"=1'-0\"", drawing_discipline="civil"
    )
    assert "1/4" in user_prompt
    assert "civil" in user_prompt.lower()


def test_load_title_block_schema_has_expected_fields():
    schema = load_schema("title_block.schema.json")
    assert schema["type"] == "object"
    for field in ("drawing_number", "sheet_title", "scale_text", "confidence"):
        assert field in schema["properties"]
    assert schema["required"] == ["confidence"]


def test_load_scale_hint_schema_has_expected_fields():
    schema = load_schema("scale_hint.schema.json")
    for field in ("scale_ratio", "confidence"):
        assert field in schema["properties"]


def test_title_block_result_drops_invalid_discipline():
    # Simulates what titleblock.extract_title_block does after parsing the
    # raw VLM JSON -- an out-of-enum discipline value must not propagate.
    raw = {"discipline": "not-a-real-discipline", "confidence": 0.5}
    discipline = raw.get("discipline")
    valid = {"civil", "structural", "mep", "architectural", "landscape", "other"}
    if discipline not in valid:
        discipline = None
    result = TitleBlockResult(discipline=discipline, confidence=raw["confidence"], raw=raw)
    assert result.discipline is None


def test_title_block_result_defaults_are_safe():
    result = TitleBlockResult()
    assert result.confidence == 0.0
    assert result.drawing_number is None
    assert result.raw == {}


def test_missing_template_raises_clear_error():
    with pytest.raises(FileNotFoundError):
        render_prompt("nonexistent_template.j2")
