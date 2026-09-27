"""Module C1 change #3 (dispatch state machine + idempotency), #4 (reply
correlation), #8 (dispatch/resend role + step-up matrix). No Celery
broker/Redis involved: app.services.procurement._queue's `.delay(...)` call
is monkeypatched (see _install_fake_delay) so these tests exercise the real
authorization/state-machine code without needing a running worker, and
app.workers.tasks.procurement._dispatch_rfq_body (the task's actual body) is
invoked directly to test the send pipeline itself -- the same "test the
async body function, not the Celery wrapper" split
tests/unit doesn't cover for Module B's index_sheets either, since neither
task registers itself with a broker in this test environment.
"""

from __future__ import annotations

import time
import uuid
from datetime import date

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import RequestContext, reset_context, set_context
from app.core.enums import RfqStatus
from app.core.errors import ConflictError, ForbiddenError, StepUpRequiredError
from app.db.rls import set_rls_context
from app.models.audit import AuditEvent
from app.models.vendors import VendorContact, VendorTrade
from app.schemas.boq import BoqLineItemCreate
from app.schemas.prequal import PrequalificationDecision
from app.schemas.procurement import ProcurementPackageCreate, RfqCreateRequest
from app.schemas.taxonomy import TradeNodeCreate
from app.schemas.vendors import VendorCreate
from app.services import boq as boq_service
from app.services import prequal as prequal_service
from app.services import procurement as procurement_service
from app.services import taxonomy as taxonomy_service
from app.services import vendors as vendors_service

pytestmark = pytest.mark.asyncio

TENANT = uuid.UUID("8f14e45f-ceea-4e97-8d0c-3d3b3f3c1a00")


def _ctx(roles: frozenset[str], *, is_system: bool = False, user_id: uuid.UUID | None = None, acr: str | None = None) -> RequestContext:
    user_id = user_id or uuid.uuid4()
    # has_recent_step_up (fix/keycloak-step-up) requires acr AND a recent
    # auth_time, not acr alone.
    auth_time = int(time.time()) if acr else None
    return RequestContext(tenant_id=TENANT, user_id=user_id, sub=str(user_id), roles=roles, is_system=is_system, acr=acr, auth_time=auth_time)


async def _seed_draft_rfq(session: AsyncSession) -> uuid.UUID:
    """One project (with a member), one trade, one active+prequalified
    vendor with a primary contact, one package with one BOQ item, and one
    RFQ drafted against it. Returns the Rfq id."""
    member_user_id = uuid.uuid4()
    system_ctx = _ctx(frozenset(), is_system=True)
    await set_rls_context(session, system_ctx)
    project_id = (
        await session.execute(
            text("INSERT INTO projects (tenant_id, code, name) VALUES (:t, :c, 'A') RETURNING id"),
            {"t": str(TENANT), "c": f"DISPATCH-{uuid.uuid4().hex[:8]}"},
        )
    ).scalar_one()
    await session.execute(
        text("INSERT INTO project_members (project_id, user_id, tenant_id, project_role) VALUES (:p, :u, :t, 'estimator')"),
        {"p": project_id, "u": str(member_user_id), "t": str(TENANT)},
    )

    lead_ctx = _ctx(frozenset({"lead_estimator"}), user_id=member_user_id)
    await set_rls_context(session, lead_ctx)
    trade = await taxonomy_service.create_node(session, lead_ctx, TradeNodeCreate(code=f"EW-{uuid.uuid4().hex[:6]}", name="Earthworks"))
    vendor = await vendors_service.create_vendor(
        session, lead_ctx, VendorCreate(legal_name=f"Vendor {uuid.uuid4().hex[:6]}", primary_email="quotes@vendor.example")
    )
    vendor.status = "active"  # create_vendor leaves status="draft" (server_default)
    session.add(VendorTrade(tenant_id=TENANT, vendor_id=vendor.id, trade_node_id=trade.id))
    session.add(VendorContact(tenant_id=TENANT, vendor_id=vendor.id, name="Primary", email="quotes@vendor.example", is_primary=True))
    await session.flush()
    await prequal_service.decide_prequalification(
        session, lead_ctx, vendor.id,
        PrequalificationDecision(status="approved", effective_from=date(2020, 1, 1), scope_trade_node_id=trade.id),
    )
    package = await procurement_service.create_package(
        session, lead_ctx, project_id, ProcurementPackageCreate(name="Earthworks Package A", trade_node_id=trade.id)
    )
    item = await boq_service.create_line_item(
        session, lead_ctx, project_id, BoqLineItemCreate(item_no="1.0", description="Excavation", uom="m3", boq_quantity=100.0)
    )
    await procurement_service.add_items(session, lead_ctx, package.id, [item.id])
    [rfq] = await procurement_service.create_rfqs(session, lead_ctx, package.id, RfqCreateRequest(vendor_ids=[vendor.id]))
    return rfq.id


