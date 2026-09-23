from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql.ranges import Range
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import RequestContext
from app.core.enums import AuditAction
from app.core.errors import ConflictError, NotFoundError
from app.models.prequal import Authority, CertificateType, VendorCertificate, VendorPrequalification
from app.schemas.prequal import PrequalificationDecision, VendorCertificateCreate
from app.services import audit


async def list_authorities(session: AsyncSession) -> list[Authority]:
    return list((await session.execute(select(Authority))).scalars().all())


async def list_certificate_types(session: AsyncSession) -> list[CertificateType]:
    return list((await session.execute(select(CertificateType))).scalars().all())


async def add_certificate(
    session: AsyncSession, ctx: RequestContext, data: VendorCertificateCreate
) -> VendorCertificate:
    cert = VendorCertificate(
        tenant_id=ctx.tenant_id,
        vendor_id=data.vendor_id,
        certificate_type_id=data.certificate_type_id,
        certificate_no=data.certificate_no,
        issue_date=data.issue_date,
        expiry_date=data.expiry_date,
        document_object_key=data.document_object_key,
        document_sha256=data.document_sha256,
        status="pending_verification",
    )
    session.add(cert)
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.CREATE, entity_type="vendor_certificate", entity_id=cert.id,
        payload={"vendor_id": str(data.vendor_id), "certificate_type_id": str(data.certificate_type_id)},
    )
    return cert


async def verify_certificate(session: AsyncSession, ctx: RequestContext, certificate_id: UUID) -> VendorCertificate:
    result = await session.execute(select(VendorCertificate).where(VendorCertificate.id == certificate_id))
    cert = result.scalar_one_or_none()
    if cert is None:
        raise NotFoundError(f"Certificate {certificate_id} not found")
    cert.status = "valid"
    cert.verified_by = ctx.user_id
    cert.verified_at = datetime.now(timezone.utc)
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.UPDATE, entity_type="vendor_certificate", entity_id=cert.id,
        payload={"status": "valid"},
    )
    return cert


async def get_prequalification_as_of(
    session: AsyncSession, vendor_id: UUID, as_of: date, scope_trade_node_id: UUID | None = None
) -> VendorPrequalification | None:
    stmt = select(VendorPrequalification).where(
        VendorPrequalification.vendor_id == vendor_id,
        VendorPrequalification.scope_trade_node_id.is_(scope_trade_node_id)
        if scope_trade_node_id is None
        else VendorPrequalification.scope_trade_node_id == scope_trade_node_id,
    )
    result = await session.execute(stmt)
    for row in result.scalars().all():
        rng: Range = row.effective_period
        lower_ok = rng.lower is None or rng.lower <= as_of
        upper_ok = rng.upper is None or as_of < rng.upper
        if lower_ok and upper_ok:
            return row
    return None


async def decide_prequalification(
    session: AsyncSession, ctx: RequestContext, vendor_id: UUID, data: PrequalificationDecision
) -> VendorPrequalification:
    """Effective-dated transition: closes the currently-open row (if any) at
    `effective_from` and inserts the new one, in one transaction. The GiST
    exclusion constraint on (tenant, vendor, scope, period) guarantees no
    overlap even under concurrent writers."""
    current = await get_prequalification_as_of(session, vendor_id, data.effective_from, data.scope_trade_node_id)
    if current is not None and current.effective_period.lower == data.effective_from:
        raise ConflictError("A prequalification decision already starts on this date")

    if current is not None:
        await session.execute(
            text(
                "UPDATE vendor_prequalifications SET effective_period = daterange(lower(effective_period), :d) "
                "WHERE id = :id"
            ),
            {"d": data.effective_from, "id": str(current.id)},
        )

    new_row = VendorPrequalification(
        tenant_id=ctx.tenant_id,
        vendor_id=vendor_id,
        status=data.status,
        grade=data.grade,
        max_award_value=data.max_award_value,
        scope_trade_node_id=data.scope_trade_node_id,
        effective_period=Range(lower=data.effective_from, upper=None),
        decided_by=ctx.user_id,
        decided_at=datetime.now(timezone.utc),
        decision_note=data.decision_note,
        supersedes_id=current.id if current else None,
    )
    session.add(new_row)
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.APPROVE if data.status == "approved" else AuditAction.UPDATE,
        entity_type="vendor_prequalification", entity_id=new_row.id,
        payload={"vendor_id": str(vendor_id), "status": data.status, "effective_from": data.effective_from.isoformat()},
    )
    return new_row
