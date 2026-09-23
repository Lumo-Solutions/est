"""Contract tests for ai-service/ prompt templates and JSON schemas.

Dependency-light on purpose: this suite only needs jinja2 + pytest (see
requirements-test.txt) and must not depend on the backend's environment, so
prompt/schema regressions are caught even before the backend package is
installed. Run with:

    pip install -r ai-service/tests/requirements-test.txt
    pytest ai-service/tests
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader

AI_SERVICE_DIR = Path(__file__).resolve().parent.parent
PROMPTS_DIR = AI_SERVICE_DIR / "prompts"
SCHEMAS_DIR = AI_SERVICE_DIR / "schemas"

_env = Environment(loader=FileSystemLoader(str(PROMPTS_DIR)), keep_trailing_newline=True)


TITLE_BLOCK_FIELDS = [
    "drawing_number",
    "sheet_title",
    "revision",
    "issue_date",
    "discipline",
    "scale_text",
    "project_name",
    "client_name",
    "confidence",
]

SCALE_HINT_FIELDS = ["scale_ratio", "unit_system", "confidence", "reasoning"]


# --------------------------------------------------------------------------- #
# title_block.j2
# --------------------------------------------------------------------------- #


def _render_title_block(**overrides):
    template = _env.get_template("title_block.j2")
    ctx = {
        "candidate_text": "DWG NO: C-101   SCALE: 1:100   REV: B",
        "has_image": False,
        "sheet_context": {"discipline_hint": "civil", "project_name": "Demo Project"},
    }
    ctx.update(overrides)
    return template.render(**ctx)


def test_title_block_renders_with_text_only():
    rendered = _render_title_block()
    assert rendered.strip(), "rendered prompt should not be empty"
    for field in TITLE_BLOCK_FIELDS:
        assert field in rendered, f"expected field name {field!r} to appear in the rendered prompt"
    assert "DWG NO: C-101" in rendered
    assert "civil" in rendered


def test_title_block_renders_with_image_and_no_text():
    rendered = _render_title_block(candidate_text="", has_image=True, sheet_context=None)
    assert rendered.strip()
    assert "image" in rendered.lower()
    assert "No machine-readable text" in rendered


def test_title_block_renders_with_minimal_context():
    rendered = _render_title_block(candidate_text="", has_image=False, sheet_context=None)
    assert rendered.strip()
    for field in TITLE_BLOCK_FIELDS:
        assert field in rendered


# --------------------------------------------------------------------------- #
# scale_hint.j2
# --------------------------------------------------------------------------- #


def _render_scale_hint(**overrides):
    template = _env.get_template("scale_hint.j2")
    ctx = {"raw_scale_text": "1:100", "drawing_discipline": "civil"}
    ctx.update(overrides)
    return template.render(**ctx)


def test_scale_hint_renders_with_context():
    rendered = _render_scale_hint()
    assert rendered.strip()
    for field in SCALE_HINT_FIELDS:
        assert field in rendered
    assert "1:100" in rendered
    assert "civil" in rendered


def test_scale_hint_renders_without_discipline():
    rendered = _render_scale_hint(drawing_discipline=None)
    assert rendered.strip()
    assert '1/4"=1\'-0"' in rendered or "1/4" in rendered  # example remains in system instructions
    for field in SCALE_HINT_FIELDS:
        assert field in rendered


def test_scale_hint_handles_nts():
    rendered = _render_scale_hint(raw_scale_text="NTS")
    assert "NTS" in rendered


# --------------------------------------------------------------------------- #
# JSON Schemas
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "filename,expected_fields",
    [
        ("title_block.schema.json", TITLE_BLOCK_FIELDS),
        ("scale_hint.schema.json", SCALE_HINT_FIELDS),
    ],
)
def test_schema_is_valid_json_object_schema(filename, expected_fields):
    path = SCHEMAS_DIR / filename
    assert path.exists(), f"missing schema file: {path}"

    with path.open("r", encoding="utf-8") as f:
        schema = json.load(f)

    assert schema.get("type") == "object"
    assert "properties" in schema
    assert schema.get("additionalProperties") is False

    for field in expected_fields:
        assert field in schema["properties"], f"schema {filename} missing property {field!r}"

    assert "confidence" in schema.get("required", []), (
        f"schema {filename} should require 'confidence' at minimum"
    )
