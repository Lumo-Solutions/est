"""Module B/C Phase 5: suggestion ranking against real pgvector columns,
RAG re-ranking from recorded feedback, and degradation to fuzzy-only when
an embedding is missing. Uses a small deterministic hash-based fixture
embedder (never the real ONNX model, which isn't available in CI either)
so cosine similarity between two texts is genuinely governed by shared
words -- monkeypatched over app.integrations.embeddings.get_embedder,
which embed_best_effort() (the only thing every write path here calls)
resolves at call time, so every service module's embedding writes go
through this same fixture regardless of which one calls it.
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import RequestContext
from app.core.enums import QuotationExtractionMethod, QuotationLineItemStatus, QuotationStatus
from app.core.errors import NotFoundError
from app.db.rls import set_rls_context
from app.integrations import embeddings as embeddings_module
from app.models.procurement import ProcurementPackageItem
from app.models.quotation_ingestion import Quotation, QuotationLineItem
from app.models.semantic_matching import SemanticMatchFeedback
from app.models.takeoff import Drawing, DrawingMeasurement, DrawingSheet
from app.schemas.boq import BoqLineItemCreate
from app.services import boq as boq_service
from app.services import semantic_matching as semantic_matching_service

pytestmark = pytest.mark.asyncio

_MEMBER_USER_ID = uuid.UUID("00000000-0000-0000-0000-0000000000f5")
_NON_MEMBER_USER_ID = uuid.UUID("00000000-0000-0000-0000-0000000000f6")
_DIM = 384


class _HashFixtureEmbedder:
    """Deterministic, no model file: each word hashes into one of _DIM
    buckets, summed and L2-normalized -- two texts sharing words score a
    positive cosine similarity, texts sharing none score ~0. Good enough
    to make ranking assertions meaningful without a real model."""

    model_name = "fixture-hash-embedder"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    @staticmethod
    def _embed_one(text_value: str) -> list[float]:
        vec = [0.0] * _DIM
        for word in text_value.lower().split():
            vec[hash(word) % _DIM] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


def _force_fixture_embedder(monkeypatch) -> None:
    monkeypatch.setattr(embeddings_module, "get_embedder", lambda: _HashFixtureEmbedder())


def _ctx(roles: frozenset[str], *, tenant_id: uuid.UUID, is_system: bool = False, user_id: uuid.UUID | None = None) -> RequestContext:
    user_id = user_id or uuid.uuid4()
    return RequestContext(tenant_id=tenant_id, user_id=user_id, sub=str(user_id), roles=roles, is_system=is_system)


async def _seed_project(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    tenant_id = uuid.uuid4()
    await session.execute(
        text("INSERT INTO tenants (id, slug, name) VALUES (:id, :slug, :name)"),
        {"id": str(tenant_id), "slug": f"acme-{uuid.uuid4().hex[:8]}", "name": "Acme"},
    )
    sys_ctx = _ctx(frozenset(), tenant_id=tenant_id, is_system=True)
    await set_rls_context(session, sys_ctx)
    project_id = (
        await session.execute(
            text("INSERT INTO projects (tenant_id, code, name) VALUES (:t, :c, 'A') RETURNING id"),
            {"t": str(tenant_id), "c": f"P5-{uuid.uuid4().hex[:8]}"},
        )
    ).scalar_one()
    await session.execute(
        text("INSERT INTO project_members (project_id, user_id, tenant_id) VALUES (:p, :u, :t)"),
        {"p": str(project_id), "u": str(_MEMBER_USER_ID), "t": str(tenant_id)},
    )
    return tenant_id, project_id


async def _seed_measurement(
    session: AsyncSession, tenant_id: uuid.UUID, project_id: uuid.UUID, *, capability: str, kind: str, layer: str,
) -> DrawingMeasurement:
    drawing = Drawing(
        tenant_id=tenant_id, project_id=project_id, original_filename="d.dxf", kind="dxf",
        bucket="installtec-drawings", object_key=f"x-{uuid.uuid4().hex}", size_bytes=1,
        sha256=uuid.uuid4().hex + uuid.uuid4().hex,  # 64 hex chars, unique per call
    )
    session.add(drawing)
    await session.flush()
    sheet = DrawingSheet(tenant_id=tenant_id, drawing_id=drawing.id, project_id=project_id, sheet_index=0, units="m")
    session.add(sheet)
    await session.flush()
    descriptor = semantic_matching_service.build_measurement_descriptor(
        capability=capability, kind=kind, layer=layer, trade_name=None,
    )
    embeddings = embeddings_module.embed_best_effort([descriptor])
    embedding = embeddings[0] if embeddings is not None else None
    measurement = DrawingMeasurement(
        tenant_id=tenant_id, drawing_id=drawing.id, sheet_id=sheet.id, project_id=project_id,
        capability=capability, kind=kind, value=Decimal("10.0"), unit="m", confidence=Decimal("1.0"),
        source_entity_ids=[], extractor_metadata={"layer": layer}, descriptor_embedding=embedding,
    )
    session.add(measurement)
    await session.flush()
    return measurement


async def _seed_quotation_line(
    session: AsyncSession, tenant_id: uuid.UUID, project_id: uuid.UUID, *, package_id: uuid.UUID, vendor_text: str,
) -> QuotationLineItem:
    vendor_id = (
        await session.execute(
            text(
                "INSERT INTO vendors (tenant_id, legal_name, normalized_name, status, primary_email) "
                "VALUES (:t, 'V', 'v', 'active', 'v@example.com') RETURNING id"
            ),
            {"t": str(tenant_id)},
        )
    ).scalar_one()
    rfq_id = (
        await session.execute(
            text(
                "INSERT INTO rfqs (tenant_id, package_id, project_id, vendor_id, status, reply_token) "
                "VALUES (:t, :pkg, :p, :v, 'sent', :tok) RETURNING id"
            ),
            {"t": str(tenant_id), "pkg": str(package_id), "p": str(project_id), "v": str(vendor_id), "tok": f"tok-{uuid.uuid4().hex}"},
        )
    ).scalar_one()
    quotation = Quotation(
        tenant_id=tenant_id, rfq_id=rfq_id, vendor_id=vendor_id, package_id=package_id, project_id=project_id,
        extraction_method=QuotationExtractionMethod.DETERMINISTIC_XLSX.value, version_no=1, is_current=True,
        currency="AED", vat_inclusive=True, submitted_at=datetime.now(timezone.utc), status=QuotationStatus.PROPOSED.value,
    )
    session.add(quotation)
    await session.flush()
    embeddings = embeddings_module.embed_best_effort([vendor_text])
    embedding = embeddings[0] if embeddings is not None else None
    line_item = QuotationLineItem(
        tenant_id=tenant_id, quotation_id=quotation.id, project_id=project_id,
        vendor_description_text=vendor_text, confidence=Decimal("1.0"), source="deterministic",
        status=QuotationLineItemStatus.PROPOSED.value, description_embedding=embedding,
    )
    session.add(line_item)
    await session.flush()
    return line_item


# --------------------------------------------------------------------------
# BOQ line -> takeoff measurement suggestions
# --------------------------------------------------------------------------


async def test_suggest_measurements_ranks_the_semantically_closer_one_first(rls_session, monkeypatch):
    _force_fixture_embedder(monkeypatch)
    tenant_id, project_id = await _seed_project(rls_session)
    sys_ctx = _ctx(frozenset(), tenant_id=tenant_id, is_system=True)
    await set_rls_context(rls_session, sys_ctx)

    close = await _seed_measurement(rls_session, tenant_id, project_id, capability="alignment", kind="alignment_length_m", layer="ROAD-CL")
    far = await _seed_measurement(rls_session, tenant_id, project_id, capability="volume", kind="trench_volume_m3", layer="DRAIN-PIPE")

    member_ctx = _ctx(frozenset({"lead_estimator"}), tenant_id=tenant_id, user_id=_MEMBER_USER_ID)
    await set_rls_context(rls_session, member_ctx)
    boq_item = await boq_service.create_line_item(
        rls_session, member_ctx, project_id,
        BoqLineItemCreate(item_no="1.0", description="alignment alignment_length_m road centreline works", uom="m", boq_quantity=100),
    )

    suggestions = await semantic_matching_service.suggest_measurements_for_boq_line(rls_session, boq_item)
    assert [s.target_id for s in suggestions] == [close.id, far.id]
    assert suggestions[0].semantic_score is not None
    assert suggestions[0].final_score > suggestions[1].final_score


async def test_suggest_degrades_to_fuzzy_only_when_embeddings_missing(rls_session, monkeypatch):
    """Model unavailable at write time (embed_best_effort returns None) --
    every embedding column stays NULL, and suggestions still rank, just on
    fuzzy alone."""
    tenant_id, project_id = await _seed_project(rls_session)
    sys_ctx = _ctx(frozenset(), tenant_id=tenant_id, is_system=True)
    await set_rls_context(rls_session, sys_ctx)

    monkeypatch.setattr(embeddings_module, "get_embedder", lambda: (_ for _ in ()).throw(FileNotFoundError("no model")))
    measurement = await _seed_measurement(rls_session, tenant_id, project_id, capability="alignment", kind="alignment_length_m", layer="ROAD-CL")
    assert measurement.descriptor_embedding is None

    member_ctx = _ctx(frozenset({"lead_estimator"}), tenant_id=tenant_id, user_id=_MEMBER_USER_ID)
    await set_rls_context(rls_session, member_ctx)
    boq_item = await boq_service.create_line_item(
        rls_session, member_ctx, project_id,
        BoqLineItemCreate(item_no="1.0", description="road works", uom="m", boq_quantity=100),
    )
    assert boq_item.description_embedding is None

    suggestions = await semantic_matching_service.suggest_measurements_for_boq_line(rls_session, boq_item)
    assert len(suggestions) == 1
    assert suggestions[0].semantic_score is None
    assert suggestions[0].combined_score == suggestions[0].fuzzy_score
    assert suggestions[0].final_score == suggestions[0].fuzzy_score  # no embedding -> no RAG lookup either


async def test_feedback_shifts_a_subsequent_suggestions_ranking(rls_session, monkeypatch):
    _force_fixture_embedder(monkeypatch)
    tenant_id, project_id = await _seed_project(rls_session)
    sys_ctx = _ctx(frozenset(), tenant_id=tenant_id, is_system=True)
    await set_rls_context(rls_session, sys_ctx)

    # Two measurements deliberately given the SAME descriptor shape (and
    # so the same embedding + fuzzy score against the query) -- the only
    # thing that can separate them afterwards is the RAG adjustment.
    a = await _seed_measurement(rls_session, tenant_id, project_id, capability="alignment", kind="alignment_length_m", layer="ROAD-CL")
    b = await _seed_measurement(rls_session, tenant_id, project_id, capability="alignment", kind="alignment_length_m", layer="ROAD-CL")

    member_ctx = _ctx(frozenset({"lead_estimator"}), tenant_id=tenant_id, user_id=_MEMBER_USER_ID)
    await set_rls_context(rls_session, member_ctx)
    boq_item = await boq_service.create_line_item(
        rls_session, member_ctx, project_id,
        BoqLineItemCreate(item_no="1.0", description="alignment alignment_length_m road centreline", uom="m", boq_quantity=100),
    )

    before = await semantic_matching_service.suggest_measurements_for_boq_line(rls_session, boq_item)
    before_scores = {s.target_id: s.final_score for s in before}
    assert before_scores[a.id] == pytest.approx(before_scores[b.id])  # tied before any feedback

    await semantic_matching_service.record_feedback(
        rls_session, member_ctx, project_id=project_id, match_type=semantic_matching_service.MATCH_TYPE_BOQ_MEASUREMENT,
        query_embedding=list(boq_item.description_embedding), target_id=a.id, outcome="accepted",
    )
    await semantic_matching_service.record_feedback(
        rls_session, member_ctx, project_id=project_id, match_type=semantic_matching_service.MATCH_TYPE_BOQ_MEASUREMENT,
        query_embedding=list(boq_item.description_embedding), target_id=b.id, outcome="rejected",
    )

    after = await semantic_matching_service.suggest_measurements_for_boq_line(rls_session, boq_item)
    after_by_id = {s.target_id: s for s in after}
    assert after_by_id[a.id].rag_adjustment > 0
    assert after_by_id[b.id].rag_adjustment < 0
    assert after_by_id[a.id].final_score > after_by_id[b.id].final_score
    assert after[0].target_id == a.id  # accepted precedent now ranks first


async def test_record_feedback_returns_none_when_query_has_no_embedding(rls_session):
    tenant_id, project_id = await _seed_project(rls_session)
    member_ctx = _ctx(frozenset({"lead_estimator"}), tenant_id=tenant_id, user_id=_MEMBER_USER_ID)
    await set_rls_context(rls_session, member_ctx)

    result = await semantic_matching_service.record_feedback(
        rls_session, member_ctx, project_id=project_id, match_type=semantic_matching_service.MATCH_TYPE_BOQ_MEASUREMENT,
        query_embedding=None, target_id=uuid.uuid4(), outcome="accepted",
    )
    assert result is None
    count = (
        await rls_session.execute(select(SemanticMatchFeedback).where(SemanticMatchFeedback.project_id == project_id))
    ).scalars().all()
    assert count == []


# --------------------------------------------------------------------------
# quotation line -> package BOQ item suggestions
# --------------------------------------------------------------------------


async def test_suggest_boq_for_quotation_line_scopes_to_the_quotes_own_package(rls_session, monkeypatch):
    _force_fixture_embedder(monkeypatch)
    tenant_id, project_id = await _seed_project(rls_session)
    sys_ctx = _ctx(frozenset(), tenant_id=tenant_id, is_system=True)
    await set_rls_context(rls_session, sys_ctx)

    package_id = (
        await rls_session.execute(
            text("INSERT INTO procurement_packages (tenant_id, project_id, name, status) VALUES (:t, :p, 'Pkg', 'sent') RETURNING id"),
            {"t": str(tenant_id), "p": str(project_id)},
        )
    ).scalar_one()
    other_package_id = (
        await rls_session.execute(
            text("INSERT INTO procurement_packages (tenant_id, project_id, name, status) VALUES (:t, :p, 'Other', 'sent') RETURNING id"),
            {"t": str(tenant_id), "p": str(project_id)},
        )
    ).scalar_one()

    member_ctx = _ctx(frozenset({"lead_estimator"}), tenant_id=tenant_id, user_id=_MEMBER_USER_ID)
    await set_rls_context(rls_session, member_ctx)
    in_package = await boq_service.create_line_item(
        rls_session, member_ctx, project_id,
        BoqLineItemCreate(item_no="1.0", description="300mm dia RC pipe supply and lay", uom="m", boq_quantity=50),
    )
    not_in_package = await boq_service.create_line_item(
        rls_session, member_ctx, project_id,
        BoqLineItemCreate(item_no="2.0", description="300mm dia RC pipe supply and lay", uom="m", boq_quantity=50),
    )
    await set_rls_context(rls_session, sys_ctx)
    rls_session.add(ProcurementPackageItem(tenant_id=tenant_id, package_id=package_id, boq_line_item_id=in_package.id, project_id=project_id))
    rls_session.add(ProcurementPackageItem(tenant_id=tenant_id, package_id=other_package_id, boq_line_item_id=not_in_package.id, project_id=project_id))
    await rls_session.flush()

    quote_line = await _seed_quotation_line(
        rls_session, tenant_id, project_id, package_id=package_id, vendor_text="300mm RC pipe supply and lay",
    )

    suggestions = await semantic_matching_service.suggest_boq_for_quotation_line(rls_session, quote_line)
    assert [s.target_id for s in suggestions] == [in_package.id]  # the other package's identical-text item never appears


# --------------------------------------------------------------------------
# access: lowest allowed role succeeds, a non-member is denied (RLS,
# same "invisible row -> NotFoundError" convention as every other
# project-scoped read in this codebase)
# --------------------------------------------------------------------------


async def test_non_member_cannot_see_a_boq_line_item_to_request_suggestions_for(rls_session, monkeypatch):
    _force_fixture_embedder(monkeypatch)
    tenant_id, project_id = await _seed_project(rls_session)
    sys_ctx = _ctx(frozenset(), tenant_id=tenant_id, is_system=True)
    await set_rls_context(rls_session, sys_ctx)

    member_ctx = _ctx(frozenset({"lead_estimator"}), tenant_id=tenant_id, user_id=_MEMBER_USER_ID)
    await set_rls_context(rls_session, member_ctx)
    boq_item = await boq_service.create_line_item(
        rls_session, member_ctx, project_id,
        BoqLineItemCreate(item_no="1.0", description="road works", uom="m", boq_quantity=100),
    )

    non_member_ctx = _ctx(frozenset({"estimator"}), tenant_id=tenant_id, user_id=_NON_MEMBER_USER_ID)
    await set_rls_context(rls_session, non_member_ctx)
    with pytest.raises(NotFoundError):
        await boq_service.get_line_item(rls_session, non_member_ctx, boq_item.id)
