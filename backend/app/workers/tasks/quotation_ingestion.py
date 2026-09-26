"""Module C2: inbound quotation ingestion.

Three tasks, three queues, deliberately separated:
  - poll_inbound_mailbox ("email" queue): IMAP I/O only. Stores every raw
    email/attachment to S3 unchanged and runs sender/RFQ matching -- never
    parses attachment content.
  - process_inbound_email ("quotation" queue): untrusted-input safety checks
    (app/procurement/attachment_safety.py) for every attachment on one
    email, then either the deterministic pricing-sheet parse or a handoff
    to the LLM path. Isolated from both the SMTP/IMAP worker and the vLLM
    worker so a hostile attachment can't back up either.
  - extract_quotation_task ("vlm" queue): the vision-LLM path, sharing the
    same worker/queue Module B's title-block extraction already uses.

One inbound email is one submission, regardless of how many attachments it
carries: exactly one Quotation is created per email (never per attachment).
If the email includes our own pricing sheet, that's the primary extraction
source; any other attachment (e.g. a signed cover PDF) links to that same
Quotation as a supporting document, never as a separately-extracted
competing quote (QuotationAttachment.quotation_id/is_primary).

Nothing here ever runs in the FastAPI web process.
"""

from __future__ import annotations

import email
import hashlib
import imaplib
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from email.utils import parseaddr, parsedate_to_datetime
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.context import RequestContext
from app.core.enums import (
    AttachmentSafetyStatus,
    AuditAction,
    InboundEmailMatchStatus,
    LineItemMatchMethod,
    QuotationExtractionMethod,
    QuotationLineItemStatus,
    QuotationLineSource,
    QuotationStatus,
    RfqStatus,
)
from app.integrations.embeddings import embed_best_effort
from app.integrations.s3 import get_object_bytes, put_object_streaming
from app.models.procurement import Rfq
from app.models.quotation_ingestion import (
    InboundEmail,
    Quotation,
    QuotationAttachment,
    QuotationExclusionFlag,
    QuotationLineItem,
)
from app.procurement.attachment_safety import check_attachment
from app.procurement.email_auth import parse_authentication_results
from app.procurement.inbound_match import match_inbound_email
from app.procurement.pricing_sheet_parser import (
    dump_workbook_text,
    looks_like_our_pricing_sheet,
    parse_pricing_sheet,
)
from app.procurement.quotation_extraction import extract_quotation
from app.procurement.quotation_matching import MatchCandidate, match_line_item
from app.services import audit
from app.services.procurement import list_package_boq_items
from app.takeoff.pdf import render_page_png
from app.workers.base import build_worker_context, run_async, with_worker_session
from app.workers.celery_app import celery_app

_SYSTEM_TENANT_PLACEHOLDER = "00000000-0000-0000-0000-000000000000"


def _embed_quotation_line_items_best_effort(items: list[QuotationLineItem]) -> None:
    """Module B/C Phase 5: one batched embed_best_effort() call for every
    line item this ingestion pass just built (not one call per row) --
    same text shape app.procurement.quotation_matching.match_line_item()
    already fuzzy-matches with. Degrades to leaving description_embedding
    NULL on every row when the ONNX model isn't provisioned."""
    if not items:
        return
    texts = [f"{i.vendor_item_text or ''} {i.vendor_description_text or ''}".strip() for i in items]
    embeddings = embed_best_effort(texts)
    if embeddings is None:
        return
    for item, embedding in zip(items, embeddings, strict=True):
        item.description_embedding = embedding


class ImapMisconfiguredError(RuntimeError):
    """A non-production environment's IMAP_HOST doesn't match
    IMAP_DEV_ALLOWED_HOST. Fails closed: better to refuse to poll than risk
    a dev/test worker draining a real mailbox -- same posture as
    app/procurement/mailer.py::resolve_recipient for the outbound side."""


