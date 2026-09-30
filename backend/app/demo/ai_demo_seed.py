"""Database side of the AI demo dataset (`python -m app.cli seed-ai-demo | seed-ai-demo-quotes`, cleaned by
`clean-demo-data`). Every row is tagged (see app/demo/ai_demo.py) so it can be removed again. DEV ONLY."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import RequestContext
from app.demo import ai_demo as demo
from app.models.boq import BoqLineItem
from app.models.costlib import CostItem
from app.models.prequal import CertificateType
from app.models.quotation_ingestion import Quotation, QuotationExclusionFlag, QuotationLineItem
from app.models.settlement import BidSettlement, BidSettlementLineItem
from app.models.taxonomy import TradeNode
from app.models.tenancy import Project
from app.models.vendors import Vendor, VendorTrade
from app.schemas.boq import BoqLineItemCreate
from app.schemas.costlib import CostItemCreate, CostRateComponentIn, RecordRateRequest
from app.schemas.prequal import PrequalificationDecision, VendorCertificateCreate
from app.schemas.vendors import VendorCreate
from app.services import boq as boq_service
from app.services import costlib as costlib_service
from app.services import prequal as prequal_service
from app.services import vendors as vendors_service


async def _trade_ids(session: AsyncSession, tenant_id: UUID) -> dict[str, UUID]:
    rows = (
        await session.execute(select(TradeNode).where(TradeNode.tenant_id == tenant_id, TradeNode.parent_id.is_(None)))
    ).scalars().all()
    return {r.code: r.id for r in rows}


async def seed_library_vendors_history(session: AsyncSession, ctx: RequestContext) -> dict[str, int]:
    tenant_id = ctx.tenant_id
    trades = await _trade_ids(session, tenant_id)
    if not trades:
        raise RuntimeError("No trade taxonomy found: run `make seed` first.")
    counts = {"cost_items": 0, "vendors": 0, "past_tenders": 0}

    # ---- cost library: each item gets an older closed rate and a current one (stale ones only an old rate)
    today = date.today()
    existing = set((await session.execute(select(CostItem.code).where(CostItem.tenant_id == tenant_id, CostItem.code.like(f"{demo.COST_CODE_PREFIX}%")))).scalars().all())
    if existing:  # a previous clean only deactivated them: bring them back
        await session.execute(update(CostItem).where(CostItem.tenant_id == tenant_id, CostItem.code.like(f"{demo.COST_CODE_PREFIX}%")).values(is_active=True))
    for it in demo.COST_LIBRARY:
        if it.code in existing:
            continue
        item = await costlib_service.create_cost_item(
            session, ctx, CostItemCreate(code=it.code, description=it.description, uom=it.uom, trade_node_id=trades.get(it.trade))
        )

        def components(rate: float) -> list[CostRateComponentIn]:
            mat = round(rate * 0.7, 2)
            return [CostRateComponentIn(component_type="material", description="Material", unit_cost=mat),
                    CostRateComponentIn(component_type="labour", description="Labour and plant", unit_cost=round(rate - mat, 2))]

        stale = it.code in demo.STALE_LIBRARY_CODES
        if it.prior_rate and not stale:
            await costlib_service.record_rate(
                session, ctx, item.id,
                RecordRateRequest(valid_from=date(2024, 1, 1), valid_to=date(2025, 6, 30), components=components(it.prior_rate), source_ref="AIDEMO history"),
            )
        await costlib_service.record_rate(
            session, ctx, item.id,
            RecordRateRequest(
                valid_from=date(2023, 1, 1) if stale else date(2025, 7, 1), components=components(it.rate), source_ref="AIDEMO current",
            ),
        )
        counts["cost_items"] += 1

    # ---- vendors
    cert_type = (
        await session.execute(select(CertificateType).where(CertificateType.tenant_id == tenant_id, CertificateType.code == "TRADE_LICENSE"))
    ).scalar_one_or_none()
    for i, spec in enumerate(demo.VENDORS, start=1):
        if (await session.execute(select(Vendor).where(Vendor.tenant_id == tenant_id, Vendor.legal_name == spec.name))).scalar_one_or_none():
            continue
        slug = "".join(ch for ch in spec.name.lower().replace(demo.VENDOR_PREFIX.lower(), "") if ch.isalnum())[:20]
        vendor = await vendors_service.create_vendor(
            session, ctx, VendorCreate(legal_name=spec.name, emirate=spec.emirate, primary_email=f"quotes@{slug}.aidemo.example", trade_license_no=f"AIDEMO-TL-{i:03d}"),
            force=True,
        )
        vendor.status = "active"
        await session.flush()
        for j, code in enumerate(spec.trades):
            if code in trades:
                session.add(VendorTrade(tenant_id=tenant_id, vendor_id=vendor.id, trade_node_id=trades[code], is_primary=(j == 0)))
        await session.flush()
        await vendors_service.replace_service_regions(session, ctx, vendor.id, list(spec.regions))
        status = {"approved": "approved", "expiring": "approved", "lapsed": "suspended", "pending": "pending"}[spec.prequal]
        await prequal_service.decide_prequalification(
            session, ctx, vendor.id,
            PrequalificationDecision(status=status, grade="A" if spec.prequal == "approved" else "B", effective_from=today - timedelta(days=400),
                                     decision_note="AIDEMO synthetic prequalification"),
        )
        if cert_type is not None:
            issued, expires = demo.cert_dates(spec, today)
            cert = await prequal_service.add_certificate(
                session, ctx,
                VendorCertificateCreate(vendor_id=vendor.id, certificate_type_id=cert_type.id, certificate_no=f"AIDEMO-{i:03d}", issue_date=issued, expiry_date=expires),
            )
            if spec.prequal != "pending":
                await prequal_service.verify_certificate(session, ctx, cert.id)
        counts["vendors"] += 1

    # ---- win/loss history: 15 past tenders, each a project with a priced settlement and a recorded outcome
    for pt in demo.history():
        if (await session.execute(select(Project).where(Project.tenant_id == tenant_id, Project.code == pt.code))).scalar_one_or_none():
            continue
        project = Project(tenant_id=tenant_id, code=pt.code, name=pt.name, status="awarded" if pt.outcome == "won" else "lost", base_currency="AED")
        session.add(project)
        await session.flush()
        settlement = BidSettlement(
            tenant_id=tenant_id, project_id=project.id, version_no=1, is_current=True, status="approved", currency="AED",
            default_markup_pct=Decimal("8"), margin_on_sell_pct=Decimal(str(pt.margin_on_sell_pct)), tender_total=Decimal(str(pt.our_price)),
            submitted_at=datetime.now(timezone.utc) - timedelta(days=200), outcome=pt.outcome,
            outcome_our_price=Decimal(str(pt.our_price)), outcome_winning_price=Decimal(str(pt.winning_price)),
            outcome_recorded_at=datetime.now(timezone.utc) - timedelta(days=150),
        )
        session.add(settlement)
        await session.flush()
        for n, (desc, uom, qty, cost) in enumerate(pt.lines, start=1):
            boq = await boq_service.create_line_item(
                session, ctx, project.id, BoqLineItemCreate(item_no=f"{n}", description=desc, uom=uom, boq_quantity=qty)
            )
            session.add(
                BidSettlementLineItem(
                    tenant_id=tenant_id, settlement_id=settlement.id, boq_line_item_id=boq.id, project_id=project.id, quantity=Decimal(str(qty)),
                    quantity_at_build=Decimal(str(qty)), direct_unit_cost=Decimal(str(cost)), source_currency="AED", cost_source="manual",
                )
            )
        await session.flush()
        counts["past_tenders"] += 1
    return counts


async def seed_quotes(session: AsyncSession, ctx: RequestContext, project_code: str = demo.DEMO_PROJECT_CODE) -> int:
    """Accepted vendor quotes for the demo project's BOQ lines (call after the BOQ has been imported)."""
    tenant_id = ctx.tenant_id
    project = (await session.execute(select(Project).where(Project.tenant_id == tenant_id, Project.code == project_code))).scalar_one_or_none()
    if project is None:
        raise RuntimeError(f"Project {project_code!r} not found: create it and import the BOQ first.")
    items = {i.item_no: i for i in (await session.execute(select(BoqLineItem).where(BoqLineItem.project_id == project.id))).scalars().all()}
    vendors = {v.legal_name: v for v in (await session.execute(select(Vendor).where(Vendor.tenant_id == tenant_id, Vendor.legal_name.like(f"{demo.VENDOR_PREFIX}%")))).scalars().all()}
    created = 0
    for item_no, quotes in demo.QUOTES.items():
        item = items.get(item_no)
        if item is None:
            continue
        already = (
            await session.execute(select(QuotationLineItem.id).where(QuotationLineItem.boq_line_item_id == item.id, QuotationLineItem.status == "accepted"))
        ).first()
        if already:
            continue
        for vendor_suffix, price, exclusion in quotes:
            vendor = vendors.get(f"{demo.VENDOR_PREFIX}{vendor_suffix}")
            if vendor is None:
                continue
            package_id = (
                await session.execute(
                    text("INSERT INTO procurement_packages (tenant_id, project_id, name, status) VALUES (:t, :p, :n, 'sent') RETURNING id"),
                    {"t": str(tenant_id), "p": str(project.id), "n": f"AIDEMO package {item_no}"},
                )
            ).scalar_one()
            rfq_id = (
                await session.execute(
                    text("INSERT INTO rfqs (tenant_id, package_id, project_id, vendor_id, status, reply_token) VALUES (:t, :pkg, :p, :v, 'sent', :tok) RETURNING id"),
                    {"t": str(tenant_id), "pkg": str(package_id), "p": str(project.id), "v": str(vendor.id), "tok": f"aidemo-{uuid.uuid4().hex}"},
                )
            ).scalar_one()
            quotation = Quotation(
                tenant_id=tenant_id, rfq_id=rfq_id, vendor_id=vendor.id, package_id=package_id, project_id=project.id,
                extraction_method="deterministic_xlsx", version_no=1, is_current=True, currency="AED", vat_inclusive=False,
                submitted_at=datetime.now(timezone.utc) - timedelta(days=20), status="proposed",
            )
            session.add(quotation)
            await session.flush()
            qli = QuotationLineItem(
                tenant_id=tenant_id, quotation_id=quotation.id, project_id=project.id, boq_line_item_id=item.id,
                vendor_description_text=item.description, vendor_uom=item.uom, unit_price=Decimal(str(price)),
                quantity=item.boq_quantity, confidence=Decimal("1.0"), source="deterministic", status="accepted", accepted_at=datetime.now(timezone.utc),
            )
            session.add(qli)
            await session.flush()
            if exclusion:
                session.add(
                    QuotationExclusionFlag(
                        tenant_id=tenant_id, quotation_id=quotation.id, project_id=project.id, line_item_id=qli.id,
                        flag_text=exclusion, source_quote_text=exclusion, confidence=Decimal("0.9"), status="open",
                    )
                )
            created += 1
    await session.flush()
    return created


