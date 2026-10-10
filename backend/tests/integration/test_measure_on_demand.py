"""Drawings are measured on demand (docs/intake-scale/report.md): intake classifies and indexes only; a person opening a
drawing, the verification report, a bulk "Measure all" or the tenant's auto-measure list start the full pipeline, at
priorities that put what someone is looking at first. Also the AI cost estimate and the confirmation a pack on an external
provider waits for. Real Postgres with RLS; Celery sends are recorded, never delivered."""

from __future__ import annotations

import hashlib
import uuid

import pytest
from pydantic import SecretStr
from sqlalchemy import select, text

from app.core.config import get_settings
from app.core.enums import MeasurePriority
from app.core.errors import ConflictError, ValidationAppError
from app.db.rls import set_rls_context
from app.models.takeoff import Drawing
from app.models.tender_intake import ProjectDocument, TenderPackage
from app.services import ai_cost
from app.services import takeoff as takeoff_service
from app.services import tender_intake as svc
from app.services import tender_intake_upload as up
from tests.fixtures.tender_pack import build_pack
from tests.integration.test_tender_intake_flow import _by_name, _ctx, _seed, drive_worker, fake_s3, mock_model  # noqa: F401

pytestmark = pytest.mark.asyncio


def sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


@pytest.fixture
def sends(monkeypatch):
    """Every Celery send of the drawing pipeline, with the priority it carried."""
    from app.workers.tasks import dwg, takeoff

    out: dict[str, list] = {"index": [], "light": [], "convert": []}

    def rec(kind):
        def _send(args=None, kwargs=None, countdown=0, priority=None, **kw):
            out[kind].append({"args": args, "kwargs": kwargs or {}, "priority": priority})
            return type("T", (), {"id": "t"})()
        return _send

    monkeypatch.setattr(takeoff.index_sheets, "apply_async", rec("index"))
    monkeypatch.setattr(takeoff.index_drawing_light, "apply_async", rec("light"))
    monkeypatch.setattr(dwg.convert_dwg, "apply_async", rec("convert"))
    return out


@pytest.fixture
async def world(rls_session, sends):
    tenant_id, project_id = await _seed(rls_session)
    est = _ctx(frozenset({"estimator"}), tenant_id=tenant_id)
    lead = _ctx(frozenset({"lead_estimator"}), tenant_id=tenant_id)
    md = _ctx(frozenset({"managing_director"}), tenant_id=tenant_id)
    await set_rls_context(rls_session, lead)
    return {"s": rls_session, "tenant": tenant_id, "project": project_id, "est": est, "lead": lead, "md": md}


async def make_drawing(w, name: str, *, discipline: str | None, status: str = "indexed", drawing_type: str | None = None, ext: str = "pdf") -> Drawing:
    s = w["s"]
    d = Drawing(
        tenant_id=w["tenant"], project_id=w["project"], original_filename=name, kind="vector_pdf" if ext == "pdf" else "dxf", bucket="b",
        object_key=f"k/{name}", size_bytes=10, sha256=sha(name), status=status, discipline_hint=discipline,
    )
    s.add(d)
    await s.flush()
    pkg = (await s.execute(select(TenderPackage))).scalars().first()
    if pkg is None:
        pkg = TenderPackage(tenant_id=w["tenant"], project_id=w["project"], status="ready", file_count=0)
        s.add(pkg)
        await s.flush()
    s.add(
        ProjectDocument(
            tenant_id=w["tenant"], project_id=w["project"], package_id=pkg.id, original_filename=name, ext=ext, sha256=sha(name), bucket="b",
            object_key=f"k/{name}", size_bytes=10, status="routed", doc_class="drawing", sub_type=discipline, routed_kind="drawing",
            routed_ref={"drawing_id": str(d.id)}, doc_metadata={"drawing_type": drawing_type} if drawing_type else {}, safety_status="accepted",
        )
    )
    await s.flush()
    return d