def _assert_dev_imap_host_is_safe(settings: Settings) -> None:
    if settings.app_env == "production":
        return
    if settings.imap_host != settings.imap_dev_allowed_host:
        raise ImapMisconfiguredError(
            f"APP_ENV={settings.app_env!r} but IMAP_HOST={settings.imap_host!r} != "
            f"IMAP_DEV_ALLOWED_HOST={settings.imap_dev_allowed_host!r} -- refusing to poll a "
            "mailbox that might be a real one from a non-production environment."
        )


def _system_ctx() -> RequestContext:
    return build_worker_context(_SYSTEM_TENANT_PLACEHOLDER)


# ---------------------------------------------------------------------------
# poll_inbound_mailbox
# ---------------------------------------------------------------------------


def _fetch_uid_validity(conn: imaplib.IMAP4) -> str:
    raw = conn.untagged_responses.get("UIDVALIDITY")
    return raw[0].decode() if raw else "0"


async def _known_uids_body(session: AsyncSession, uid_validity: str) -> set[str]:
    result = await session.execute(select(InboundEmail.imap_uid).where(InboundEmail.imap_uid_validity == uid_validity))
    return {row[0] for row in result.all()}


async def _ingest_one_email_body(session: AsyncSession, uid_validity: str, imap_uid: str, raw_bytes: bytes) -> None:
    settings = get_settings()
    msg = email.message_from_bytes(raw_bytes)
    from_address = (parseaddr(msg.get("From", ""))[1] or "").lower()
    to_address = parseaddr(msg.get("To", ""))[1] or ""
    from_domain = from_address.rsplit("@", 1)[-1] if "@" in from_address else ""
    subject = msg.get("Subject")
    try:
        received_at = parsedate_to_datetime(msg.get("Date")) if msg.get("Date") else datetime.now(timezone.utc)
        if received_at.tzinfo is None:
            received_at = received_at.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        received_at = datetime.now(timezone.utc)

    auth_results = parse_authentication_results(msg.get("Authentication-Results"))
    outcome = await match_inbound_email(
        session, from_address=from_address, to_address=to_address, auth_results=auth_results, settings=settings
    )

    raw_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    object_key = f"inbound/{uid_validity}/{imap_uid}.eml"
    await put_object_streaming(object_key, raw_bytes, "message/rfc822", bucket=settings.s3_bucket_procurement)

    inbound_email = InboundEmail(
        tenant_id=outcome.tenant_id, rfq_id=outcome.rfq_id, imap_uid_validity=uid_validity, imap_uid=imap_uid,
        message_id=msg.get("Message-ID"), from_address=from_address, from_domain=from_domain, to_address=to_address,
        subject=subject, received_at=received_at, match_status=outcome.match_status, needs_review=outcome.needs_review,
        review_reasons=outcome.review_reasons, spf_result=auth_results.spf, dkim_result=auth_results.dkim,
        dmarc_result=auth_results.dmarc, auth_results_raw=msg.get("Authentication-Results"),
        raw_object_key=object_key, raw_sha256=raw_sha256,
    )
    session.add(inbound_email)
    await session.flush()

    if outcome.tenant_id is not None:
        tenant_ctx = RequestContext(tenant_id=outcome.tenant_id, user_id=None, sub="system", is_system=True)
        await audit.record(
            session, tenant_ctx, action=AuditAction.CREATE, entity_type="inbound_email", entity_id=inbound_email.id,
            payload={"match_status": outcome.match_status, "needs_review": outcome.needs_review, "review_reasons": outcome.review_reasons},
        )

    if outcome.rfq_id is not None and outcome.match_status == InboundEmailMatchStatus.MATCHED.value:
        rfq = (await session.execute(select(Rfq).where(Rfq.id == outcome.rfq_id))).scalar_one()
        if rfq.status == RfqStatus.SENT.value:
            rfq.status = RfqStatus.RESPONDED.value
            await session.flush()

    attachment_ids: list[uuid.UUID] = []
    for part in msg.walk():
        filename = part.get_filename()
        if not filename or part.get_content_maintype() == "multipart":
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        att_sha256 = hashlib.sha256(payload).hexdigest()
        att_key = f"inbound/{uid_validity}/{imap_uid}-{len(attachment_ids)}-{filename}"
        await put_object_streaming(att_key, payload, part.get_content_type(), bucket=settings.s3_bucket_procurement)
        attachment = QuotationAttachment(
            tenant_id=outcome.tenant_id, inbound_email_id=inbound_email.id, filename=filename,
            content_type_declared=part.get_content_type(), size_bytes=len(payload), raw_object_key=att_key, raw_sha256=att_sha256,
        )
        session.add(attachment)
        await session.flush()
        attachment_ids.append(attachment.id)

    auto_process = outcome.match_status == InboundEmailMatchStatus.MATCHED.value and not outcome.needs_review
    if auto_process:
        # One task for the whole email, not one per attachment -- an email
        # with several attachments is one submission (see module docstring).
        process_inbound_email_task.delay(str(inbound_email.id), str(outcome.tenant_id))


