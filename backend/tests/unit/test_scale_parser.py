from __future__ import annotations

import pytest

from app.takeoff.geometry.entities import GeometricEntity
from app.takeoff.scale import (
    PositionedText,
    ScaleSignal,
    dimension_cross_check_signals,
    estimate_scale,
    parse_scale_text,
    scale_bar_signal,
)


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


# --------------------------------------------------------------------------
# Multi-signal fusion (Module B Phase 4a)
# --------------------------------------------------------------------------


def test_estimate_scale_agreement_no_disagreement_flagged() -> None:
    signals = [ScaleSignal(100.0, "title_block_text", 0.95), ScaleSignal(102.0, "scale_bar", 0.65)]
    result = estimate_scale(signals)
    assert result.ratio == 100.0
    assert result.source == "title_block_text"
    assert result.disagreement is False


def test_estimate_scale_disagreement_flagged() -> None:
    signals = [ScaleSignal(100.0, "title_block_text", 0.95), ScaleSignal(500.0, "scale_bar", 0.65)]
    result = estimate_scale(signals)
    assert result.disagreement is True
    assert result.ratio == 100.0  # still reports the highest-confidence signal, never averages


def test_estimate_scale_ignores_low_confidence_signals_for_disagreement() -> None:
    signals = [ScaleSignal(100.0, "title_block_text", 0.95), ScaleSignal(9999.0, "scale_bar", 0.1)]
    result = estimate_scale(signals)
    assert result.disagreement is False  # the low-confidence outlier never counts


def test_estimate_scale_no_usable_signals() -> None:
    result = estimate_scale([ScaleSignal(None, "unknown", 0.0)])
    assert result.ratio is None
    assert result.source == "unknown"
    assert result.disagreement is False


# --------------------------------------------------------------------------
# Dimension cross-check
# --------------------------------------------------------------------------


def test_dimension_cross_check_signal_from_explicit_override_text() -> None:
    entity = GeometricEntity(
        "dimension", "DIM", "h1", [(0.0, 0.0), (10.0, 0.0)], attributes={"stated_length": "5.0"}
    )
    signals = dimension_cross_check_signals([entity])
    assert len(signals) == 1
    assert signals[0].ratio == pytest.approx(0.5)
    assert signals[0].source == "dimension_cross_check"


def test_dimension_cross_check_skips_auto_text() -> None:
    entity = GeometricEntity("dimension", "DIM", "h1", [(0.0, 0.0), (10.0, 0.0)], attributes={"stated_length": "<>"})
    assert dimension_cross_check_signals([entity]) == []


def test_dimension_cross_check_ignores_non_dimension_entities() -> None:
    entity = GeometricEntity("line", "C-ROAD", "h1", [(0.0, 0.0), (10.0, 0.0)])
    assert dimension_cross_check_signals([entity]) == []


# --------------------------------------------------------------------------
# Scale-bar detection
# --------------------------------------------------------------------------


def test_scale_bar_signal_detects_evenly_spaced_ticks_and_labels() -> None:
    baseline = GeometricEntity("line", "SCALE-BAR", "b", [(0.0, 0.0), (100.0, 0.0)])
    ticks = [
        GeometricEntity("line", "SCALE-BAR", f"t{i}", [(x, 0.0), (x, 5.0)])
        for i, x in enumerate((0.0, 50.0, 100.0))
    ]
    texts = [PositionedText("0", 0.0, 10.0), PositionedText("10", 50.0, 10.0), PositionedText("20", 100.0, 10.0)]

    result = scale_bar_signal([baseline, *ticks], texts)
    assert result is not None
    assert result.ratio == pytest.approx(0.2)  # 10 real-unit step / 50 drawing-unit spacing
    assert result.source == "scale_bar"


def test_scale_bar_signal_none_when_no_matching_shape() -> None:
    lines = [GeometricEntity("line", "C-ROAD", "h1", [(0.0, 0.0), (10.0, 3.0)])]
    texts = [PositionedText("Revision B", 0.0, 0.0)]
    assert scale_bar_signal(lines, texts) is None


def test_scale_bar_signal_none_when_ticks_unevenly_spaced() -> None:
    baseline = GeometricEntity("line", "SCALE-BAR", "b", [(0.0, 0.0), (100.0, 0.0)])
    ticks = [
        GeometricEntity("line", "SCALE-BAR", f"t{i}", [(x, 0.0), (x, 5.0)])
        for i, x in enumerate((0.0, 20.0, 100.0))  # not evenly spaced
    ]
    texts = [PositionedText("0", 0.0, 10.0), PositionedText("10", 20.0, 10.0), PositionedText("20", 100.0, 10.0)]
    assert scale_bar_signal([baseline, *ticks], texts) is None