# ------------------------------------------------------------------ intake indexes, never measures
async def test_intake_routes_drawings_as_indexed_and_starts_no_measurement(rls_session, fake_s3, mock_model, sends, monkeypatch):
    from app.services import tender_intake_upload as up_mod  # noqa: F401

    tenant_id, project_id = await _seed(rls_session)
    est = _ctx(frozenset({"estimator"}), tenant_id=tenant_id)
    await set_rls_context(rls_session, est)
    files = [f for f in build_pack() if f.name in ("C-101 Rev A.dxf", "S-201 Rev B.pdf", "ITT.pdf")]
    await svc.create_package(rls_session, est, project_id, [(f.name, f.data) for f in files])
    await drive_worker(rls_session, monkeypatch, est, tenant_id)
    docs = await _by_name(rls_session)
    drawings = (await rls_session.execute(select(Drawing))).scalars().all()
    assert len(drawings) == 2 and {d.status for d in drawings} == {"indexed"}  # classified and indexed: not measured
    assert sends["index"] == [] and sends["convert"] == []  # nothing entered the measurement pipeline
    assert len(sends["light"]) == 2 and all(c["priority"] == 9 for c in sends["light"])  # only the light sheet-count task
    routed = docs["C-101 Rev A.dxf"].routed_ref
    assert routed["indexed_only"] is True and routed["ingest_started"] is False
    assert docs["C-101 Rev A.dxf"].sub_type == "roads_civil"  # discipline, type, number, title: from the classification


async def test_a_discipline_on_the_auto_measure_list_is_measured_on_intake_at_the_lowest_priority(rls_session, fake_s3, mock_model, sends, monkeypatch):
    tenant_id, project_id = await _seed(rls_session)
    md = _ctx(frozenset({"managing_director"}), tenant_id=tenant_id)
    await set_rls_context(rls_session, md)
    assert await svc.set_auto_measure(rls_session, md, ["structural"]) == ["structural"]
    est = _ctx(frozenset({"estimator"}), tenant_id=tenant_id)
    await set_rls_context(rls_session, est)
    files = [f for f in build_pack() if f.name in ("C-101 Rev A.dxf", "S-201 Rev B.pdf")]
    await svc.create_package(rls_session, est, project_id, [(f.name, f.data) for f in files])
    await drive_worker(rls_session, monkeypatch, est, tenant_id)
    by_name = {d.original_filename: d for d in (await rls_session.execute(select(Drawing))).scalars()}
    assert by_name["S-201 Rev B.pdf"].status == "queued" and by_name["S-201 Rev B.pdf"].measure_priority == MeasurePriority.AUTO
    assert by_name["C-101 Rev A.dxf"].status == "indexed"
    assert [c["priority"] for c in sends["index"]] == [MeasurePriority.AUTO]


async def test_only_known_disciplines_can_be_listed_and_the_default_is_none(world):
    w = world
    assert await svc.get_auto_measure(w["s"]) == []
    await set_rls_context(w["s"], w["md"])
    with pytest.raises(ValidationAppError, match="made_up"):
        await svc.set_auto_measure(w["s"], w["md"], ["roads_civil", "made_up"])
    await svc.set_auto_measure(w["s"], w["md"], ["sewer", "sewer", "roads_civil"])
    assert await svc.get_auto_measure(w["s"]) == ["roads_civil", "sewer"]
    events = (await w["s"].execute(text("SELECT payload FROM audit_events WHERE entity_type = 'tenant_ai_settings'"))).scalars().all()
    assert any(e.get("intake_auto_measure", {}).get("after") == ["roads_civil", "sewer"] for e in events)


# ------------------------------------------------------------------ on demand
async def test_opening_a_drawing_measures_it_now_ahead_of_bulk_and_is_idempotent(world, sends):
    w = world
    d = await make_drawing(w, "R-1.pdf", discipline="roads_civil")
    assert takeoff_service.measurement_state(d.status) == "indexed"
    assert await takeoff_service.request_measure(w["s"], w["est"], d.id, priority=MeasurePriority.INTERACTIVE) == "queued"
    await w["s"].refresh(d)
    assert (d.status, d.measure_priority) == ("queued", 0) and [c["priority"] for c in sends["index"]] == [0]
    assert sends["index"][0]["kwargs"] == {"priority": 0}
    # Opening it again does not queue it twice.
    assert await takeoff_service.request_measure(w["s"], w["est"], d.id, priority=MeasurePriority.INTERACTIVE) == "queued"
    assert len(sends["index"]) == 1