async def _poll_and_ingest() -> None:
    """The IMAP fetch (blocking, but that's fine -- this task does nothing
    else concurrently) plus every DB access for one poll cycle, all inside
    ONE asyncio.run() call (see poll_inbound_mailbox). Each email still gets
    its own with_worker_session() (own transaction), so one bad message
    never rolls back ones already ingested -- only the *event loop* is
    shared, not the session/transaction."""
    settings = get_settings()
    imap_cls = imaplib.IMAP4_SSL if settings.imap_use_ssl else imaplib.IMAP4
    conn = imap_cls(settings.imap_host, settings.imap_port)
    fetched: list[tuple[str, bytes]] = []
    try:
        conn.login(settings.imap_user, settings.imap_password)
        conn.select(settings.imap_mailbox, readonly=True)
        uid_validity = _fetch_uid_validity(conn)
        typ, data = conn.uid("search", None, "ALL")
        all_uids = [u.decode() for u in data[0].split()] if typ == "OK" and data and data[0] else []

        known = await with_worker_session(_system_ctx(), _known_uids_body, uid_validity)
        for uid in all_uids:
            if uid in known:
                continue
            typ, msg_data = conn.uid("fetch", uid, "(RFC822)")
            if typ != "OK" or not msg_data or msg_data[0] is None:
                continue
            fetched.append((uid, msg_data[0][1]))
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001 -- best-effort cleanup, never masks a real error above
            pass

    for uid, raw_bytes in fetched:
        await with_worker_session(_system_ctx(), _ingest_one_email_body, uid_validity, uid, raw_bytes)


@celery_app.task(bind=True, name="app.workers.tasks.quotation_ingestion.poll_inbound_mailbox", soft_time_limit=120)
def poll_inbound_mailbox(self) -> None:
    _assert_dev_imap_host_is_safe(get_settings())
    # A single run_async() call for the whole task, not one per email:
    # app/db/session.py's cached engine's asyncpg connection pool binds each
    # connection to the event loop that created it, and calling run_async()
    # (a fresh asyncio.run(), i.e. a fresh event loop) more than once in the
    # same worker process raised "Future attached to a different loop" the
    # first time this ran against more than one queued message -- found
    # while running `make dev-simulate-quotes` end to end.
    run_async(_poll_and_ingest)()


# ---------------------------------------------------------------------------
# process_inbound_email
# ---------------------------------------------------------------------------


