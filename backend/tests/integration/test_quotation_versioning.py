"""Module C2 fix: versioning must never let an empty/failed extraction, or a
fresh reply, silently supersede an accepted quote, and attachments on one
inbound email must form one submission, not competing quotes.

1. A quotation with zero extracted line items is flagged and never becomes
   is_current automatically.
2. Attachments from the same inbound email form one submission (one
   Quotation); our pricing sheet is the primary source, everything else
   links as a supporting document.
3. A new version becomes current only when a reviewer explicitly promotes
   it (procurement_head+, audited).

See app/workers/tasks/quotation_ingestion.py::_create_quotation_version and
app/services/quotation_ingestion.py::promote_quotation_version.
"""

from __future__ import annotations

import asyncio
import io
import uuid
from datetime import datetime, timezone

import pytest
from pypdf import PdfWriter
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import RequestContext
from app.core.enums import QuotationExtractionMethod, QuotationStatus
from app.core.errors import ConflictError, ForbiddenError
from app.db.rls import set_rls_context
from app.models.procurement import ProcurementPackage, Rfq
from app.models.quotation_ingestion import InboundEmail, Quotation, QuotationAttachment
from app.models.vendors import Vendor
from app.procurement.content import RfqLineItem
from app.procurement.pricing_sheet import build_pricing_workbook
from app.schemas.boq import BoqLineItemCreate
from app.services import boq as boq_service
from app.services import procurement as procurement_service
from app.services import quotation_ingestion as quotation_service

pytestmark = pytest.mark.asyncio


def _ctx(roles: frozenset[str], *, tenant_id: uuid.UUID, is_system: bool = False, user_id: uuid.UUID | None = None) -> RequestContext:
    user_id = user_id or uuid.uuid4()
    return RequestContext(tenant_id=tenant_id, user_id=user_id, sub=str(user_id), roles=roles, is_system=is_system)


async def _system_ctx(session: AsyncSession, tenant_id: uuid.UUID) -> RequestContext:
    ctx = _ctx(frozenset(), tenant_id=tenant_id, is_system=True)
    await set_rls_context(session, ctx)
    return ctx


async def _seed_tenant_project_rfq_with_boq(session: AsyncSession):
    tenant_id = uuid.uuid4()
    await session.execute(
        text("INSERT INTO tenants (id, slug, name) VALUES (:id, :slug, :name)"),
        {"id": str(tenant_id), "slug": f"acme-{uuid.uuid4().hex[:8]}", "name": "Acme"},
    )
    system_ctx = await _system_ctx(session, tenant_id)
    project_id = (
        await session.execute(
            text("INSERT INTO projects (tenant_id, code, name) VALUES (:t, :c, 'A') RETURNING id"),
            {"t": str(tenant_id), "c": f"C2V-{uuid.uuid4().hex[:8]}"},
        )
    ).scalar_one()
    vendor = Vendor(tenant_id=tenant_id, legal_name="Vendor X", normalized_name="vendor x", status="active", primary_email="v@vendor.example")
    session.add(vendor)
    await session.flush()
    package = ProcurementPackage(tenant_id=tenant_id, project_id=project_id, name="Package A", status="sent")
    session.add(package)
    await session.flush()
    boq_item = await boq_service.create_line_item(
        session, system_ctx, project_id, BoqLineItemCreate(item_no="1.0", description="Excavation", uom="m3", boq_quantity=100.0)
    )
    await procurement_service.add_items(session, system_ctx, package.id, [boq_item.id])
    rfq = Rfq(
        tenant_id=tenant_id, package_id=package.id, project_id=project_id, vendor_id=vendor.id,
        status="sent", reply_token=f"tok-{uuid.uuid4().hex}",
    )
    session.add(rfq)
    await session.flush()
    return tenant_id, rfq, boq_item


async def _seed_inbound_email(session: AsyncSession, *, tenant_id: uuid.UUID, rfq_id: uuid.UUID) -> InboundEmail:
    email = InboundEmail(
        tenant_id=tenant_id, rfq_id=rfq_id, imap_uid_validity="1", imap_uid=str(uuid.uuid4().int)[:10],
        from_address="vendor@example.com", from_domain="example.com", to_address="rfq+x.y@installtec.local",
        received_at=datetime.now(timezone.utc), match_status="matched", needs_review=False,
        raw_object_key="inbound/1/1.eml", raw_sha256="0" * 64,
    )
    session.add(email)
    await session.flush()
    return email


# --------------------------------------------------------------------------
# 1. empty/failed extraction never becomes current automatically
# --------------------------------------------------------------------------


