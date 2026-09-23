from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import RequestContext
from app.core.enums import AuditAction
from app.core.errors import DuplicateVendorError, NotFoundError
from app.models.vendors import Vendor, VendorDuplicateCandidate
from app.schemas.vendors import VendorCreate
from app.services import audit
from app.services.dedupe import (
    AUTO_CANDIDATE_THRESHOLD,
    VendorSignature,
    classify,
    contact_fingerprint,
    email_domain,
    normalize_address,
    normalize_license,
    normalize_name,
    phone_last9,
    score_pair,
)

_BLOCKING_CANDIDATE_LIMIT = 200


def _signature(v: Vendor) -> VendorSignature:
    return VendorSignature(
        normalized_name=v.normalized_name,
        normalized_license=v.normalized_license,
        normalized_address=v.normalized_address,
        email_domain=v.email_domain,
        phone_last9=v.phone_last9,
        trn_vat_no=v.trn_vat_no,
    )


async def _find_blocking_candidates(
    session: AsyncSession, tenant_id: UUID, v: Vendor, exclude_id: UUID | None
) -> list[Vendor]:
    """Cheap SQL-side blocking: trigram similarity on name/license, or exact
    match on phone/email-domain/contact fingerprint. Scoring happens in
    Python afterwards (services/dedupe.py)."""
    stmt = (
        select(Vendor)
        .where(Vendor.tenant_id == tenant_id, Vendor.status != "merged")
        .where(
            text(
                "(normalized_license % :lic OR normalized_name % :name "
                "OR phone_last9 = :phone OR email_domain = :domain "
                "OR contact_fingerprint = :fp)"
            ).bindparams(
                lic=v.normalized_license or "",
                name=v.normalized_name,
                phone=v.phone_last9 or "",
                domain=v.email_domain or "",
                fp=v.contact_fingerprint or "",
            )
        )
        .limit(_BLOCKING_CANDIDATE_LIMIT)
    )
    if exclude_id is not None:
        stmt = stmt.where(Vendor.id != exclude_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def check_duplicates(
    session: AsyncSession, tenant_id: UUID, v: Vendor, exclude_id: UUID | None = None
) -> list[tuple[Vendor, float, dict[str, float]]]:
    candidates = await _find_blocking_candidates(session, tenant_id, v, exclude_id)
    sig = _signature(v)
    scored = []
    for candidate in candidates:
        result = score_pair(sig, _signature(candidate))
        if classify(result.score) != "ignore":
            scored.append((candidate, result.score, result.signals))
    scored.sort(key=lambda t: t[1], reverse=True)
    return scored


def build_vendor(tenant_id: UUID, data: VendorCreate) -> Vendor:
    norm_license = normalize_license(data.trade_license_no)
    dom = email_domain(data.primary_email)
    p9 = phone_last9(data.primary_phone)
    return Vendor(
        tenant_id=tenant_id,
        legal_name=data.legal_name,
        trading_name=data.trading_name,
        normalized_name=normalize_name(data.legal_name),
        trade_license_no=data.trade_license_no,
        normalized_license=norm_license,
        license_authority=data.license_authority,
        trn_vat_no=data.trn_vat_no,
        country=data.country,
        emirate=data.emirate,
        address_line=data.address_line,
        normalized_address=normalize_address(data.address_line),
        primary_email=data.primary_email,
        email_domain=dom,
        primary_phone=data.primary_phone,
        phone_last9=p9,
        website_domain=data.website_domain,
        contact_fingerprint=contact_fingerprint(dom, p9, norm_license),
        notes=data.notes,
        status="draft",
    )


async def create_vendor(
    session: AsyncSession, ctx: RequestContext, data: VendorCreate, *, force: bool = False
) -> Vendor:
    vendor = build_vendor(ctx.tenant_id, data)
    scored = await check_duplicates(session, ctx.tenant_id, vendor)

    auto_candidates = [(c, s, sig) for c, s, sig in scored if s >= AUTO_CANDIDATE_THRESHOLD]
    if auto_candidates and not force:
        raise DuplicateVendorError(
            "One or more likely-duplicate vendors already exist; pass force=true to create anyway.",
            candidates=[{"vendor_id": str(c.id), "legal_name": c.legal_name, "score": s} for c, s, _ in auto_candidates],
        )

    session.add(vendor)
    await session.flush()

    for candidate, score, signals in scored:
        a_id, b_id = sorted((vendor.id, candidate.id), key=str)
        session.add(
            VendorDuplicateCandidate(
                tenant_id=ctx.tenant_id,
                vendor_a_id=a_id,
                vendor_b_id=b_id,
                score=score,
                signals=signals,
                status="open",
                detected_at=datetime.now(timezone.utc),
            )
        )

    await audit.record(
        session, ctx, action=AuditAction.CREATE, entity_type="vendor", entity_id=vendor.id,
        payload={"legal_name": vendor.legal_name, "forced": force, "duplicate_candidates": len(scored)},
    )
    return vendor


async def get_vendor(session: AsyncSession, tenant_id: UUID, vendor_id: UUID) -> Vendor:
    result = await session.execute(select(Vendor).where(Vendor.id == vendor_id))
    vendor = result.scalar_one_or_none()
    if vendor is None:
        raise NotFoundError(f"Vendor {vendor_id} not found")
    return vendor


async def list_vendors(
    session: AsyncSession, tenant_id: UUID, *, status: str | None = None, limit: int = 50, offset: int = 0
) -> tuple[list[Vendor], int]:
    base = select(Vendor)
    count_stmt = select(func.count()).select_from(Vendor)
    if status:
        base = base.where(Vendor.status == status)
        count_stmt = count_stmt.where(Vendor.status == status)

    total = (await session.execute(count_stmt)).scalar_one()
    rows = (
        await session.execute(base.order_by(Vendor.legal_name).limit(limit).offset(offset))
    ).scalars().all()
    return list(rows), total


async def scan_duplicates(session: AsyncSession, ctx: RequestContext, vendor_id: UUID) -> list[VendorDuplicateCandidate]:
    vendor = await get_vendor(session, ctx.tenant_id, vendor_id)
    scored = await check_duplicates(session, ctx.tenant_id, vendor, exclude_id=vendor.id)
    created: list[VendorDuplicateCandidate] = []
    for candidate, score, signals in scored:
        a_id, b_id = sorted((vendor.id, candidate.id), key=str)
        existing = await session.execute(
            select(VendorDuplicateCandidate).where(
                VendorDuplicateCandidate.vendor_a_id == a_id,
                VendorDuplicateCandidate.vendor_b_id == b_id,
            )
        )
        if existing.scalar_one_or_none() is not None:
            continue
        row = VendorDuplicateCandidate(
            tenant_id=ctx.tenant_id,
            vendor_a_id=a_id,
            vendor_b_id=b_id,
            score=score,
            signals=signals,
            status="open",
            detected_at=datetime.now(timezone.utc),
        )
        session.add(row)
        created.append(row)
    await session.flush()
    return created


async def list_duplicate_candidates(
    session: AsyncSession, tenant_id: UUID, *, status: str | None = "open"
) -> list[VendorDuplicateCandidate]:
    stmt = select(VendorDuplicateCandidate)
    if status:
        stmt = stmt.where(VendorDuplicateCandidate.status == status)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def resolve_duplicate(
    session: AsyncSession, ctx: RequestContext, candidate_id: UUID, resolution: str, note: str | None
) -> VendorDuplicateCandidate:
    result = await session.execute(
        select(VendorDuplicateCandidate).where(VendorDuplicateCandidate.id == candidate_id)
    )
    candidate = result.scalar_one_or_none()
    if candidate is None:
        raise NotFoundError(f"Duplicate candidate {candidate_id} not found")

    candidate.status = resolution
    candidate.resolved_by = ctx.user_id
    candidate.resolved_at = datetime.now(timezone.utc)
    candidate.resolution_note = note

    if resolution == "merged":
        vendor_b = await get_vendor(session, ctx.tenant_id, candidate.vendor_b_id)
        vendor_b.status = "merged"
        vendor_b.merged_into_vendor_id = candidate.vendor_a_id
        await audit.record(
            session, ctx, action=AuditAction.MERGE, entity_type="vendor", entity_id=vendor_b.id,
            payload={"merged_into": str(candidate.vendor_a_id)},
        )

    await audit.record(
        session, ctx, action=AuditAction.UPDATE, entity_type="vendor_duplicate_candidate", entity_id=candidate.id,
        payload={"resolution": resolution},
    )
    return candidate