async def _create_quotation_version(
    session: AsyncSession, *, rfq: Rfq, inbound_email: InboundEmail, attachment: QuotationAttachment | None,
    extraction_method: str, currency: str | None, vat_inclusive: bool | None, status: str, line_item_count: int,
) -> Quotation:
    """SRS change #3: versions per (rfq, vendor); a new version never
    mutates an earlier one's own line items. Whether it becomes is_current
    automatically is deliberately conservative:

    - A quotation with zero line items (status NEEDS_REVIEW -- the pricing
      sheet's identity check failed -- or EXTRACTION_EMPTY -- extraction
      found nothing) never becomes current automatically, ever, even as the
      very first version for this (rfq, vendor). It's recorded for manual
      follow-up; a reviewer promotes it explicitly
      (app/services/quotation_ingestion.py::promote_quotation_version) if
      it's ever meant to be the active one.
    - Otherwise, a new version replaces the current one automatically only
      if the existing current version has no *accepted* line item yet. If
      it does, the new version is recorded but left non-current -- an
      accepted quote is never silently superseded by a fresher, possibly
      worse, reply; promotion requires the same explicit reviewer action.

    Found and fixed after a live run let an empty vision-LLM extraction
    (zero line items) become current over an already-accepted deterministic
    quote -- see tests/integration/test_quotation_versioning.py.
    """
    # Serializes concurrent callers for the SAME (rfq, vendor): two
    # attachments on two different emails from the same vendor can each be
    # routed to extract_quotation_task and land on two different vLLM
    # worker forks at once, each independently computing MAX(version_no)
    # from a snapshot that doesn't yet see the other's still-uncommitted
    # INSERT, and colliding on uq_quotations_rfq_vendor_version -- found
    # running `make dev-simulate-quotes` with two PDF replies against the
    # same vendor. pg_advisory_xact_lock blocks the second caller here until
    # the first's transaction commits (or rolls back) and releases it
    # automatically -- no separate unlock/cleanup needed.
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": f"{rfq.id}:{rfq.vendor_id}"})

    existing_current = (
        await session.execute(
            select(Quotation).where(Quotation.rfq_id == rfq.id, Quotation.vendor_id == rfq.vendor_id, Quotation.is_current.is_(True))
        )
    ).scalar_one_or_none()
    # version_no must come from the highest version ever created for this
    # (rfq, vendor), not from existing_current: a prior version that never
    # became current (an empty/failed extraction, per the rule above) still
    # occupies its own version_no, and existing_current can be None even
    # when earlier versions exist -- found via
    # uq_quotations_rfq_vendor_version colliding in
    # tests/integration/test_quotation_versioning.py.
    max_version_no = (
        await session.execute(select(func.max(Quotation.version_no)).where(Quotation.rfq_id == rfq.id, Quotation.vendor_id == rfq.vendor_id))
    ).scalar_one()

    is_empty = line_item_count == 0 or status in (QuotationStatus.NEEDS_REVIEW.value, QuotationStatus.EXTRACTION_EMPTY.value)
    existing_has_accepted = False
    if existing_current is not None and not is_empty:
        existing_has_accepted = (
            await session.execute(
                select(QuotationLineItem.id)
                .where(QuotationLineItem.quotation_id == existing_current.id, QuotationLineItem.status == QuotationLineItemStatus.ACCEPTED.value)
                .limit(1)
            )
        ).scalar_one_or_none() is not None

    make_current = not is_empty and not existing_has_accepted
    version_no = (max_version_no or 0) + 1
    if existing_current is not None and make_current:
        existing_current.is_current = False
        await session.flush()

    is_late = bool(rfq.due_at and inbound_email.received_at > rfq.due_at)
    quotation = Quotation(
        tenant_id=rfq.tenant_id, rfq_id=rfq.id, vendor_id=rfq.vendor_id, package_id=rfq.package_id, project_id=rfq.project_id,
        inbound_email_id=inbound_email.id, source_attachment_id=attachment.id if attachment else None, extraction_method=extraction_method,
        version_no=version_no, is_current=make_current, currency=currency, vat_inclusive=vat_inclusive,
        submitted_at=inbound_email.received_at, is_late=is_late, status=status,
    )
    session.add(quotation)
    await session.flush()
    return quotation


async def _link_supporting_documents(session: AsyncSession, quotation: Quotation, attachment_ids: list[uuid.UUID]) -> None:
    """Every attachment belonging to this quotation's inbound email links
    back to it -- whether it was the primary extraction source or a
    supporting document (e.g. a signed PDF alongside the priced xlsx) --
    never extracted as a separate, competing quote."""
    if not attachment_ids:
        return
    await session.execute(
        sa_update(QuotationAttachment).where(QuotationAttachment.id.in_(attachment_ids)).values(quotation_id=quotation.id)
    )


