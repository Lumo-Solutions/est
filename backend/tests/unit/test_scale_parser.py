from __future__ import annotations

import pytest

from app.takeoff.scale import parse_scale_text


@pytest.mark.parametrize(
    ("text", "expected_ratio"),
    [
        ("1:100", 100.0),
        ("1 : 50", 50.0),
        ("1/200", 200.0),
    ],
)
def test_parse_ratio_scale(text: str, expected_ratio: float) -> None:
    result = parse_scale_text(text)
    assert result.ratio == expected_ratio
    assert result.source == "title_block_text"
    assert result.confidence >= 0.9


@pytest.mark.parametrize("text", ["NTS", "N.T.S.", "Not To Scale", "AS SHOWN", "as shown"])
def test_parse_not_to_scale_variants(text: str) -> None:
    result = parse_scale_text(text)
    assert result.ratio is None
    assert result.confidence == 0.0


def test_parse_imperial_architectural_scale() -> None:
    result = parse_scale_text('1/4"=1\'-0"')
    assert result.ratio == pytest.approx(48.0)
    assert result.confidence >= 0.85


def test_parse_imperial_scale_with_inches() -> None:
    # 1/8" = 1'-6" -> real inches = 18, drawing inches = 0.125 -> ratio = 144
    result = parse_scale_text('1/8"=1\'-6"')
    assert result.ratio == pytest.approx(144.0)


def test_parse_embedded_scale_in_longer_string() -> None:
    result = parse_scale_text("SCALE 1:250 @ A1")
    assert result.ratio == 250.0
    assert result.confidence == 0.6


def test_parse_none_and_empty() -> None:
    assert parse_scale_text(None).ratio is None
    assert parse_scale_text("").ratio is None
    assert parse_scale_text("   ").confidence == 0.0


def test_parse_garbage_text_returns_unknown() -> None:
    result = parse_scale_text("REVISION B")
    assert result.ratio is None
    assert result.source == "unknown"
