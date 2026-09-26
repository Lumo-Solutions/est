from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel


class SuggestionOut(BaseModel):
    target_id: UUID
    fuzzy_score: float
    semantic_score: float | None
    combined_score: float
    rag_adjustment: float
    final_score: float


class FeedbackCreate(BaseModel):
    match_type: str
    query_embedding_source_id: UUID  # the BOQ line item / quotation line item this suggestion was for
    target_id: UUID
    outcome: str