async def test_empty_extraction_is_flagged_and_never_becomes_current(rls_session):
    from app.workers.tasks.quotation_ingestion import _create_quotation_version

    tenant_id, rfq, _boq_item = await _seed_tenant_project_rfq_with_boq(rls_session)
    await _system_ctx(rls_session, tenant_id)
    inbound_email = await _seed_inbound_email(rls_session, tenant_id=tenant_id, rfq_id=rfq.id)

    # First-ever version for this (rfq, vendor), but empty -- must NOT
    # become current even though there's nothing else to protect.
    empty_quotation = await _create_quotation_version(
        rls_session, rfq=rfq, inbound_email=inbound_email, attachment=None,
        extraction_method=QuotationExtractionMethod.NONE.value, currency=None, vat_inclusive=None,
        status=QuotationStatus.EXTRACTION_EMPTY.value, line_item_count=0,
    )
    assert empty_quotation.is_current is False
    assert empty_quotation.status == QuotationStatus.EXTRACTION_EMPTY.value
    assert empty_quotation.version_no == 1

    # A real, non-empty version arrives next -- since nothing is currently
    # current (the empty one never became current), this one safely becomes
    # current automatically.
    inbound_email_2 = await _seed_inbound_email(rls_session, tenant_id=tenant_id, rfq_id=rfq.id)
    good_quotation = await _create_quotation_version(
        rls_session, rfq=rfq, inbound_email=inbound_email_2, attachment=None,
        extraction_method=QuotationExtractionMethod.DETERMINISTIC_XLSX.value, currency="AED", vat_inclusive=True,
        status=QuotationStatus.PROPOSED.value, line_item_count=1,
    )
    assert good_quotation.is_current is True
    assert good_quotation.version_no == 2

    await rls_session.refresh(empty_quotation)
    assert empty_quotation.is_current is False  # untouched


async def test_deterministic_sheet_identity_failure_also_never_becomes_current(rls_session):
    """NEEDS_REVIEW (the pricing sheet's row-id identity check failed) is
    the other zero-line-item case -- same rule applies."""
    from app.workers.tasks.quotation_ingestion import _create_quotation_version

    tenant_id, rfq, _boq_item = await _seed_tenant_project_rfq_with_boq(rls_session)
    await _system_ctx(rls_session, tenant_id)
    inbound_email = await _seed_inbound_email(rls_session, tenant_id=tenant_id, rfq_id=rfq.id)

    quotation = await _create_quotation_version(
        rls_session, rfq=rfq, inbound_email=inbound_email, attachment=None,
        extraction_method=QuotationExtractionMethod.DETERMINISTIC_XLSX.value, currency=None, vat_inclusive=None,
        status=QuotationStatus.NEEDS_REVIEW.value, line_item_count=0,
    )
    assert quotation.is_current is False


# --------------------------------------------------------------------------
# 2. attachments from one email form one submission
# --------------------------------------------------------------------------


def _pricing_sheet_bytes(rfq: Rfq, boq_item) -> bytes:
    items = [RfqLineItem(boq_line_item_id=boq_item.id, item_no=boq_item.item_no, description=boq_item.description, uom=boq_item.uom, quantity=float(boq_item.boq_quantity))]
    data, _sha = build_pricing_workbook(rfq_id=rfq.id, rfq_ref="RFQ-TEST-0001", reply_token=rfq.reply_token, package_name="Package A", items=items)
    return data


def _minimal_pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


async def test_email_with_pricing_sheet_and_pdf_is_one_submission(rls_session, monkeypatch):
    from app.workers.tasks import quotation_ingestion as worker_module

    tenant_id, rfq, boq_item = await _seed_tenant_project_rfq_with_boq(rls_session)
    await _system_ctx(rls_session, tenant_id)
    inbound_email = await _seed_inbound_email(rls_session, tenant_id=tenant_id, rfq_id=rfq.id)

    xlsx_bytes = _pricing_sheet_bytes(rfq, boq_item)
    pdf_bytes = _minimal_pdf_bytes()
    store = {"xlsx": xlsx_bytes, "pdf": pdf_bytes}

    pdf_attachment = QuotationAttachment(
        tenant_id=tenant_id, inbound_email_id=inbound_email.id, filename="cover-letter.pdf",
        size_bytes=len(pdf_bytes), raw_object_key="pdf", raw_sha256="1" * 64,
    )
    xlsx_attachment = QuotationAttachment(
        tenant_id=tenant_id, inbound_email_id=inbound_email.id, filename="RFQ-TEST-0001-priced.xlsx",
        size_bytes=len(xlsx_bytes), raw_object_key="xlsx", raw_sha256="2" * 64,
    )
    # Deliberately added PDF first, xlsx second -- the pricing sheet must be
    # picked as primary regardless of attachment order.
    rls_session.add_all([pdf_attachment, xlsx_attachment])
    await rls_session.flush()

    async def _fake_get_object_bytes(object_key, *args, **kwargs):
        return store[object_key]

    monkeypatch.setattr(worker_module, "get_object_bytes", _fake_get_object_bytes)
    extract_calls = []
    monkeypatch.setattr(worker_module.extract_quotation_task, "delay", lambda *a, **kw: extract_calls.append((a, kw)))

    await worker_module._process_inbound_email_body(rls_session, str(inbound_email.id))

    # Exactly one Quotation for this email.
    quotations = (await rls_session.execute(select(Quotation).where(Quotation.inbound_email_id == inbound_email.id))).scalars().all()
    assert len(quotations) == 1
    quotation = quotations[0]
    assert quotation.extraction_method == QuotationExtractionMethod.DETERMINISTIC_XLSX.value
    assert quotation.source_attachment_id == xlsx_attachment.id

    await rls_session.refresh(xlsx_attachment)
    await rls_session.refresh(pdf_attachment)
    assert xlsx_attachment.is_primary is True
    assert pdf_attachment.is_primary is False
    assert xlsx_attachment.quotation_id == quotation.id
    assert pdf_attachment.quotation_id == quotation.id  # supporting document, linked, not extracted

    attachments = await quotation_service.list_quotation_attachments(rls_session, quotation.id)
    assert {a.id for a in attachments} == {xlsx_attachment.id, pdf_attachment.id}

    # The PDF was never sent to the LLM path -- it's a supporting document,
    # not a competing quote.
    assert extract_calls == []


