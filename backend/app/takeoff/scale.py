"""Scale-text parsing.

`parse_scale_text()` is pure (no DB/network) -- see
backend/tests/unit/test_scale_parser.py. Handles the handful of conventions
that actually show up on tender drawings: ratio scales ("1:100", "1 : 50"),
imperial architectural scales ('1/4"=1\\'-0"', '3/8" = 1\\'-0"'), and the
"not to scale" family. Dimension-entity cross-checking and scale-bar image
detection are the two remaining multi-signal-fusion slots (see
docs/takeoff-pipeline.md) -- not implemented in this slice.

`disambiguate_via_vlm()` is a network-calling fallback used only when the
regex parser can't confidently resolve a string; see its docstring.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

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