async def test_a_drawing_waiting_in_a_bulk_request_is_bumped_when_someone_opens_it(world, sends):
    w = world
    d = await make_drawing(w, "R-2.pdf", discipline="roads_civil")
    await takeoff_service.request_measure(w["s"], w["lead"], d.id, priority=MeasurePriority.BULK)
    assert [c["priority"] for c in sends["index"]] == [6]
    await takeoff_service.request_measure(w["s"], w["est"], d.id, priority=MeasurePriority.INTERACTIVE)
    await w["s"].refresh(d)
    assert d.measure_priority == 0 and [c["priority"] for c in sends["index"]] == [6, 0]  # a second, urgent message
    # A lower priority never demotes it.
    await takeoff_service.request_measure(w["s"], w["lead"], d.id, priority=MeasurePriority.BULK)
    assert len(sends["index"]) == 2


async def test_measured_and_in_flight_drawings_are_left_alone(world, sends):
    w = world
    done = await make_drawing(w, "done.pdf", discipline="sewer", status="ready")
    busy = await make_drawing(w, "busy.pdf", discipline="sewer", status="extracting")
    partial = await make_drawing(w, "part.pdf", discipline="sewer", status="partial")
    assert [await takeoff_service.request_measure(w["s"], w["est"], x.id, priority=0) for x in (done, busy, partial)] == ["measured", "measuring", "measured"]
    assert sends["index"] == []


async def test_a_failed_drawing_is_measured_again_on_request(world, sends):
    w = world
    d = await make_drawing(w, "bad.pdf", discipline="sewer", status="failed")
    d.error_message = "took too long"
    assert await takeoff_service.request_measure(w["s"], w["est"], d.id, priority=0) == "queued"
    await w["s"].refresh(d)
    assert d.status == "queued" and d.error_message is None


async def test_every_drawing_status_reads_as_one_of_five_states():
    states = {s: takeoff_service.measurement_state(s) for s in (
        "indexed", "uploaded", "queued", "converting", "indexing", "extracting", "embedding", "ready", "partial", "failed", "needs_conversion")}
    assert set(states.values()) == {"indexed", "queued", "measuring", "measured", "failed"}
    assert states["partial"] == "measured" and states["needs_conversion"] == "failed"


# ------------------------------------------------------------------ bulk "Measure all: roads, drainage"
async def test_measure_all_picks_by_discipline_and_type_and_queues_behind_interactive(world, sends):
    w = world
    roads = [await make_drawing(w, f"road{i}.pdf", discipline="roads_civil", drawing_type="plan_profile" if i == 0 else None) for i in range(3)]
    storm = await make_drawing(w, "storm.pdf", discipline="stormwater")
    sewer = await make_drawing(w, "sewer.pdf", discipline="sewer", drawing_type="cross_sections")
    measured = await make_drawing(w, "roadX.pdf", discipline="roads_civil", status="ready")
    ids = await takeoff_service.drawings_matching(w["s"], w["project"], disciplines=["roads_civil", "stormwater"], drawing_types=None, drawing_ids=None)
    assert set(ids) == {d.id for d in roads} | {storm.id}  # the measured one is not asked again; sewer is not in the list
    out = await takeoff_service.request_measure_many(w["s"], w["lead"], ids, priority=MeasurePriority.BULK)
    assert out == {"queued": 4, "measuring": 0, "measured": 0, "skipped": 0}
    assert {c["priority"] for c in sends["index"]} == {6}
    by_type = await takeoff_service.drawings_matching(w["s"], w["project"], disciplines=None, drawing_types=["cross_sections"], drawing_ids=None)
    assert by_type == [sewer.id] and measured.status == "ready"
    summary = await takeoff_service.measurement_summary(w["s"], w["project"])
    assert summary["total"] == {"indexed": 1, "queued": 4, "measuring": 0, "measured": 1, "failed": 0}
    assert summary["by_discipline"]["roads_civil"] == {"indexed": 0, "queued": 3, "measuring": 0, "measured": 1, "failed": 0}


