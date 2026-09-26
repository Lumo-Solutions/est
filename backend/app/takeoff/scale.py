"""Scale-text parsing and multi-signal scale fusion (Module B Phase 4a --
see docs/module-b-phase4-plan.md §4a).

`parse_scale_text()` is pure (no DB/network) -- see
backend/tests/unit/test_scale_parser.py. Handles the handful of conventions
that actually show up on tender drawings: ratio scales ("1:100", "1 : 50"),
imperial architectural scales ('1/4"=1\\'-0"', '3/8" = 1\\'-0"'), and the
"not to scale" family.

`disambiguate_via_vlm()` is a network-calling fallback used only when the
regex parser can't confidently resolve a string; see its docstring.

Ratio convention throughout this module: `ratio` is the "N" in a "1:N"
scale -- real_world_length = drawing_length * ratio (matches
parse_scale_text()'s own imperial-scale arithmetic, `real_inches /
drawing_inches`).

The two other signals below both work in **vector space** (already-
extracted entity/text coordinates), never against a rasterized image --
consistent with this being vector extraction throughout, and avoiding a
much larger image-CV dependency:

- `dimension_cross_check_signals()`: DXF only for now -- a DIMENSION
  entity with an explicit (non-auto) text override states a real-world
  length a human would read directly off the drawing; paired with the
  geometric distance between its own definition points, that's a genuine
  scale candidate. PDF has no DIMENSION objects, and correlating a
  numeric text label with "the line it's dimensioning" from position
  alone is a real, separate piece of work -- deliberately deferred rather
  than rushed; see docs/build-log.md's Phase 4a section.
- `scale_bar_signal()`: works for either source, since both already
  produce the same `GeometricEntity`/text shapes -- looks for a baseline
  line carrying evenly-spaced short perpendicular ticks, paired with
  nearby text forming an arithmetic sequence.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from app.takeoff.geometry.entities import GeometricEntity

_RATIO_PATTERN = re.compile(r"^\s*1\s*[:/]\s*(\d+(?:\.\d+)?)\s*$")
_NTS_PATTERN = re.compile(r"\b(N\.?T\.?S\.?|NOT\s+TO\s+SCALE|AS\s+SHOWN)\b", re.IGNORECASE)
_IMPERIAL_PATTERN = re.compile(
    r"""(?P<num>\d+)\s*/\s*(?P<den>\d+)\s*["”]?\s*=\s*(?P<feet>\d+)\s*['’]\s*-?\s*(?P<inches>\d+)?\s*["”]?""",
    re.VERBOSE,
)


@dataclass(frozen=True, slots=True)
class ScaleResult:
    ratio: float | None
    source: str  # title_block_text | unknown
    confidence: float


def parse_scale_text(text: str | None) -> ScaleResult:
    if not text:
        return ScaleResult(None, "unknown", 0.0)

    text = text.strip()

    if _NTS_PATTERN.search(text):
        return ScaleResult(None, "title_block_text", 0.0)

    ratio_match = _RATIO_PATTERN.match(text)
    if ratio_match:
        denominator = float(ratio_match.group(1))
        return ScaleResult(denominator, "title_block_text", 0.95)

    imperial_match = _IMPERIAL_PATTERN.search(text)
    if imperial_match:
        num = float(imperial_match.group("num"))
        den = float(imperial_match.group("den"))
        feet = float(imperial_match.group("feet"))
        inches = float(imperial_match.group("inches") or 0)
        drawing_inches = num / den
        real_inches = feet * 12 + inches
        if drawing_inches > 0:
            return ScaleResult(real_inches / drawing_inches, "title_block_text", 0.9)

    # Loose fallback: "SCALE 1:250" or "SC 1/200" embedded in a longer string.
    loose = re.search(r"1\s*[:/]\s*(\d+(?:\.\d+)?)", text)
    if loose:
        return ScaleResult(float(loose.group(1)), "title_block_text", 0.6)

    return ScaleResult(None, "unknown", 0.0)


async def disambiguate_via_vlm(raw_scale_text: str, discipline: str | None = None) -> ScaleResult:
    """Fallback for scale text the regex parser above can't confidently
    resolve (confidence == 0.0) -- asks the VLM to interpret it. Only called
    when parse_scale_text() alone isn't enough; see
    workers/tasks/takeoff.py::extract_sheet."""
    from app.integrations.vllm import extract_json
    from app.takeoff.prompts import load_schema, render_prompt

    system_prompt, user_prompt = render_prompt(
        "scale_hint.j2", raw_scale_text=raw_scale_text, drawing_discipline=discipline
    )
    schema = load_schema("scale_hint.schema.json")
    raw = await extract_json(system_prompt=system_prompt, user_prompt=user_prompt, json_schema=schema)
    ratio = raw.get("scale_ratio")
    confidence = float(raw.get("confidence") or 0.0)
    return ScaleResult(float(ratio) if ratio is not None else None, "title_block_text", confidence)


# --------------------------------------------------------------------------
# Multi-signal fusion
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ScaleSignal:
    ratio: float | None
    source: str  # title_block_text | dimension_cross_check | scale_bar | units_fallback | vlm
    confidence: float


@dataclass(frozen=True, slots=True)
class ScaleEstimate:
    ratio: float | None
    source: str
    confidence: float
    disagreement: bool
    signals: list[ScaleSignal] = field(default_factory=list)


def estimate_scale(signals: list[ScaleSignal]) -> ScaleEstimate:
    """Combines every usable signal into one estimate: the highest-
    confidence signal wins the reported ratio/source, but `disagreement`
    is set whenever two signals both confident enough to trust (>=0.5)
    disagree by more than 10% -- surfaced to a reviewer rather than
    silently resolved. Never averages ratios together (a 1:100 and a
    1:500 signal averaging to 1:300 would be a real number that's wrong
    in every possible interpretation)."""
    usable = [s for s in signals if s.ratio is not None and s.ratio > 0 and s.confidence > 0]
    if not usable:
        return ScaleEstimate(None, "unknown", 0.0, False, signals)

    best = max(usable, key=lambda s: s.confidence)
    strong = [s for s in usable if s.confidence >= 0.5]
    disagreement = any(
        abs(a.ratio - b.ratio) / max(a.ratio, b.ratio) > 0.10
        for i, a in enumerate(strong)
        for b in strong[i + 1 :]
    )
    return ScaleEstimate(best.ratio, best.source, best.confidence, disagreement, signals)


# --------------------------------------------------------------------------
# Dimension-text-vs-measured-length (DXF only -- see module docstring)
# --------------------------------------------------------------------------


def dimension_cross_check_signals(entities: list[GeometricEntity]) -> list[ScaleSignal]:
    """entities carrying entity_type="dimension" (app.takeoff.dxf.
    index_dxf_geometry) with an explicit stated_length attribute -- an
    auto ("<>") dimension text is skipped entirely (see module
    docstring: its displayed value already depends on the dimension
    style's own scale factor, which this deliberately doesn't resolve)."""
    signals: list[ScaleSignal] = []
    for entity in entities:
        if entity.entity_type != "dimension" or len(entity.vertices) != 2:
            continue
        stated_text = entity.attributes.get("stated_length")
        try:
            stated = float(stated_text)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        (x1, y1), (x2, y2) = entity.vertices
        drawing_dist = math.hypot(x2 - x1, y2 - y1)
        if drawing_dist <= 0 or stated <= 0:
            continue
        signals.append(ScaleSignal(ratio=stated / drawing_dist, source="dimension_cross_check", confidence=0.7))
    return signals


# --------------------------------------------------------------------------
# Scale-bar detection (vector space -- works for DXF or PDF entities/text)
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PositionedText:
    value: str
    x: float
    y: float


def scale_bar_signal(
    entities: list[GeometricEntity], texts: list[PositionedText], *, tolerance: float = 0.15
) -> ScaleSignal | None:
    """Looks for a baseline line carrying several short, roughly-
    perpendicular tick lines starting at evenly-spaced points along it,
    paired with nearby text forming an arithmetic sequence (0, x, 2x,
    ...) -- a real, common scale-bar shape. Deliberately modest: the
    first baseline candidate producing >=3 evenly-spaced ticks AND >=3
    evenly-stepped numeric labels wins; anything messier is left
    undetected rather than guessed at."""
    lines = [e for e in entities if e.entity_type == "line" and len(e.vertices) == 2]

    numeric_values = sorted(_as_float(t.value) for t in texts if _as_float(t.value) is not None)
    if len(numeric_values) < 3:
        return None
    label_steps = [b - a for a, b in zip(numeric_values, numeric_values[1:], strict=False)]
    avg_step = sum(label_steps) / len(label_steps)
    if avg_step <= 0 or any(abs(s - avg_step) > avg_step * tolerance for s in label_steps):
        return None

    for baseline in lines:
        (bx1, by1), (bx2, by2) = baseline.vertices
        blen = math.hypot(bx2 - bx1, by2 - by1)
        if blen <= 0:
            continue
        bdx, bdy = (bx2 - bx1) / blen, (by2 - by1) / blen

        tick_positions: list[float] = []
        for other in lines:
            if other is baseline:
                continue
            (ox1, oy1), (ox2, oy2) = other.vertices
            olen = math.hypot(ox2 - ox1, oy2 - oy1)
            if olen <= 0 or olen > blen * 0.25:  # a tick is short relative to the baseline
                continue
            odx, ody = (ox2 - ox1) / olen, (oy2 - oy1) / olen
            if abs(odx * bdx + ody * bdy) > 0.2:  # not roughly perpendicular to the baseline
                continue
            t = (ox1 - bx1) * bdx + (oy1 - by1) * bdy  # projection onto the baseline
            if -tolerance * blen <= t <= blen * (1 + tolerance):
                tick_positions.append(t)

        if len(tick_positions) < 3:
            continue
        tick_positions.sort()
        spacings = [b - a for a, b in zip(tick_positions, tick_positions[1:], strict=False)]
        avg_spacing = sum(spacings) / len(spacings)
        if avg_spacing <= 0 or any(abs(s - avg_spacing) > avg_spacing * tolerance for s in spacings):
            continue

        return ScaleSignal(ratio=avg_step / avg_spacing, source="scale_bar", confidence=0.65)

    return None


def _as_float(value: str) -> float | None:
    try:
        return float(value.strip())
    except (ValueError, AttributeError):
        return None