class _FakeAsyncResult:
    id = "fake-task-id"


@pytest.fixture
def fake_dispatch_delay(monkeypatch):
    """Replaces the Celery task's own `.delay` with a no-op recorder, so
    app.services.procurement._queue's enqueue call never touches a real
    broker. Returns the list of (args) it was called with."""
    from app.workers.tasks.procurement import dispatch_rfq_task

    calls: list[tuple] = []

    def _fake_delay(*args):
        calls.append(args)
        return _FakeAsyncResult()

    monkeypatch.setattr(dispatch_rfq_task, "delay", _fake_delay)
    return calls


async def _read_audit_actions(session: AsyncSession, entity_id: uuid.UUID) -> list[str]:
    managing_director_ctx = _ctx(frozenset({"managing_director"}))
    await set_rls_context(session, managing_director_ctx)
    result = await session.execute(
        select(AuditEvent.action).where(AuditEvent.entity_type == "rfq", AuditEvent.entity_id == str(entity_id))
        .order_by(AuditEvent.occurred_at)
    )
    return [row[0] for row in result.all()]


# --------------------------------------------------------------------------
# dispatch/resend: role + MFA step-up matrix (SRS change #8)
# --------------------------------------------------------------------------


async def test_dispatch_denied_for_estimator_and_lead_estimator(rls_session, fake_dispatch_delay):
    rfq_id = await _seed_draft_rfq(rls_session)

    estimator_ctx = _ctx(frozenset({"estimator"}), acr="silver")
    await set_rls_context(rls_session, estimator_ctx)
    with pytest.raises(ForbiddenError):
        await procurement_service.dispatch_rfq(rls_session, estimator_ctx, rfq_id)

    # lead_estimator (lowest role that CAN draft) is still not senior enough
    # to dispatch -- that boundary is the whole point of this test.
    lead_ctx = _ctx(frozenset({"lead_estimator"}), acr="silver")
    await set_rls_context(rls_session, lead_ctx)
    with pytest.raises(ForbiddenError):
        await procurement_service.dispatch_rfq(rls_session, lead_ctx, rfq_id)

    assert fake_dispatch_delay == []


async def test_dispatch_requires_step_up_even_for_procurement_head(rls_session, fake_dispatch_delay):
    rfq_id = await _seed_draft_rfq(rls_session)

    no_acr_ctx = _ctx(frozenset({"procurement_head"}), acr=None)
    await set_rls_context(rls_session, no_acr_ctx)
    with pytest.raises(StepUpRequiredError):
        await procurement_service.dispatch_rfq(rls_session, no_acr_ctx, rfq_id)

    bronze_ctx = _ctx(frozenset({"procurement_head"}), acr="bronze")
    await set_rls_context(rls_session, bronze_ctx)
    with pytest.raises(StepUpRequiredError):
        await procurement_service.dispatch_rfq(rls_session, bronze_ctx, rfq_id)

    assert fake_dispatch_delay == []