async def _ingest_deterministic(
    session: AsyncSession, *, rfq: Rfq, attachment: QuotationAttachment, inbound_email: InboundEmail, data: bytes,
    boq_items: list, all_attachment_ids: list[uuid.UUID],
) -> None:
    expected_ids = {item.id for item in boq_items}
    parsed = parse_pricing_sheet(data, expected_rfq_id=rfq.id, expected_reply_token=rfq.reply_token, expected_boq_line_item_ids=expected_ids)

    quotation = await _create_quotation_version(
        session, rfq=rfq, inbound_email=inbound_email, attachment=attachment,
        extraction_method=QuotationExtractionMethod.DETERMINISTIC_XLSX.value,
        currency=parsed.currency, vat_inclusive=parsed.vat_inclusive,
        status=QuotationStatus.PROPOSED.value if parsed.ok else QuotationStatus.NEEDS_REVIEW.value,
        line_item_count=len(parsed.rows) if parsed.ok else 0,
    )
    await _link_supporting_documents(session, quotation, all_attachment_ids)
    if not parsed.ok:
        return

    boq_by_id = {item.id: item for item in boq_items}
    new_items: list[QuotationLineItem] = []
    for row in parsed.rows:
        boq_item = boq_by_id.get(row.boq_line_item_id)
        quantity = boq_item.boq_quantity if boq_item else None
        extended_computed = (row.rate.value * quantity) if row.rate.value is not None and quantity is not None else None
        line_status = QuotationLineItemStatus.NEEDS_REVIEW.value if row.rate.needs_review else QuotationLineItemStatus.PROPOSED.value
        item = QuotationLineItem(
            tenant_id=rfq.tenant_id, quotation_id=quotation.id, project_id=rfq.project_id,
            boq_line_item_id=row.boq_line_item_id, vendor_description_text=boq_item.description if boq_item else None,
            unit_price=row.rate.value, quantity=quantity, extended_price_computed=extended_computed,
            confidence=Decimal("1.0"), source=QuotationLineSource.DETERMINISTIC.value, match_method=LineItemMatchMethod.ROW_ID.value,
            remarks_text=row.remarks, status=line_status,
        )
        session.add(item)
        new_items.append(item)
    _embed_quotation_line_items_best_effort(new_items)
    await session.flush()


def _pick_primary(accepted: list[tuple[QuotationAttachment, bytes, str | None]]) -> tuple[QuotationAttachment, bytes, str | None]:
    """Our own pricing sheet if present, else the first accepted attachment
    in the order the email listed them."""
    for attachment, data, sniffed in accepted:
        if sniffed == "xlsx" and looks_like_our_pricing_sheet(data):
            return attachment, data, sniffed
    return accepted[0]