async def test_celery_runs_the_urgent_message_first_whatever_order_they_were_sent_in(redis_container):
    """The priority steps and queue order strategy on the real Redis transport: 0 (opened), 3 (verification), 6 (bulk), 9 (auto)."""
    from kombu import Connection, Exchange, Queue

    from app.workers.celery_app import celery_app

    options = dict(celery_app.conf.broker_transport_options)
    assert options["priority_steps"] == [0, 3, 6, 9] and options["queue_order_strategy"] == "priority"
    name = f"index-test-{uuid.uuid4().hex[:6]}"
    queue = Queue(name, Exchange(name), routing_key=name)
    with Connection(redis_container, transport_options=options) as conn:
        with conn.Producer() as producer:
            for prio in (9, 6, 6, 0, 3, 9, 0):
                producer.publish({"p": prio}, exchange=queue.exchange, routing_key=name, declare=[queue], priority=prio)
        got = []
        with conn.SimpleQueue(queue, serializer="json") as simple:
            for _ in range(7):
                msg = simple.get(timeout=5)
                got.append(msg.payload["p"])
                msg.ack()
    assert got == [0, 0, 3, 6, 6, 9, 9]


# ------------------------------------------------------------------ verification, failures, duplicate messages
async def test_the_verification_report_queues_the_drawings_it_needs(world, sends):
    from app.services import verification as verification_service

    w = world
    await make_drawing(w, "v1.pdf", discipline="sewer")
    await make_drawing(w, "v2.pdf", discipline="roads_civil")
    await make_drawing(w, "v3.pdf", discipline="roads_civil", status="ready")
    await verification_service.create_run(w["s"], w["lead"], w["project"], use_ai=False)
    assert sorted(c["priority"] for c in sends["index"]) == [3, 3]  # ahead of bulk (6), behind a person looking (0)


async def test_an_indexing_timeout_is_recorded_on_the_drawing_from_a_fresh_session(world):
    from celery.exceptions import SoftTimeLimitExceeded

    from app.workers.tasks import takeoff as worker

    w = world
    d = await make_drawing(w, "slow.pdf", discipline="sewer", status="indexing")
    await worker._record_index_failure_body(w["s"], str(d.id), "Reading this file took longer than 300 seconds")
    await w["s"].refresh(d)
    assert d.status == "failed" and "took longer" in d.error_message
    assert isinstance(SoftTimeLimitExceeded(), Exception)


async def test_a_stale_low_priority_message_is_ignored_once_the_drawing_is_past_indexing(world):
    from app.workers.tasks import takeoff as worker

    w = world
    flags = {}
    for status in ("queued", "indexing", "failed", "extracting", "embedding", "ready", "partial"):
        d = await make_drawing(w, f"{status}.pdf", discipline="sewer", status=status)
        flags[status] = await worker._should_index(w["s"], str(d.id))
    assert flags == {"queued": True, "indexing": True, "failed": True, "extracting": False, "embedding": False, "ready": False, "partial": False}


# ------------------------------------------------------------------ AI cost: estimate, confirmation, gate
def external_settings():
    return get_settings().model_copy(update={
        "ai_provider": "openai_compatible", "ai_api_key": SecretStr("k"), "ai_base_url": "http://ai.test/v1", "ai_model": "qwen3.7-plus",
        "ai_model_classify": "qwen3.7-flash", "ai_model_vision": "qwen3.7-plus", "ai_model_reasoning": "qwen3.7-plus",
        "ai_monthly_budget_usd": None, "ai_project_budget_usd": None,
    })


