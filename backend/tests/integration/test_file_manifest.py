"""Phase 1 of the BOQ agent, with a real Postgres: upload with the per-file AI classification off builds the manifest for
every file with no model call, routes only BOQ workbooks and addenda by rules, finds files by text, and keeps one
tenant's index away from another's (docs/boq-agent/plan.md section 2)."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select, text

from app.db.rls import set_rls_context
from app.models.tender_intake import ProjectDocument, ProjectFileIndex
from app.services import file_manifest
from app.services import tender_intake as svc
from tests.fixtures.tender_pack import build_pack
from tests.integration.test_tender_intake_flow import (  # noqa: F401 -- shared fixtures and helpers
    _ctx,
    _seed,
    celery_calls,
    drive_worker,
    fake_s3,
    mock_model,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def fast_pack(rls_session, fake_s3, mock_model, celery_calls, monkeypatch):
    tenant_id, project_id = await _seed(rls_session)
    est = _ctx(frozenset({"estimator"}), tenant_id=tenant_id)
    await set_rls_context(rls_session, est)
    package, _ = await svc.create_package(
        rls_session, est, project_id, [(f.name, f.data) for f in build_pack()], label="TX", transmittal_ref="TX-1"
    )
    await drive_worker(rls_session, monkeypatch, est, tenant_id, ai_classify=False)
    await svc.refresh_package_status(rls_session, package.id)
    return {"s": rls_session, "tenant": tenant_id, "project": project_id, "est": est, "ai_calls": mock_model}


async def test_no_model_call_and_every_readable_file_has_an_entry(fast_pack):
    s = fast_pack["s"]
    assert fast_pack["ai_calls"] == []  # upload is AI-free
    docs = (await s.execute(select(ProjectDocument))).scalars().all()
    readable = [d for d in docs if d.status in ("proposed", "confirmed", "routed")]
    assert readable
    indexed = {r.document_id for r in (await s.execute(select(ProjectFileIndex))).scalars()}
    missing = [d.original_filename for d in readable if d.id not in indexed and d.doc_class != "other"]
    assert not missing, missing
    assert all(d.classified_by in ("rules", None) for d in docs)


async def test_boq_and_addenda_route_by_rules_and_the_rest_waits(fast_pack):
    s = fast_pack["s"]
    docs = (await s.execute(select(ProjectDocument))).scalars().all()
    routed = {d.doc_class for d in docs if d.status == "routed" and d.auto_accepted}
    assert routed <= {"boq", "addendum"}
    drawings = [d for d in docs if d.doc_class == "drawing"]
    assert drawings and all(d.status == "proposed" for d in drawings)  # nothing measured or routed without a person


async def test_search_finds_a_file_by_name_and_title_text(fast_pack):
    s = fast_pack["s"]
    entries = (await s.execute(select(ProjectFileIndex))).scalars().all()
    target = next(e for e in entries if e.hints.get("document_number"))
    hits = await file_manifest.search(s, fast_pack["project"], target.hints["document_number"])
    assert target.document_id in {h.document_id for h in hits}
    assert await file_manifest.search(s, fast_pack["project"], "zzzzqqqqunmatched") == []


async def test_partial_and_duplicate_entries_exist(fast_pack):
    s = fast_pack["s"]
    docs = (await s.execute(select(ProjectDocument).where(ProjectDocument.duplicate_of_id.is_not(None)))).scalars().all()
    assert docs
    for d in docs:
        assert await file_manifest.get_entry(s, d.project_id, d.id) is not None


async def test_other_tenant_sees_nothing(fast_pack, rls_session):
    s = fast_pack["s"]
    other = _ctx(frozenset({"estimator"}), tenant_id=__import__("uuid").uuid4())
    await set_rls_context(s, other)
    assert (await s.execute(select(func.count()).select_from(ProjectFileIndex))).scalar_one() == 0
    await set_rls_context(s, fast_pack["est"])
    assert (await s.execute(select(func.count()).select_from(ProjectFileIndex))).scalar_one() > 0


async def test_upload_with_the_ai_off_needs_no_cost_confirmation_even_when_an_external_provider_is_configured(fast_pack):
    """The pack is read without a model, so the dispatcher must not wait for a cost confirmation that has nothing to cost."""
    from pydantic import SecretStr

    from app.core.config import Settings
    from app.models.ai import TenantAiSettings
    from app.models.tender_intake import TenderPackage
    from app.services import ai_cost

    s = fast_pack["s"]
    settings = Settings(
        APP_DATABASE_URL="postgresql://x/y", MIGRATOR_DATABASE_URL="postgresql://x/y", S3_ENDPOINT="http://s3", VLLM_API_BASE="http://v/v1",
        AI_PROVIDER="openai_compatible", AI_API_KEY=SecretStr("k"), AI_BASE_URL="https://ai.example/v1", AI_MODEL="qwen3.7-plus",
    )
    sys_ctx = fast_pack["est"].__class__(tenant_id=fast_pack["tenant"], user_id=None, sub="system", roles=frozenset(), is_system=True)
    await set_rls_context(s, sys_ctx)
    s.add(TenantAiSettings(tenant_id=fast_pack["tenant"], external_ai_allowed=True, intake_ai_classify=False))
    await s.flush()
    package_id = (await s.execute(select(TenderPackage.id))).scalars().first()
    assert await ai_cost.external_ai_in_use(s, sys_ctx, settings) is False
    est = await ai_cost.estimate(s, sys_ctx, settings, package_id)
    assert est.confirmation_required is False and est.files_needing_ai == 0 and est.total_usd == 0 and "no cost" in est.note
    await s.execute(text("UPDATE tenant_ai_settings SET intake_ai_classify = true"))
    assert await ai_cost.external_ai_in_use(s, sys_ctx, settings) is True  # unchanged behaviour once a tenant turns it on


async def test_embeddings_are_filled_in_afterwards_in_small_batches(fast_pack, monkeypatch):
    from app.services import file_manifest

    s = fast_pack["s"]
    calls: list[int] = []

    def fake(texts):
        calls.append(len(texts))
        return [[0.1] * 384 for _ in texts]

    monkeypatch.setattr("app.integrations.embeddings.embed_best_effort", fake)
    missing = (await s.execute(select(func.count()).select_from(ProjectFileIndex).where(ProjectFileIndex.embedding.is_(None)))).scalar_one()
    assert missing > 0  # upload does not wait for the embedder
    done = await file_manifest.embed_pending(s, limit=96)
    assert done == missing and max(calls) <= file_manifest.EMBED_SUB_BATCH
    assert await file_manifest.embed_pending(s) == 0