async def test_dispatch_succeeds_for_procurement_head_with_step_up_and_queues(rls_session, fake_dispatch_delay):
    rfq_id = await _seed_draft_rfq(rls_session)
    ph_ctx = _ctx(frozenset({"procurement_head"}), acr="silver")
    await set_rls_context(rls_session, ph_ctx)

    rfq = await procurement_service.dispatch_rfq(rls_session, ph_ctx, rfq_id)
    assert rfq.status == RfqStatus.QUEUED.value
    assert rfq.celery_task_id == "fake-task-id"
    assert len(fake_dispatch_delay) == 1
    assert fake_dispatch_delay[0][0] == str(rfq_id)

    assert "update" in await _read_audit_actions(rls_session, rfq_id)


async def test_dispatch_conflict_once_already_queued_or_sent(rls_session, fake_dispatch_delay):
    rfq_id = await _seed_draft_rfq(rls_session)
    ph_ctx = _ctx(frozenset({"procurement_head"}), acr="silver")
    await set_rls_context(rls_session, ph_ctx)

    await procurement_service.dispatch_rfq(rls_session, ph_ctx, rfq_id)
    with pytest.raises(ConflictError):
        await procurement_service.dispatch_rfq(rls_session, ph_ctx, rfq_id)

    rfq = await procurement_service.get_rfq(rls_session, rfq_id)
    rfq.status = RfqStatus.SENT.value
    await rls_session.flush()
    with pytest.raises(ConflictError):
        await procurement_service.dispatch_rfq(rls_session, ph_ctx, rfq_id)


async def test_resend_denied_for_lead_estimator_requires_step_up_then_succeeds(rls_session, fake_dispatch_delay):
    rfq_id = await _seed_draft_rfq(rls_session)
    rfq = await procurement_service.get_rfq(rls_session, rfq_id)
    rfq.status = RfqStatus.SENT.value
    await rls_session.flush()

    lead_ctx = _ctx(frozenset({"lead_estimator"}), acr="silver")
    await set_rls_context(rls_session, lead_ctx)
    with pytest.raises(ForbiddenError):
        await procurement_service.resend_rfq(rls_session, lead_ctx, rfq_id, "vendor says they never received it")

    ph_no_stepup = _ctx(frozenset({"procurement_head"}), acr=None)
    await set_rls_context(rls_session, ph_no_stepup)
    with pytest.raises(StepUpRequiredError):
        await procurement_service.resend_rfq(rls_session, ph_no_stepup, rfq_id, "vendor says they never received it")

    ph_ctx = _ctx(frozenset({"procurement_head"}), acr="silver")
    await set_rls_context(rls_session, ph_ctx)
    resent = await procurement_service.resend_rfq(rls_session, ph_ctx, rfq_id, "vendor says they never received it")
    assert resent.status == RfqStatus.QUEUED.value

    actions = await _read_audit_actions(rls_session, rfq_id)
    assert actions.count("update") >= 1


async def test_resend_rejected_for_a_draft_never_sent(rls_session, fake_dispatch_delay):
    rfq_id = await _seed_draft_rfq(rls_session)
    ph_ctx = _ctx(frozenset({"procurement_head"}), acr="silver")
    await set_rls_context(rls_session, ph_ctx)
    with pytest.raises(ConflictError):
        await procurement_service.resend_rfq(rls_session, ph_ctx, rfq_id, "not sent yet")


# --------------------------------------------------------------------------
# actual send pipeline (app.workers.tasks.procurement._dispatch_rfq_body)
# --------------------------------------------------------------------------


class _FakeSentEmail:
    def __init__(self, to_address: str, original_to: str | None, message_id: str) -> None:
        self.to_address = to_address
        self.original_to = original_to
        self.message_id = message_id