# --------------------------------------------------------------------------
# 3. promotion is explicit, role-gated, and audited
# --------------------------------------------------------------------------


async def test_promote_quotation_version_requires_review_role_and_is_audited(rls_session):
    from decimal import Decimal

    from app.models.quotation_ingestion import QuotationLineItem
    from app.workers.tasks.quotation_ingestion import _create_quotation_version

    tenant_id, rfq, boq_item = await _seed_tenant_project_rfq_with_boq(rls_session)
    await _system_ctx(rls_session, tenant_id)
    inbound_email_1 = await _seed_inbound_email(rls_session, tenant_id=tenant_id, rfq_id=rfq.id)
    v1 = await _create_quotation_version(
        rls_session, rfq=rfq, inbound_email=inbound_email_1, attachment=None,
        extraction_method=QuotationExtractionMethod.DETERMINISTIC_XLSX.value, currency="AED", vat_inclusive=True,
        status=QuotationStatus.PROPOSED.value, line_item_count=1,
    )
    v1_line = QuotationLineItem(
        tenant_id=tenant_id, quotation_id=v1.id, project_id=rfq.project_id, boq_line_item_id=boq_item.id,
        unit_price=Decimal("100.0"), source="deterministic", status="proposed",
    )
    rls_session.add(v1_line)
    await rls_session.flush()

    ph_ctx_accept = _ctx(frozenset({"procurement_head"}), tenant_id=tenant_id)
    await set_rls_context(rls_session, ph_ctx_accept)
    await quotation_service.accept_line_item(rls_session, ph_ctx_accept, v1_line.id)

    # v2 arrives after v1 already has an accepted line -- must NOT
    # auto-become current (this is exactly what promote exists for).
    await _system_ctx(rls_session, tenant_id)
    inbound_email_2 = await _seed_inbound_email(rls_session, tenant_id=tenant_id, rfq_id=rfq.id)
    v2 = await _create_quotation_version(
        rls_session, rfq=rfq, inbound_email=inbound_email_2, attachment=None,
        extraction_method=QuotationExtractionMethod.DETERMINISTIC_XLSX.value, currency="AED", vat_inclusive=True,
        status=QuotationStatus.PROPOSED.value, line_item_count=1,
    )
    await rls_session.refresh(v1)
    assert v1.is_current is True
    assert v2.is_current is False

    estimator_ctx = _ctx(frozenset({"estimator"}), tenant_id=tenant_id)
    await set_rls_context(rls_session, estimator_ctx)
    with pytest.raises(ForbiddenError):
        await quotation_service.promote_quotation_version(rls_session, estimator_ctx, v2.id)

    ph_ctx = _ctx(frozenset({"procurement_head"}), tenant_id=tenant_id)
    await set_rls_context(rls_session, ph_ctx)

    with pytest.raises(ConflictError):
        await quotation_service.promote_quotation_version(rls_session, ph_ctx, v1.id)  # already current

    promoted = await quotation_service.promote_quotation_version(rls_session, ph_ctx, v2.id)
    assert promoted.is_current is True

    await rls_session.refresh(v1)
    assert v1.is_current is False  # flipped off by the promotion
    # ...but its accepted line item is completely untouched.
    v1_items = await quotation_service.list_quotation_line_items(rls_session, v1.id)
    assert v1_items[0].status == "accepted"

    audit_row = (
        await rls_session.execute(
            text("SELECT action, actor_sub, payload FROM audit_events WHERE entity_type = 'quotation' AND entity_id = :e"),
            {"e": str(v2.id)},
        )
    ).one()
    assert audit_row[0] == "update"
    assert audit_row[1] == ph_ctx.sub


