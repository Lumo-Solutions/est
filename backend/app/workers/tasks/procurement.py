"""Module C1 outbound dispatch: renders and sends one RFQ email + pricing
sheet, off the request path. See app/services/procurement.py::_queue for
how this gets enqueued and its idempotency contract."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.context import current_context
from app.core.enums import AuditAction, RfqStatus
from app.integrations.s3 import put_object_streaming
from app.models.boq import BoqLineItem
from app.models.procurement import ProcurementPackage, Rfq
from app.models.tenancy import Project, Tenant
from app.models.vendors import Vendor, VendorContact
from app.procurement.content import RfqLineItem
from app.procurement.mailer import send_rfq_email
from app.procurement.pricing_sheet import build_pricing_workbook
from app.procurement.rendering import render_rfq_email
from app.services import audit
from app.services.procurement import list_package_boq_items
from app.workers.base import build_worker_context, run_async, with_worker_session
from app.workers.celery_app import celery_app


def _rfq_line_items(boq_items: list[BoqLineItem]) -> list[RfqLineItem]:
    return [
        RfqLineItem(
            boq_line_item_id=item.id, item_no=item.item_no, description=item.description,
            uom=item.uom, quantity=float(item.boq_quantity) if item.boq_quantity is not None else None,
        )
        for item in boq_items
    ]


async def _dispatch_rfq_body(session: AsyncSession, rfq_id: str) -> None:
    ctx = current_context()
    rfq = (await session.execute(select(Rfq).where(Rfq.id == UUID(rfq_id)))).scalar_one_or_none()
    if rfq is None or rfq.status != RfqStatus.QUEUED.value:
        # Idempotency guard: a Celery redelivery of a task that already ran
        # to completion (success or failure already recorded) sees a
        # status other than `queued` and is a no-op -- see
        # app/services/procurement.py::_queue/dispatch_rfq/resend_rfq.
        return

    rfq.dispatch_attempts += 1
    package = (await session.execute(select(ProcurementPackage).where(ProcurementPackage.id == rfq.package_id))).scalar_one()
    vendor = (await session.execute(select(Vendor).where(Vendor.id == rfq.vendor_id))).scalar_one()
    # scalar_one_or_none(), not scalar_one(): this is only for the email's
    # signature line -- a missing `tenants` row (there is no FK forcing one
    # to exist; see app/db/base.py::TenantMixin) should not fail an
    # otherwise-deliverable RFQ.
    tenant = (await session.execute(select(Tenant).where(Tenant.id == rfq.tenant_id))).scalar_one_or_none()
    tenant_name = tenant.name if tenant is not None else "INSTALLTEC"
    # Falls back to the raw tenant_id (never contains '.', so still parses
    # safely -- see app/procurement/inbound_address.py) in the same
    # extremely-unlikely no-tenants-row case as tenant_name above.
    tenant_slug = tenant.slug if tenant is not None else str(rfq.tenant_id)
    contact = None
    if rfq.vendor_contact_id is not None:
        contact = (
            await session.execute(select(VendorContact).where(VendorContact.id == rfq.vendor_contact_id))
        ).scalar_one_or_none()
    vendor_email = (contact.email if contact and contact.email else None) or vendor.primary_email

    if not vendor_email:
        rfq.status = RfqStatus.FAILED.value
        rfq.dispatch_error = "Vendor has no contactable email on file"
        await session.flush()
        await audit.record(
            session, ctx, action=AuditAction.SEND, entity_type="rfq", entity_id=rfq.id, project_id=rfq.project_id,
            payload={"result": "failed", "error": rfq.dispatch_error},
        )
        return

    boq_items = await list_package_boq_items(session, rfq.package_id)
    rfq_items = _rfq_line_items(boq_items)
    subject = f"RFQ {rfq.rfq_ref} - {package.name}"
    html = render_rfq_email(
        vendor_name=vendor.legal_name, rfq_ref=rfq.rfq_ref, package_name=package.name, items=rfq_items,
        due_at=rfq.due_at.date().isoformat() if rfq.due_at else None, sender_name=f"{tenant_name} Procurement Team",
    )
    project = (await session.execute(select(Project).where(Project.id == rfq.project_id))).scalar_one()
    xlsx_bytes, xlsx_sha256 = build_pricing_workbook(
        rfq_id=rfq.id, rfq_ref=rfq.rfq_ref, reply_token=rfq.reply_token, package_name=package.name, items=rfq_items,
        default_currency=project.base_currency,
    )
    attachment_key = f"{rfq.tenant_id}/{rfq.id}.xlsx"

    try:
        sent = await send_rfq_email(
            vendor_email=vendor_email, subject=subject, html_body=html, attachment_bytes=xlsx_bytes,
            attachment_filename=f"{rfq.rfq_ref}.xlsx", reply_token=rfq.reply_token, tenant_slug=tenant_slug,
        )
    except Exception as exc:  # noqa: BLE001 -- any SMTP/config failure lands the RFQ in `failed`, never crashes the worker
        rfq.status = RfqStatus.FAILED.value
        rfq.dispatch_error = str(exc)[:2000]
        await session.flush()
        await audit.record(
            session, ctx, action=AuditAction.SEND, entity_type="rfq", entity_id=rfq.id, project_id=rfq.project_id,
            payload={"result": "failed", "error": rfq.dispatch_error},
        )
        return

    # Upload after a successful send, not before: an xlsx nobody received
    # isn't "what the vendor received" (see Rfq model docstring) -- keeping
    # the attachment_* columns NULL on a failed attempt makes that visible.
    await put_object_streaming(
        attachment_key, xlsx_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        bucket=get_settings().s3_bucket_procurement,
    )

    rfq.status = RfqStatus.SENT.value
    rfq.sent_at = datetime.now(timezone.utc)
    rfq.message_id = sent.message_id
    rfq.subject = subject
    rfq.body_html = html
    rfq.attachment_object_key = attachment_key
    rfq.attachment_sha256 = xlsx_sha256
    rfq.dispatch_error = None
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.SEND, entity_type="rfq", entity_id=rfq.id, project_id=rfq.project_id,
        payload={
            "result": "sent", "to": sent.to_address, "original_to": sent.original_to,
            "message_id": sent.message_id, "attachment_sha256": xlsx_sha256,
        },
    )


@celery_app.task(bind=True, name="app.workers.tasks.procurement.dispatch_rfq_task")
def dispatch_rfq_task(self, rfq_id: str, tenant_id: str, actor_user_id: str | None, actor_roles: list[str] | None = None) -> None:
    ctx = build_worker_context(tenant_id, actor_user_id, actor_roles)
    run_async(lambda: with_worker_session(ctx, _dispatch_rfq_body, rfq_id))()