async def _process_inbound_email_body(session: AsyncSession, inbound_email_id: str) -> None:
    """Safety-checks every attachment on this ONE email, then routes the
    whole email as a single submission (see module docstring) -- never one
    Quotation per attachment."""
    settings = get_settings()
    inbound_email = (await session.execute(select(InboundEmail).where(InboundEmail.id == UUID(inbound_email_id)))).scalar_one()
    if inbound_email.rfq_id is None:
        return  # never parse without a matched/attached RFQ, regardless of how this task was reached

    attachments = (
        await session.execute(select(QuotationAttachment).where(QuotationAttachment.inbound_email_id == inbound_email.id))
    ).scalars().all()
    if not attachments:
        return  # a plain-text reply with nothing attached -- nothing to review yet

    accepted: list[tuple[QuotationAttachment, bytes, str | None]] = []
    for attachment in attachments:
        data = await get_object_bytes(attachment.raw_object_key, bucket=settings.s3_bucket_procurement)
        safety = check_attachment(filename=attachment.filename, data=data, settings=settings)
        attachment.safety_status = safety.status
        attachment.content_type_sniffed = safety.sniffed_content_type
        attachment.rejection_reason = safety.reason
        attachment.processed_at = datetime.now(timezone.utc)
        if safety.status == AttachmentSafetyStatus.ACCEPTED.value:
            accepted.append((attachment, data, safety.sniffed_content_type))
    await session.flush()

    all_attachment_ids = [a.id for a in attachments]
    rfq = (await session.execute(select(Rfq).where(Rfq.id == inbound_email.rfq_id))).scalar_one()

    if not accepted:
        # Every attachment failed the safety check -- still record a shell
        # submission (never is_current automatically, see
        # _create_quotation_version) so it's visible for manual follow-up
        # instead of silently vanishing.
        quotation = await _create_quotation_version(
            session, rfq=rfq, inbound_email=inbound_email, attachment=None, extraction_method=QuotationExtractionMethod.NONE.value,
            currency=None, vat_inclusive=None, status=QuotationStatus.EXTRACTION_EMPTY.value, line_item_count=0,
        )
        await _link_supporting_documents(session, quotation, all_attachment_ids)
        return

    boq_items = await list_package_boq_items(session, rfq.package_id)
    primary_attachment, primary_data, primary_sniffed = _pick_primary(accepted)
    primary_attachment.is_primary = True
    await session.flush()
    supporting_ids = [a.id for a in attachments if a.id != primary_attachment.id]

    if primary_sniffed == "xlsx" and looks_like_our_pricing_sheet(primary_data):
        await _ingest_deterministic(
            session, rfq=rfq, attachment=primary_attachment, inbound_email=inbound_email, data=primary_data,
            boq_items=boq_items, all_attachment_ids=all_attachment_ids,
        )
        return

    if primary_sniffed == "pdf":
        extraction_method = QuotationExtractionMethod.VLM_PDF.value
    elif primary_sniffed in ("jpeg", "png"):
        extraction_method = QuotationExtractionMethod.VLM_IMAGE.value
    elif primary_sniffed == "xlsx":
        extraction_method = QuotationExtractionMethod.VLM_XLSX_OTHER.value
    else:
        extraction_method = QuotationExtractionMethod.VLM_CSV.value

    extract_quotation_task.delay(str(primary_attachment.id), extraction_method, str(inbound_email.tenant_id))


@celery_app.task(
    bind=True, name="app.workers.tasks.quotation_ingestion.process_inbound_email", soft_time_limit=90,
    autoretry_for=(ConnectionError,), retry_backoff=True, max_retries=2,
)
def process_inbound_email_task(self, inbound_email_id: str, tenant_id: str) -> None:
    ctx = build_worker_context(tenant_id)
    run_async(lambda: with_worker_session(ctx, _process_inbound_email_body, inbound_email_id))()


# ---------------------------------------------------------------------------
# extract_quotation_task (vLLM path)
# ---------------------------------------------------------------------------


