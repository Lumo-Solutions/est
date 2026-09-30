"""The AI demo dataset against Postgres: it seeds the cost library (with rate history and a stale rate), vendors
(mixed prequalification), and 15 past tenders with outcomes; is idempotent; seeds accepted quotes onto an imported
BOQ; feeds the pricing assistant real candidates; and `clean` removes every tagged row and nothing else."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, text

from app.demo import ai_demo as demo
from app.demo import ai_demo_seed as seed
from app.models.boq import BoqLineItem
from app.models.costlib import CostItem, CostItemRate
from app.models.prequal import Authority, CertificateType, VendorCertificate, VendorPrequalification
from app.models.quotation_ingestion import Quotation, QuotationExclusionFlag, QuotationLineItem
from app.models.settlement import BidSettlement
from app.models.taxonomy import TradeNode
from app.models.tenancy import Project
from app.models.vendors import Vendor, VendorServiceRegion, VendorTrade
from app.schemas.boq import BoqLineItemCreate
from app.services import boq as boq_service
from app.services import settlement as settlement_service
from tests.integration.test_bid_settlement import _system_ctx

pytestmark = pytest.mark.asyncio


async def _tenant(session) -> tuple[uuid.UUID, object]:
    tenant_id = uuid.uuid4()
    await session.execute(text("INSERT INTO tenants (id, slug, name) VALUES (:i, :s, 'T')"), {"i": str(tenant_id), "s": f"ai-{uuid.uuid4().hex[:8]}"})
    ctx = await _system_ctx(session, tenant_id)
    for code, name in [("EARTH", "Earthworks"), ("ASPHALT", "Asphalt & Paving"), ("CONCRETE", "Concrete"), ("MEP", "MEP"), ("UTIL", "Utilities")]:
        session.add(TradeNode(tenant_id=tenant_id, parent_id=None, code=code, name=name, path="placeholder"))
    auth = Authority(tenant_id=tenant_id, code="DM", name="Dubai Municipality", jurisdiction="Dubai")
    session.add(auth)
    await session.flush()
    session.add(CertificateType(tenant_id=tenant_id, authority_id=auth.id, code="TRADE_LICENSE", name="Trade licence", validity_months=12, is_mandatory=True))
    await session.flush()
    return tenant_id, ctx


async def _count(session, model, *where) -> int:
    return (await session.execute(select(func.count()).select_from(model).where(*where))).scalar_one()


async def test_seed_library_vendors_history_and_idempotency(rls_session):
    tenant_id, ctx = await _tenant(rls_session)
    counts = await seed.seed_library_vendors_history(rls_session, ctx)
    assert counts["cost_items"] == len(demo.COST_LIBRARY) and counts["vendors"] == 20 and counts["past_tenders"] == 15
    assert await _count(rls_session, CostItem, CostItem.tenant_id == tenant_id) == len(demo.COST_LIBRARY)
    # rate history: an ordinary item has a closed older rate and a current one; a stale item only an old open rate
    pipe = (await rls_session.execute(select(CostItem).where(CostItem.code == f"{demo.COST_CODE_PREFIX}PP-UPVC-300"))).scalar_one()
    assert await _count(rls_session, CostItemRate, CostItemRate.cost_item_id == pipe.id) == 2
    stale = (await rls_session.execute(select(CostItem).where(CostItem.code == f"{demo.COST_CODE_PREFIX}MH-1200-up"))).scalar_one()
    assert await _count(rls_session, CostItemRate, CostItemRate.cost_item_id == stale.id) == 1
    # vendors: trades, regions, mixed prequalification, verified certificates (one lapsed, some expiring)
    assert await _count(rls_session, VendorTrade, VendorTrade.tenant_id == tenant_id) == sum(len(v.trades) for v in demo.VENDORS)
    assert await _count(rls_session, VendorServiceRegion, VendorServiceRegion.tenant_id == tenant_id) == sum(len(v.regions) for v in demo.VENDORS)
    statuses = {s for (s,) in (await rls_session.execute(select(VendorPrequalification.status).where(VendorPrequalification.tenant_id == tenant_id))).all()}
    assert {"approved", "suspended", "pending"} <= statuses
    soon = await _count(rls_session, VendorCertificate, VendorCertificate.tenant_id == tenant_id,
                        VendorCertificate.expiry_date >= date.today(), VendorCertificate.expiry_date <= date.today() + timedelta(days=30))
    assert soon == sum(1 for v in demo.VENDORS if 0 <= v.cert_days <= 30)
    lapsed = await _count(rls_session, VendorCertificate, VendorCertificate.tenant_id == tenant_id, VendorCertificate.expiry_date < date.today())
    assert lapsed == 1
    # history: 15 projects, each with an approved settlement carrying a recorded outcome
    hist = (await rls_session.execute(select(BidSettlement).where(BidSettlement.tenant_id == tenant_id, BidSettlement.outcome.in_(("won", "lost"))))).scalars().all()
    assert len(hist) == 15 and {h.outcome for h in hist} == {"won", "lost"} and all(h.margin_on_sell_pct is not None for h in hist)
    # idempotent
    again = await seed.seed_library_vendors_history(rls_session, ctx)
    assert again == {"cost_items": 0, "vendors": 0, "past_tenders": 0}


async def test_quotes_feed_the_pricing_assistant_and_clean_removes_only_tagged_rows(rls_session):
    tenant_id, ctx = await _tenant(rls_session)
    await seed.seed_library_vendors_history(rls_session, ctx)
    # an unrelated project, vendor and cost item that clean must never touch
    other = Project(tenant_id=tenant_id, code="REAL-1", name="Real project")
    rls_session.add(other)
    await rls_session.flush()
    keep_vendor = Vendor(tenant_id=tenant_id, legal_name="Real Vendor LLC", normalized_name="real vendor llc", status="active")
    rls_session.add(keep_vendor)
    rls_session.add(CostItem(tenant_id=tenant_id, code="REAL-ITEM", description="Real", uom="m"))
    # the demo project with the BOQ that the tender pack's Excel BOQ would import
    project = Project(tenant_id=tenant_id, code=demo.DEMO_PROJECT_CODE, name="Al Reem Package 3", submission_due_at=datetime(2026, 6, 1, tzinfo=timezone.utc))
    rls_session.add(project)
    await rls_session.flush()
    parents: dict[str, uuid.UUID] = {}
    for b in demo.BOQ:
        item = await boq_service.create_line_item(
            rls_session, ctx, project.id,
            BoqLineItemCreate(item_no=b.item_no, description=b.description, uom=b.uom, boq_quantity=b.qty, parent_id=parents.get(b.item_no.rsplit(".", 1)[0]) if "." in b.item_no else None),
        )
        if b.qty is None:
            parents[b.item_no] = item.id
    created = await seed.seed_quotes(rls_session, ctx)
    expected = sum(len(v) for v in demo.QUOTES.values())
    assert created == expected
    assert await seed.seed_quotes(rls_session, ctx) == 0   # idempotent
    accepted = await _count(rls_session, QuotationLineItem, QuotationLineItem.project_id == project.id, QuotationLineItem.status == "accepted")
    assert accepted == expected
    assert await _count(rls_session, QuotationExclusionFlag, QuotationExclusionFlag.project_id == project.id) == 1

    # the pricing assistant sees real candidates on this data (quote + library + history), with flags from the seed
    from app.ai.gateway import AIGateway
    from app.ai.store import MemoryStore
    from app.core.config import Settings
    from app.models.pricing_ai import SettlementAiProposal
    from app.services import pricing_ai as pricing

    S = Settings(APP_DATABASE_URL="postgresql://x/y", MIGRATOR_DATABASE_URL="postgresql://x/y", S3_ENDPOINT="http://s3",
                 VLLM_API_BASE="http://vllm.internal/v1", AI_PROVIDER="mock", AI_STALE_RATE_MONTHS=12)
    from app.core.context import RequestContext

    lead = RequestContext(tenant_id=tenant_id, user_id=uuid.uuid4(), sub="lead", roles=frozenset({"lead_estimator"}), is_system=True)
    settlement = await settlement_service.build_settlement_draft(rls_session, lead, project.id)
    run = await pricing.create_run(rls_session, lead, settlement.id, kind="costs")

    async def _np(*_a):
        return None

    await pricing.run_cost_proposals(rls_session, lead, run.id, _np, gateway=AIGateway(settings=S, store=MemoryStore(), ctx=lead))
    rows = (await rls_session.execute(select(SettlementAiProposal).where(SettlementAiProposal.settlement_id == settlement.id))).scalars().all()
    by_item = {i.item_no: i for i in (await rls_session.execute(select(BoqLineItem).where(BoqLineItem.project_id == project.id))).scalars().all()}
    prop = {next(k for k, v in by_item.items() if v.id == r.boq_line_item_id): r for r in rows}
    assert prop["2.1"].chosen is not None and {c["type"] for c in prop["2.1"].candidates} >= {"quote", "library"}
    assert "quote_exclusions" in prop["2.2"].flags                     # the vendor quote that excludes testing
    assert "vendor_not_eligible" in prop["4.1"].flags                  # the vendor whose prequalification lapsed
    assert prop["2.3"].chosen is not None and any(c["type"] == "library" and "stale_rate" in c["flags"] for c in prop["2.3"].candidates)
    assert prop["2.4"].chosen is None                                   # nothing in the library for a connection to an existing manhole
    competing = prop["1.1"]
    assert sorted(float(c["rate"]) for c in competing.candidates if c["type"] == "quote") == [17.5, 19.0]

    removed = await seed.clean(rls_session, tenant_id)
    assert removed["projects"] == 16 and removed["vendors"] == 20 and removed["cost_items"] == len(demo.COST_LIBRARY)   # deactivated
    assert await _count(rls_session, Project, Project.tenant_id == tenant_id) == 1
    assert (await rls_session.execute(select(Project.code).where(Project.tenant_id == tenant_id))).scalar_one() == "REAL-1"
    assert await _count(rls_session, Vendor, Vendor.tenant_id == tenant_id) == 1
    # the library is append-only (no DELETE policy): demo items are deactivated, the real one stays active
    assert await _count(rls_session, CostItem, CostItem.tenant_id == tenant_id, CostItem.is_active.is_(True)) == 1
    assert await _count(rls_session, CostItem, CostItem.tenant_id == tenant_id) == 1 + len(demo.COST_LIBRARY)
    # a second clean is a no-op and re-seeding brings the items back without creating duplicates
    assert (await seed.clean(rls_session, tenant_id)) == {"projects": 0, "vendors": 0, "cost_items": 0}
    again = await seed.seed_library_vendors_history(rls_session, ctx)
    assert again["cost_items"] == 0 and again["vendors"] == 20
    assert await _count(rls_session, CostItem, CostItem.tenant_id == tenant_id, CostItem.is_active.is_(True)) == 1 + len(demo.COST_LIBRARY)