# --------------------------------------------------------------------------
# 4. concurrent replies for the same (rfq, vendor) never collide on version_no
# --------------------------------------------------------------------------


async def test_concurrent_replies_get_distinct_version_numbers(app_engine, monkeypatch):
    """Two concurrent replies for the same (rfq, vendor) -- e.g. two PDF
    attachments from different emails, each routed to extract_quotation_task
    and landing on two different vLLM worker forks at once -- is exactly
    what hit uq_quotations_rfq_vendor_version live during
    `make dev-simulate-quotes` (see docs/c2-verification-report.md's Round
    2). _create_quotation_version's pg_advisory_xact_lock must serialize the
    two callers so they land on distinct version_no values instead of both
    computing the same MAX(version_no) and colliding.

    Deliberately does NOT use the shared `rls_session` fixture: that fixture
    wraps the whole test in one transaction, and pg_advisory_xact_lock is
    reentrant within a single transaction -- a second lock call on the same
    connection/transaction would never block, so the race couldn't happen at
    all. This test instead opens two independent AsyncSession/transactions
    (mirroring two separate worker processes, each with its own DB
    connection) and runs them concurrently via asyncio.gather; Postgres
    itself serializes them on the advisory lock, which is real network I/O
    from asyncpg's point of view, so the event loop can genuinely interleave
    them.

    A plain asyncio.gather() of the two branches isn't enough by itself,
    though: against a fast local connection, one branch can simply run
    start-to-finish before the other's first await is even scheduled, so the
    two never actually overlap and the test passes "by luck" whether or not
    the lock is there (confirmed by hand -- removing the lock without this
    delay still passed). The monkeypatch below sleeps briefly right after
    the MAX(version_no) read inside _create_quotation_version -- after the
    point a missing lock would let both callers read the same value, before
    either has inserted -- to force real overlap when nothing serializes
    them. It costs nothing when the lock IS present: the second caller is
    then still blocked earlier, at pg_advisory_xact_lock, and doesn't reach
    this query at all until the first caller's whole transaction (sleep
    included) has already committed.

    To confirm this test actually exercises the lock: comment out the
    `pg_advisory_xact_lock` line in _create_quotation_version and rerun --
    it fails with a raw asyncpg.exceptions.UniqueViolationError on
    uq_quotations_rfq_vendor_version (confirmed manually; see
    docs/c2-verification-report.md's Round 3 note).
    """
    from app.workers.tasks.quotation_ingestion import _create_quotation_version

    async with AsyncSession(app_engine, expire_on_commit=False) as setup_session, setup_session.begin():
        tenant_id, rfq, _boq_item = await _seed_tenant_project_rfq_with_boq(setup_session)

    original_execute = AsyncSession.execute

    async def _delay_after_max_version_read(self, statement, *args, **kwargs):
        result = await original_execute(self, statement, *args, **kwargs)
        compiled = str(statement).lower()
        if "max(" in compiled and "version_no" in compiled:
            await asyncio.sleep(0.3)
        return result

    monkeypatch.setattr(AsyncSession, "execute", _delay_after_max_version_read)

    async def _run_one() -> int:
        async with AsyncSession(app_engine, expire_on_commit=False) as session, session.begin():
            await _system_ctx(session, tenant_id)
            inbound_email = await _seed_inbound_email(session, tenant_id=tenant_id, rfq_id=rfq.id)
            quotation = await _create_quotation_version(
                session, rfq=rfq, inbound_email=inbound_email, attachment=None,
                extraction_method=QuotationExtractionMethod.DETERMINISTIC_XLSX.value,
                currency="AED", vat_inclusive=True, status=QuotationStatus.PROPOSED.value, line_item_count=1,
            )
            return quotation.version_no

    version_numbers = await asyncio.gather(_run_one(), _run_one())
    assert sorted(version_numbers) == [1, 2]  # no collision, no IntegrityError from either branch

    async with AsyncSession(app_engine, expire_on_commit=False) as check_session, check_session.begin():
        await _system_ctx(check_session, tenant_id)
        rows = (
            await check_session.execute(
                select(Quotation.version_no, Quotation.is_current)
                .where(Quotation.rfq_id == rfq.id, Quotation.vendor_id == rfq.vendor_id)
                .order_by(Quotation.version_no)
            )
        ).all()
        assert [r[0] for r in rows] == [1, 2]
        # Whichever branch's transaction commits first becomes v1/current;
        # the second sees it (no accepted line item yet) and safely
        # supersedes it -- deterministic regardless of which branch wins
        # the lock race.
        assert [r[1] for r in rows] == [False, True]
