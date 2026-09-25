"""Matches an LLM-extracted vendor line (raw item text/description) back to
one of the RFQ's own BOQ line items -- deliberately NOT something the
vision-LLM decides (see app/procurement/quotation_extraction.py's schema,
which has no boq_line_item_id field at all). Fuzzy text matching only;
embedding/pgvector-based semantic matching is a fast-follow, not required
for this slice (SRS C2 plan default #4)."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from rapidfuzz import fuzz

from app.core.enums import LineItemMatchMethod

# Below this score (rapidfuzz WRatio / 100) a match is not trusted at all --
# the line item is created with boq_line_item_id=None, source=llm,
# match_method=None, and confidence set to the (low) match score so a
# reviewer sees exactly how uncertain the mapping is and matches it
# manually.
MIN_MATCH_SCORE = 0.72


@dataclass(frozen=True, slots=True)
class MatchCandidate:
    boq_line_item_id: UUID
    item_no: str
    description: str


@dataclass(frozen=True, slots=True)
class MatchResult:
    boq_line_item_id: UUID | None
    score: float
    match_method: str | None


def _candidate_text(candidate: MatchCandidate) -> str:
    return f"{candidate.item_no} {candidate.description}".strip()


def match_line_item(
    *, vendor_item_text: str | None, vendor_description_text: str, candidates: list[MatchCandidate]
) -> MatchResult:
    if not candidates:
        return MatchResult(boq_line_item_id=None, score=0.0, match_method=None)

    query = f"{vendor_item_text or ''} {vendor_description_text}".strip()
    scored = [(candidate, fuzz.WRatio(query, _candidate_text(candidate)) / 100.0) for candidate in candidates]
    best_candidate, best_score = max(scored, key=lambda pair: pair[1])

    if best_score >= MIN_MATCH_SCORE:
        return MatchResult(boq_line_item_id=best_candidate.boq_line_item_id, score=best_score, match_method=LineItemMatchMethod.FUZZY.value)
    return MatchResult(boq_line_item_id=None, score=best_score, match_method=None)