async def clean(session: AsyncSession, tenant_id: UUID) -> dict[str, int]:
    """Removes everything the AI demo created: projects (cascading to BOQ, drawings, settlements, verification
    runs, AI runs, quotes), vendors and cost items."""
    out = {"projects": 0, "vendors": 0, "cost_items": 0}
    projects = (
        await session.execute(
            select(Project).where(Project.tenant_id == tenant_id, (Project.code == demo.DEMO_PROJECT_CODE) | Project.code.like(f"{demo.HISTORY_PROJECT_PREFIX}%"))
        )
    ).scalars().all()
    for p in projects:
        await session.delete(p)
        out["projects"] += 1
    await session.flush()
    for v in (await session.execute(select(Vendor).where(Vendor.tenant_id == tenant_id, Vendor.legal_name.like(f"{demo.VENDOR_PREFIX}%")))).scalars().all():
        await session.delete(v)
        out["vendors"] += 1
    await session.flush()
    # The cost library is append-only by design (bi-temporal; no DELETE policy for anyone), so demo items are
    # DEACTIVATED, not deleted: they disappear from lists and from the pricing assistant, and a re-seed reactivates them.
    res = await session.execute(
        update(CostItem).where(CostItem.tenant_id == tenant_id, CostItem.code.like(f"{demo.COST_CODE_PREFIX}%"), CostItem.is_active.is_(True)).values(is_active=False)
    )
    out["cost_items"] = res.rowcount or 0
    return out