async def seed_history(w, flash_calls=100, plus_calls=25):
    from app.core.context import system_context

    s = w["s"]
    await set_rls_context(s, system_context(w["tenant"]))  # ai_calls and tenant settings are written by the system
    for model, n, t_in, t_cached, t_out in (("qwen3.7-flash", flash_calls, 2_000, 1_500, 100), ("qwen3.7-plus", plus_calls, 5_000, 0, 300)):
        for i in range(n):
            await s.execute(
                text(
                    "INSERT INTO ai_calls (tenant_id, task, provider, model, input_sha256, tokens_in, tokens_cached, tokens_out, cost_usd, status, external) "
                    "VALUES (:t, 'intake_classify', 'openai_compatible', :m, :h, :i, :c, :o, 0.0001, 'ok', true)"
                ),
                {"t": w["tenant"], "m": model, "h": sha(f"{model}{i}"), "i": t_in, "c": t_cached, "o": t_out},
            )
    await s.execute(text("INSERT INTO tenant_ai_settings (tenant_id, external_ai_allowed, intake_ai_classify) VALUES (:t, true, true)"), {"t": w["tenant"]})
    await set_rls_context(s, w["lead"])


async def pack_with(w, n: int, *, extra_dupes: int = 0) -> TenderPackage:
    s = w["s"]
    pkg = TenderPackage(tenant_id=w["tenant"], project_id=w["project"], status="processing", file_count=n)
    s.add(pkg)
    await s.flush()
    for i in range(n):
        s.add(ProjectDocument(
            tenant_id=w["tenant"], project_id=w["project"], package_id=pkg.id, original_filename=f"f{i}.pdf", ext="pdf", sha256=sha(f"f{i}"),
            bucket="b", object_key=f"k/f{i}", size_bytes=10, status="received",
        ))
    await s.flush()
    return pkg


async def test_the_estimate_is_files_needing_ai_times_the_average_tokens_per_model(world):
    w = world
    await seed_history(w)
    pkg = await pack_with(w, 200)
    settings = external_settings()
    est = await ai_cost.estimate(w["s"], w["lead"], settings, pkg.id)
    assert est.files_needing_ai == 200 and est.external and est.ai_available
    flash, plus = est.models
    assert (flash.model, plus.model) == ("qwen3.7-flash", "qwen3.7-plus") and flash.basis == plus.basis == "history"
    # history: 100 flash calls vs 25 plus: 20% of calls carry images
    assert (flash.calls, plus.calls) == (160, 40)
    # flash per call: 500 x 0.03 + 1500 x 0.006 + 100 x 0.13 = 37 per million; plus: 5000 x 0.40 + 300 x 1.20 = 2,360 per million
    assert flash.est_usd == pytest.approx(160 * 37 / 1e6, rel=1e-6) and plus.est_usd == pytest.approx(40 * 2_360 / 1e6, rel=1e-6)
    assert est.total_usd == pytest.approx(flash.est_usd + plus.est_usd)
    assert flash.rate_verified is True and plus.rate_verified is False and est.any_unverified is True
    assert est.confirmation_required is True and est.within_budget is True


async def test_the_estimate_leaves_out_copies_big_files_and_archives(world):
    w = world
    s = w["s"]
    await seed_history(w)
    pkg = await pack_with(w, 5)
    docs = (await s.execute(select(ProjectDocument).where(ProjectDocument.package_id == pkg.id).order_by(ProjectDocument.original_filename))).scalars().all()
    docs[0].duplicate_of_id = docs[1].id  # a copy reuses its original's answer
    docs[2].size_bytes = get_settings().intake_max_process_bytes + 1  # parked for a person, never sent
    docs[3].ext = "zip"  # its members are counted when it opens
    await s.flush()
    est = await ai_cost.estimate(s, w["lead"], external_settings(), pkg.id)
    assert est.files_needing_ai == 2