async def _run_dispatch_body(session: AsyncSession, rfq_id: uuid.UUID, ctx: RequestContext) -> None:
    from app.workers.tasks.procurement import _dispatch_rfq_body

    token = set_context(ctx)
    try:
        await _dispatch_rfq_body(session, str(rfq_id))
    finally:
        reset_context(token)


async def _fake_put_object_streaming(*_args, **_kwargs) -> str:
    return "fake-sha256"


async def test_dispatch_pipeline_sends_and_snapshots_exactly_what_was_sent(rls_session, fake_dispatch_delay, monkeypatch):
    rfq_id = await _seed_draft_rfq(rls_session)
    ph_ctx = _ctx(frozenset({"procurement_head"}), acr="silver")
    await set_rls_context(rls_session, ph_ctx)
    await procurement_service.dispatch_rfq(rls_session, ph_ctx, rfq_id)

    sent_calls: list[dict] = []

    async def _fake_send_rfq_email(**kwargs):
        sent_calls.append(kwargs)
        return _FakeSentEmail(to_address="dev-catchall@installtec.local", original_to=kwargs["vendor_email"], message_id="<fake@installtec.local>")

    monkeypatch.setattr("app.workers.tasks.procurement.send_rfq_email", _fake_send_rfq_email)
    monkeypatch.setattr("app.workers.tasks.procurement.put_object_streaming", _fake_put_object_streaming)

    await _run_dispatch_body(rls_session, rfq_id, ph_ctx)

    rfq = await procurement_service.get_rfq(rls_session, rfq_id)
    assert rfq.status == RfqStatus.SENT.value
    assert rfq.sent_at is not None
    assert rfq.message_id == "<fake@installtec.local>"
    assert rfq.subject and rfq.rfq_ref in rfq.subject
    assert rfq.body_html and "Excavation" in rfq.body_html
    assert rfq.attachment_object_key == f"{TENANT}/{rfq_id}.xlsx"
    assert rfq.attachment_sha256
    assert rfq.dispatch_attempts == 1
    assert len(sent_calls) == 1
    assert sent_calls[0]["vendor_email"] == "quotes@vendor.example"

    # create (drafting the RFQ) -> update (queuing it) -> send (this dispatch)
    assert await _read_audit_actions(rls_session, rfq_id) == ["create", "update", "send"]


async def test_dispatch_pipeline_is_idempotent_against_task_redelivery(rls_session, fake_dispatch_delay, monkeypatch):
    rfq_id = await _seed_draft_rfq(rls_session)
    ph_ctx = _ctx(frozenset({"procurement_head"}), acr="silver")
    await set_rls_context(rls_session, ph_ctx)
    await procurement_service.dispatch_rfq(rls_session, ph_ctx, rfq_id)

    send_call_count = 0

    async def _fake_send_rfq_email(**kwargs):
        nonlocal send_call_count
        send_call_count += 1
        return _FakeSentEmail(to_address="dev-catchall@installtec.local", original_to=kwargs["vendor_email"], message_id="<fake@installtec.local>")

    monkeypatch.setattr("app.workers.tasks.procurement.send_rfq_email", _fake_send_rfq_email)
    monkeypatch.setattr("app.workers.tasks.procurement.put_object_streaming", _fake_put_object_streaming)

    await _run_dispatch_body(rls_session, rfq_id, ph_ctx)
    assert send_call_count == 1

    # A Celery redelivery of the *same* task after it already completed --
    # status is now `sent`, so the body must be a no-op, not a second email.
    await _run_dispatch_body(rls_session, rfq_id, ph_ctx)
    assert send_call_count == 1
    rfq = await procurement_service.get_rfq(rls_session, rfq_id)
    assert rfq.dispatch_attempts == 1


