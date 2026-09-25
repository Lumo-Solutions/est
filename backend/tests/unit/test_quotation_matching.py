from __future__ import annotations

import uuid

from app.procurement.quotation_matching import MatchCandidate, match_line_item

_ID_1 = uuid.uuid4()
_ID_2 = uuid.uuid4()
_CANDIDATES = [
    MatchCandidate(boq_line_item_id=_ID_1, item_no="1.0", description="Excavation to formation level"),
    MatchCandidate(boq_line_item_id=_ID_2, item_no="1.1", description="Disposal of excavated material off site"),
]


def test_matches_near_identical_text_with_high_confidence():
    result = match_line_item(vendor_item_text="1.0", vendor_description_text="Excavation to formation level", candidates=_CANDIDATES)
    assert result.boq_line_item_id == _ID_1
    assert result.match_method == "fuzzy"
    assert result.score > 0.9


def test_matches_slightly_reworded_text():
    result = match_line_item(vendor_item_text=None, vendor_description_text="Excavate to formation level (bulk)", candidates=_CANDIDATES)
    assert result.boq_line_item_id == _ID_1


def test_unrelated_text_does_not_force_a_match():
    result = match_line_item(vendor_item_text=None, vendor_description_text="Supply and install fire extinguishers", candidates=_CANDIDATES)
    assert result.boq_line_item_id is None
    assert result.match_method is None


def test_no_candidates_returns_no_match():
    result = match_line_item(vendor_item_text="1.0", vendor_description_text="Excavation", candidates=[])
    assert result.boq_line_item_id is None
    assert result.score == 0.0
