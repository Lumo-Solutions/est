"""Module B/C Phase 5: semantic matching -- score combination (fuzzy +
optional embedding similarity + a bounded precedent adjustment),
suggestion queries (BOQ line -> unlinked takeoff measurements, quotation
line -> its own package's BOQ items), and the continuous-learning feedback
store. See docs/module-b-c-phase5-plan.md for the design this implements.

Deliberately NOT where embeddings get written -- app.integrations.
embeddings::embed_best_effort is the shared degradation-safe embed call,
invoked from each domain's own write path (boq_service.py, takeoff.py,
the quotation-ingestion worker) so this module stays read-side only:
scoring and suggesting, never mutating boq_line_items/drawing_measurements/
quotation_line_items itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import RequestContext
from app.core.enums import AuditAction
from app.core.errors import ValidationAppError
from app.models.boq import BoqLineItem
from app.models.semantic_matching import SemanticMatchFeedback
from app.services import audit

# Fuzzy dominates (a proven, tuned score on real vendor-quote text --
# app.procurement.quotation_matching.MIN_MATCH_SCORE); semantic nudges
# rather than overrides it, since it hasn't been validated against this
# domain's actual documents yet. See plan doc §4.
FUZZY_WEIGHT = 0.6
SEMANTIC_WEIGHT = 0.4

# A single nearest-precedent lookup, not a learned model -- deliberately
# small so a handful of early examples can't swing rankings wildly. See
# plan doc §6.
RAG_MAX_ADJUSTMENT = 0.05

DEFAULT_TOP_K = 5

MATCH_TYPE_BOQ_MEASUREMENT = "boq_measurement"
MATCH_TYPE_QUOTE_BOQ = "quote_boq"
_VALID_MATCH_TYPES = frozenset({MATCH_TYPE_BOQ_MEASUREMENT, MATCH_TYPE_QUOTE_BOQ})
_VALID_OUTCOMES = frozenset({"accepted", "rejected"})


@dataclass(frozen=True, slots=True)
class Suggestion:
    target_id: UUID
    fuzzy_score: float
    semantic_score: float | None
    combined_score: float
    rag_adjustment: float
    final_score: float


def build_measurement_descriptor(*, capability: str, kind: str, layer: str | None, trade_name: str | None) -> str:
    """A DrawingMeasurement has no free-text description of its own (Module
    B Phase 5 -- see the field's own docstring) -- this is a formulaic
    stand-in, not prose, so fuzzy text similarity against a real BOQ
    description will generally score low; the embedding term is expected
    to carry most of the signal for this particular match type."""
    return f"{capability} {kind} layer={layer or 'unknown'} trade={trade_name or 'unclassified'}"


def combine_scores(fuzzy_score: float, semantic_score: float | None) -> float:
    if semantic_score is None:
        return fuzzy_score
    return FUZZY_WEIGHT * fuzzy_score + SEMANTIC_WEIGHT * semantic_score


def cosine_similarity_from_distance(distance: float) -> float:
    """pgvector's `<=>` operator (vector_cosine_ops) returns cosine
    DISTANCE in [0, 2]; similarity = 1 - distance, clamped to [0, 1] so a
    dissimilar/negative-cosine pair never contributes a penalty on top of
    the fuzzy score, only "no extra credit"."""
    return max(0.0, min(1.0, 1.0 - distance))


async def _rag_adjustment(
    session: AsyncSession, project_id: UUID, match_type: str, query_embedding: list[float], target_id: UUID,
) -> float:
    """The single most-similar past feedback row *for this specific
    candidate* (target_id) -- nearest-neighbor among only the feedback rows
    that were ever recorded about this same target, no threshold floor (a
    distant "nearest" scores near enough to zero once scaled that a floor
    would be redundant). Deliberately scoped to target_id, not just
    project/match_type: an unscoped nearest-neighbor lookup would return
    the SAME single globally-nearest feedback row for every candidate
    being scored in one suggestion call, silently starving every other
    candidate's adjustment to zero whenever two candidates happen to share
    (or nearly share) a query embedding -- exactly what happens right
    after a query gets both an accepted and a rejected suggestion in two
    different rounds. No feedback at all for this target contributes
    nothing."""
    nearest = (
        await session.execute(
            select(
                SemanticMatchFeedback.outcome,
                SemanticMatchFeedback.query_embedding.cosine_distance(query_embedding).label("distance"),
            )
            .where(
                SemanticMatchFeedback.project_id == project_id, SemanticMatchFeedback.match_type == match_type,
                SemanticMatchFeedback.target_id == target_id,
            )
            .order_by("distance")
            .limit(1)
        )
    ).first()
    if nearest is None:
        return 0.0
    similarity = cosine_similarity_from_distance(nearest.distance)
    sign = 1.0 if nearest.outcome == "accepted" else -1.0
    return sign * RAG_MAX_ADJUSTMENT * similarity


async def _rank(
    session: AsyncSession, *, project_id: UUID, match_type: str, query_text: str, query_embedding: list[float] | None,
    candidates: list[tuple[UUID, str, list[float] | None]], top_k: int,
) -> list[Suggestion]:
    """`candidates` is (id, text, embedding) triples; shared by both
    suggestion functions below so the scoring/RAG-adjustment logic is
    written exactly once."""
    scored: list[Suggestion] = []
    for target_id, text, embedding in candidates:
        fuzzy_score = fuzz.WRatio(query_text, text) / 100.0
        semantic_score = None
        if query_embedding is not None and embedding is not None:
            # Both sides are L2-normalized (OnnxEmbedder.embed()'s own
            # final step), so the dot product IS cosine similarity
            # directly -- no distance round-trip needed, unlike
            # _rag_adjustment's SQL-side pgvector `<=>` (a real distance
            # operator, where cosine_similarity_from_distance applies).
            dot = sum(a * b for a, b in zip(query_embedding, embedding, strict=True))
            semantic_score = max(0.0, min(1.0, dot))
        combined = combine_scores(fuzzy_score, semantic_score)
        adjustment = (
            await _rag_adjustment(session, project_id, match_type, query_embedding, target_id)
            if query_embedding is not None
            else 0.0
        )
        final = max(0.0, min(1.0, combined + adjustment))
        scored.append(
            Suggestion(
                target_id=target_id, fuzzy_score=fuzzy_score, semantic_score=semantic_score,
                combined_score=combined, rag_adjustment=adjustment, final_score=final,
            )
        )
    scored.sort(key=lambda s: s.final_score, reverse=True)
    return scored[:top_k]


async def suggest_measurements_for_boq_line(
    session: AsyncSession, boq_item: BoqLineItem, top_k: int = DEFAULT_TOP_K,
) -> list[Suggestion]:
    from app.services.boq import list_unlinked_measurements

    unlinked = await list_unlinked_measurements(session, boq_item.project_id)
    if not unlinked:
        return []

    trade_names: dict[UUID, str] = {}
    trade_ids = {m.trade_node_id for m in unlinked if m.trade_node_id is not None}
    if trade_ids:
        from app.models.taxonomy import TradeNode

        rows = (await session.execute(select(TradeNode).where(TradeNode.id.in_(trade_ids)))).scalars().all()
        trade_names = {r.id: r.name for r in rows}

    candidates = [
        (
            m.id,
            build_measurement_descriptor(
                capability=m.capability, kind=m.kind,
                layer=(m.extractor_metadata or {}).get("layer") if m.extractor_metadata else None,
                trade_name=trade_names.get(m.trade_node_id) if m.trade_node_id else None,
            ),
            list(m.descriptor_embedding) if m.descriptor_embedding is not None else None,
        )
        for m in unlinked
    ]
    query_text = f"{boq_item.item_no} {boq_item.description}"
    query_embedding = list(boq_item.description_embedding) if boq_item.description_embedding is not None else None
    return await _rank(
        session, project_id=boq_item.project_id, match_type=MATCH_TYPE_BOQ_MEASUREMENT,
        query_text=query_text, query_embedding=query_embedding, candidates=candidates, top_k=top_k,
    )


async def suggest_boq_for_quotation_line(session: AsyncSession, quote_line, top_k: int = DEFAULT_TOP_K) -> list[Suggestion]:
    from app.models.quotation_ingestion import Quotation
    from app.services.procurement import list_package_boq_items

    quotation = (
        await session.execute(select(Quotation).where(Quotation.id == quote_line.quotation_id))
    ).scalar_one()
    package_items = await list_package_boq_items(session, quotation.package_id)
    if not package_items:
        return []

    candidates = [
        (
            item.id, f"{item.item_no} {item.description}",
            list(item.description_embedding) if item.description_embedding is not None else None,
        )
        for item in package_items
    ]
    query_text = f"{quote_line.vendor_item_text or ''} {quote_line.vendor_description_text or ''}".strip()
    query_embedding = (
        list(quote_line.description_embedding) if quote_line.description_embedding is not None else None
    )
    return await _rank(
        session, project_id=quote_line.project_id, match_type=MATCH_TYPE_QUOTE_BOQ,
        query_text=query_text, query_embedding=query_embedding, candidates=candidates, top_k=top_k,
    )


async def record_feedback(
    session: AsyncSession, ctx: RequestContext, *, project_id: UUID, match_type: str,
    query_embedding: list[float] | None, target_id: UUID, outcome: str,
) -> SemanticMatchFeedback | None:
    """Returns None (records nothing) when the query side has no embedding
    -- there's nothing to re-rank future suggestions BY without one, and a
    row with a NULL/zero vector would be a meaningless "nearest neighbor"
    forever after. Not an error: the caller's own accept/reject action
    (the thing this rides alongside) still succeeds either way."""
    if match_type not in _VALID_MATCH_TYPES:
        raise ValidationAppError(f"Unknown match_type {match_type!r}")
    if outcome not in _VALID_OUTCOMES:
        raise ValidationAppError(f"Unknown outcome {outcome!r}")
    if query_embedding is None:
        return None

    feedback = SemanticMatchFeedback(
        tenant_id=ctx.tenant_id, project_id=project_id, match_type=match_type,
        query_embedding=query_embedding, target_id=target_id, outcome=outcome,
    )
    session.add(feedback)
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.CREATE, entity_type="semantic_match_feedback", entity_id=feedback.id,
        project_id=project_id, payload={"match_type": match_type, "target_id": str(target_id), "outcome": outcome},
    )
    return feedback