async def test_failed_send_is_recorded_and_can_be_retried(rls_session, fake_dispatch_delay, monkeypatch):
    rfq_id = await _seed_draft_rfq(rls_session)
    ph_ctx = _ctx(frozenset({"procurement_head"}), acr="silver")
    await set_rls_context(rls_session, ph_ctx)
    await procurement_service.dispatch_rfq(rls_session, ph_ctx, rfq_id)

    async def _failing_send(**kwargs):
        raise ConnectionError("Mailpit unreachable")

    monkeypatch.setattr("app.workers.tasks.procurement.send_rfq_email", _failing_send)
    monkeypatch.setattr("app.workers.tasks.procurement.put_object_streaming", _fake_put_object_streaming)

    await _run_dispatch_body(rls_session, rfq_id, ph_ctx)
    rfq = await procurement_service.get_rfq(rls_session, rfq_id)
    assert rfq.status == RfqStatus.FAILED.value
    assert "Mailpit unreachable" in rfq.dispatch_error
    assert rfq.attachment_object_key is None
    assert rfq.sent_at is None

    # Retry: dispatch() allows a second attempt straight from `failed`.
    retried = await procurement_service.dispatch_rfq(rls_session, ph_ctx, rfq_id)
    assert retried.status == RfqStatus.QUEUED.value

    async def _fake_send_rfq_email(**kwargs):
        return _FakeSentEmail(to_address="dev-catchall@installtec.local", original_to=kwargs["vendor_email"], message_id="<fake@installtec.local>")

    monkeypatch.setattr("app.workers.tasks.procurement.send_rfq_email", _fake_send_rfq_email)
    await _run_dispatch_body(rls_session, rfq_id, ph_ctx)
    rfq = await procurement_service.get_rfq(rls_session, rfq_id)
    assert rfq.status == RfqStatus.SENT.value
    assert rfq.dispatch_attempts == 2


# --------------------------------------------------------------------------
# dev/test email safety, end to end through the real mailer (SRS change #1)
# --------------------------------------------------------------------------


async def test_dispatch_pipeline_never_reaches_a_real_vendor_address_in_non_production(rls_session, fake_dispatch_delay, monkeypatch):
    rfq_id = await _seed_draft_rfq(rls_session)
    ph_ctx = _ctx(frozenset({"procurement_head"}), acr="silver")
    await set_rls_context(rls_session, ph_ctx)
    await procurement_service.dispatch_rfq(rls_session, ph_ctx, rfq_id)

    from app.core.config import Settings

    non_prod_settings = Settings(
        APP_DATABASE_URL="postgresql://x/y", MIGRATOR_DATABASE_URL="postgresql://x/y",
        S3_ENDPOINT="http://s3.invalid", VLLM_API_BASE="http://vllm.invalid/v1",
        APP_ENV="dev", EMAIL_REDIRECT_ALL_TO="dev-catchall@installtec.local",
    )
    monkeypatch.setattr("app.procurement.mailer.get_settings", lambda: non_prod_settings)

    captured: dict = {}

    async def _fake_smtp_send(message, **kwargs):
        captured["to"] = message["To"]
        captured["reply_to"] = message["Reply-To"]

    monkeypatch.setattr("app.procurement.mailer.aiosmtplib.send", _fake_smtp_send)
    monkeypatch.setattr("app.workers.tasks.procurement.put_object_streaming", _fake_put_object_streaming)

    await _run_dispatch_body(rls_session, rfq_id, ph_ctx)

    assert captured["to"] == "dev-catchall@installtec.local"
    assert captured["to"] != "quotes@vendor.example"
    assert captured["reply_to"].startswith("rfq+")

    rfq = await procurement_service.get_rfq(rls_session, rfq_id)
    assert rfq.status == RfqStatus.SENT.value

    result = await rls_session.execute(
        select(AuditEvent.payload).where(
            AuditEvent.entity_type == "rfq", AuditEvent.entity_id == str(rfq_id), AuditEvent.action == "send"
        )
    )
    payload = result.scalar_one()
    assert payload["to"] == "dev-catchall@installtec.local"
    assert payload["original_to"] == "quotes@vendor.example"