async def test_without_history_the_defaults_are_used_and_a_budget_below_the_estimate_is_said(world):
    w = world
    from app.core.context import system_context

    await set_rls_context(w["s"], system_context(w["tenant"]))
    await w["s"].execute(text("INSERT INTO tenant_ai_settings (tenant_id, external_ai_allowed, intake_ai_classify) VALUES (:t, true, true)"), {"t": w["tenant"]})
    await set_rls_context(w["s"], w["lead"])
    pkg = await pack_with(w, 100)
    settings = external_settings().model_copy(update={"ai_monthly_budget_usd": 0.0001})
    est = await ai_cost.estimate(w["s"], w["lead"], settings, pkg.id)
    assert {m.basis for m in est.models} == {"default"} and est.total_usd > 0.0001
    assert est.within_budget is False and est.monthly_remaining_usd is not None and "budget" in est.note


async def test_a_provider_inside_the_deployment_has_no_cost_and_needs_no_confirmation(world):
    w = world
    pkg = await pack_with(w, 10)
    est = await ai_cost.estimate(w["s"], w["lead"], get_settings().model_copy(update={"ai_provider": "mock"}), pkg.id)
    assert est.external is False and est.total_usd == 0 and est.confirmation_required is False


async def test_a_pack_on_an_external_provider_does_not_start_until_the_estimate_is_confirmed(world, monkeypatch):
    w = world
    await seed_history(w)
    pkg = await pack_with(w, 200)
    settings = external_settings()
    monkeypatch.setattr(up, "get_settings", lambda: settings)
    assert await up.claim_for_dispatch(w["s"], w["tenant"]) == []  # nothing is sent to the provider yet
    est = await ai_cost.estimate(w["s"], w["lead"], settings, pkg.id)
    with pytest.raises(ai_cost.CostConfirmationRequired) as low:  # the estimate they saw was far below the real one
        await ai_cost.confirm(w["s"], w["lead"], settings, pkg.id, est.total_usd / 10)
    assert "look at it again" in low.value.detail and low.value.extra["estimate"]["package_id"] == str(pkg.id)
    done = await ai_cost.confirm(w["s"], w["lead"], settings, pkg.id, est.total_usd)
    assert done.confirmation_required is False and done.confirmed_usd == pytest.approx(est.total_usd, abs=1e-4)
    assert len(await up.claim_for_dispatch(w["s"], w["tenant"])) == settings.intake_dispatch_limit  # now it starts
    events = (await w["s"].execute(text("SELECT payload FROM audit_events WHERE payload->>'event' = 'confirm_cost'"))).scalars().all()
    assert len(events) == 1 and events[0]["accepted_usd"] == pytest.approx(est.total_usd) and events[0]["any_unverified"] is True


async def test_resuming_a_paused_pack_asks_for_the_confirmation_first(world, monkeypatch):
    w = world
    await seed_history(w)
    pkg = await pack_with(w, 3)
    settings = external_settings()
    monkeypatch.setattr(up, "get_settings", lambda: settings)
    await up.pause_package(w["s"], w["lead"], pkg.id)
    with pytest.raises(ai_cost.CostConfirmationRequired):
        await up.resume_package(w["s"], w["lead"], pkg.id)
    est = await ai_cost.estimate(w["s"], w["lead"], settings, pkg.id)
    await ai_cost.confirm(w["s"], w["lead"], settings, pkg.id, est.total_usd)
    assert (await up.resume_package(w["s"], w["lead"], pkg.id)).status == "processing"


async def test_the_pack_list_says_which_packs_wait_for_a_cost_confirmation(world, monkeypatch):
    from app.core.context import try_current_context  # noqa: F401
    from app.services import tender_intake_tree as tree

    w = world
    await seed_history(w)
    await pack_with(w, 4)
    settings = external_settings()
    import app.core.config as cfg
    monkeypatch.setattr(cfg, "get_settings", lambda: settings)
    from app.core.context import _current_context

    token = _current_context.set(w["lead"])
    try:
        packs = await tree.package_progress(w["s"], w["project"])
    finally:
        _current_context.reset(token)
    assert packs[0].awaiting_cost_confirmation is True


async def test_conflict_error_type_for_the_ui():
    err = ai_cost.CostConfirmationRequired("x", estimate={"total_usd": 1})
    assert isinstance(err, ConflictError) and err.error_type == "urn:installtec:cost-confirmation-required" and err.status_code == 409