async def _extract_quotation_body(session: AsyncSession, attachment_id: str, extraction_method: str) -> None:
    settings = get_settings()
    attachment = (await session.execute(select(QuotationAttachment).where(QuotationAttachment.id == UUID(attachment_id)))).scalar_one()
    inbound_email = (await session.execute(select(InboundEmail).where(InboundEmail.id == attachment.inbound_email_id))).scalar_one()
    rfq = (await session.execute(select(Rfq).where(Rfq.id == inbound_email.rfq_id))).scalar_one()
    boq_items = await list_package_boq_items(session, rfq.package_id)
    boq_by_id = {item.id: item for item in boq_items}
    candidates = [MatchCandidate(boq_line_item_id=i.id, item_no=i.item_no, description=i.description) for i in boq_items]

    data = await get_object_bytes(attachment.raw_object_key, bucket=settings.s3_bucket_procurement)

    if extraction_method == QuotationExtractionMethod.VLM_PDF.value:
        page_png = render_page_png(data, 0)
        result = await extract_quotation(candidate_text="", image_bytes=page_png, image_mime="image/png", page_number=1, page_count=1)
    elif extraction_method == QuotationExtractionMethod.VLM_IMAGE.value:
        mime = "image/png" if attachment.content_type_sniffed == "png" else "image/jpeg"
        result = await extract_quotation(candidate_text="", image_bytes=data, image_mime=mime)
    elif extraction_method == QuotationExtractionMethod.VLM_XLSX_OTHER.value:
        result = await extract_quotation(candidate_text=dump_workbook_text(data), image_bytes=None)
    else:
        result = await extract_quotation(candidate_text=data.decode("utf-8", errors="replace"), image_bytes=None)

    status = QuotationStatus.PROPOSED.value if result.line_items else QuotationStatus.EXTRACTION_EMPTY.value
    quotation = await _create_quotation_version(
        session, rfq=rfq, inbound_email=inbound_email, attachment=attachment, extraction_method=extraction_method,
        currency=result.currency, vat_inclusive=result.vat_inclusive, status=status, line_item_count=len(result.line_items),
    )
    other_attachment_ids = (
        await session.execute(
            select(QuotationAttachment.id).where(QuotationAttachment.inbound_email_id == inbound_email.id, QuotationAttachment.id != attachment.id)
        )
    ).scalars().all()
    await _link_supporting_documents(session, quotation, [attachment.id, *other_attachment_ids])

    new_items: list[QuotationLineItem] = []
    for item in result.line_items:
        match = match_line_item(vendor_item_text=item.vendor_item_text, vendor_description_text=item.vendor_description_text, candidates=candidates)
        boq_item = boq_by_id.get(match.boq_line_item_id) if match.boq_line_item_id else None

        extended_computed = None
        arithmetic_mismatch = False
        if item.unit_price is not None and item.quantity is not None:
            extended_computed = Decimal(str(item.unit_price)) * Decimal(str(item.quantity))
            if item.extended_price_stated is not None:
                arithmetic_mismatch = abs(extended_computed - Decimal(str(item.extended_price_stated))) > Decimal("0.01")

        quantity_mismatch = (
            boq_item is not None and boq_item.boq_quantity is not None and item.quantity is not None
            and abs(Decimal(str(item.quantity)) - Decimal(str(boq_item.boq_quantity))) > Decimal("0.01")
        )

        line_status = QuotationLineItemStatus.PROPOSED.value if match.boq_line_item_id else QuotationLineItemStatus.NEEDS_REVIEW.value
        new_item = QuotationLineItem(
            tenant_id=rfq.tenant_id, quotation_id=quotation.id, project_id=rfq.project_id,
            boq_line_item_id=match.boq_line_item_id, vendor_item_text=item.vendor_item_text,
            vendor_description_text=item.vendor_description_text, unit_price=item.unit_price, quantity=item.quantity,
            extended_price_stated=item.extended_price_stated, extended_price_computed=extended_computed,
            arithmetic_mismatch=arithmetic_mismatch, quantity_mismatch=bool(quantity_mismatch),
            confidence=Decimal(str(round(match.score, 3))), source=QuotationLineSource.LLM.value,
            match_method=match.match_method, remarks_text=item.remarks_text, status=line_status,
        )
        session.add(new_item)
        new_items.append(new_item)
    _embed_quotation_line_items_best_effort(new_items)
    await session.flush()

    for excl in result.exclusions:
        session.add(
            QuotationExclusionFlag(
                tenant_id=rfq.tenant_id, quotation_id=quotation.id, project_id=rfq.project_id,
                flag_text=excl.flag_text, source_quote_text=excl.source_quote_text,
                confidence=Decimal(str(round(result.confidence, 3))),
            )
        )
    await session.flush()


@celery_app.task(
    bind=True, name="app.workers.tasks.quotation_ingestion.extract_quotation", soft_time_limit=180,
    autoretry_for=(ConnectionError, TimeoutError), retry_backoff=True, retry_jitter=True, max_retries=3,
)
def extract_quotation_task(self, attachment_id: str, extraction_method: str, tenant_id: str) -> None:
    ctx = build_worker_context(tenant_id)
    run_async(lambda: with_worker_session(ctx, _extract_quotation_body, attachment_id, extraction_method))()
