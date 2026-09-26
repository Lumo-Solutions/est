from __future__ import annotations

from dataclasses import asdict
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_session, require_roles
from app.core.context import RequestContext
from app.core.enums import Role
from app.core.errors import ValidationAppError
from app.schemas.semantic_matching import FeedbackCreate, SuggestionOut
from app.services import boq as boq_service
from app.services import quotation_ingestion as quotation_service
from app.services import semantic_matching as semantic_matching_service

router = APIRouter(tags=["semantic-matching"])

# Suggestions are read-only (CurrentUser, project-visibility via RLS on the
# underlying queries) -- a suggestion list is not itself a mutation, same
# reasoning as GET .../measurements. Feedback rides alongside whichever
# existing accept/reject action the reviewer already takes, so it reuses
# that action's own role tier -- the operational estimator+ set every
# other Module B/C write already uses.
_FEEDBACK_ROLES = (
    Role.ESTIMATOR.value, Role.LEAD_ESTIMATOR.value, Role.PROCUREMENT_HEAD.value,
    Role.BD_DIRECTOR.value, Role.MANAGING_DIRECTOR.value,
)


@router.get("/boq-line-items/{item_id}/measurement-suggestions", response_model=list[SuggestionOut])
async def suggest_measurements_endpoint(
    item_id: UUID, top_k: int = 5, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session),
) -> list[SuggestionOut]:
    item = await boq_service.get_line_item(session, ctx, item_id)
    suggestions = await semantic_matching_service.suggest_measurements_for_boq_line(session, item, top_k=top_k)
    return [SuggestionOut(**asdict(s)) for s in suggestions]


@router.get("/quotation-line-items/{item_id}/boq-suggestions", response_model=list[SuggestionOut])
async def suggest_boq_for_quotation_line_endpoint(
    item_id: UUID, top_k: int = 5, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session),
) -> list[SuggestionOut]:
    quote_line = await quotation_service.get_line_item(session, item_id)
    suggestions = await semantic_matching_service.suggest_boq_for_quotation_line(session, quote_line, top_k=top_k)
    return [SuggestionOut(**asdict(s)) for s in suggestions]


@router.post("/semantic-matching/feedback", status_code=201)
async def record_feedback_endpoint(
    data: FeedbackCreate,
    ctx: RequestContext = Depends(require_roles(*_FEEDBACK_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    if data.match_type == semantic_matching_service.MATCH_TYPE_BOQ_MEASUREMENT:
        source = await boq_service.get_line_item(session, ctx, data.query_embedding_source_id)
        project_id = source.project_id
        query_embedding = list(source.description_embedding) if source.description_embedding is not None else None
    elif data.match_type == semantic_matching_service.MATCH_TYPE_QUOTE_BOQ:
        source = await quotation_service.get_line_item(session, data.query_embedding_source_id)
        project_id = source.project_id
        query_embedding = list(source.description_embedding) if source.description_embedding is not None else None
    else:
        raise ValidationAppError(f"Unknown match_type {data.match_type!r}")

    feedback = await semantic_matching_service.record_feedback(
        session, ctx, project_id=project_id, match_type=data.match_type, query_embedding=query_embedding,
        target_id=data.target_id, outcome=data.outcome,
    )
    return {"recorded": feedback is not None, "id": str(feedback.id) if feedback else None}
