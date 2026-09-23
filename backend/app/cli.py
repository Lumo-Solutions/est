"""Operational CLI: `python -m app.cli <command>`.

Design simplification vs. the original sketch: seed data is defined inline
in Python below rather than loaded from backend/app/seeds/*.yaml -- for a
handful of small, code-reviewed reference tables (trade roots, UAE
authorities, a default approval policy) a YAML-loading layer would be pure
indirection. If seed data volume grows, extracting to YAML is a mechanical
follow-up.
"""

from __future__ import annotations

import argparse
import asyncio
from uuid import UUID

from sqlalchemy import select

from app.core.config import get_settings
from app.core.context import system_context
from app.db.session import session_scope
from app.models.approvals import ApprovalPolicy, ApprovalPolicyTier
from app.models.prequal import Authority, CertificateType
from app.models.taxonomy import TradeNode
from app.models.tenancy import Tenant

_TRADE_ROOTS = [
    ("EARTH", "Earthworks"),
    ("ASPHALT", "Asphalt & Paving"),
    ("CONCRETE", "Concrete"),
    ("MEP", "Mechanical, Electrical & Plumbing"),
    ("UTIL", "Utilities"),
]

_AUTHORITIES = [
    ("DM", "Dubai Municipality", "Dubai"),
    ("RTA", "Roads and Transport Authority", "Dubai"),
    ("DEWA", "Dubai Electricity and Water Authority", "Dubai"),
    ("CIVIL_DEFENCE", "Civil Defence", "UAE"),
]

_CERT_TYPES = {
    "DM": [("TRADE_LICENSE", "Trade License", 12, True), ("DM_PREQUAL", "DM Contractor Prequalification", 24, True)],
    "RTA": [("RTA_PREQUAL", "RTA Contractor Registration", 24, True)],
    "DEWA": [("DEWA_APPROVAL", "DEWA Contractor Approval", 24, False)],
    "CIVIL_DEFENCE": [("CD_NOC", "Civil Defence NOC", 12, True)],
}

_DEFAULT_APPROVAL_TIERS = [
    (1, 0, 50_000, "lead_estimator"),
    (2, 50_000, 250_000, "procurement_head"),
    (3, 250_000, 1_000_000, "bd_director"),
    (4, 1_000_000, None, "managing_director"),
]


async def seed(tenant_slug: str) -> None:
    settings = get_settings()
    tenant_id = UUID(settings.demo_tenant_id)
    ctx = system_context(tenant_id)

    async with session_scope(ctx) as session:
        existing = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
        if existing.scalar_one_or_none() is None:
            session.add(Tenant(id=tenant_id, slug=tenant_slug, name=tenant_slug.title()))
            await session.flush()

        root_ids: dict[str, UUID] = {}
        for code, name in _TRADE_ROOTS:
            existing_node = await session.execute(
                select(TradeNode).where(TradeNode.tenant_id == tenant_id, TradeNode.code == code, TradeNode.parent_id.is_(None))
            )
            node = existing_node.scalar_one_or_none()
            if node is None:
                node = TradeNode(tenant_id=tenant_id, parent_id=None, code=code, name=name, path="placeholder")
                session.add(node)
                await session.flush()
            root_ids[code] = node.id

        authority_ids: dict[str, UUID] = {}
        for code, name, jurisdiction in _AUTHORITIES:
            existing_auth = await session.execute(
                select(Authority).where(Authority.tenant_id == tenant_id, Authority.code == code)
            )
            authority = existing_auth.scalar_one_or_none()
            if authority is None:
                authority = Authority(tenant_id=tenant_id, code=code, name=name, jurisdiction=jurisdiction)
                session.add(authority)
                await session.flush()
            authority_ids[code] = authority.id

        for authority_code, cert_defs in _CERT_TYPES.items():
            for code, name, validity_months, is_mandatory in cert_defs:
                existing_ct = await session.execute(
                    select(CertificateType).where(CertificateType.tenant_id == tenant_id, CertificateType.code == code)
                )
                if existing_ct.scalar_one_or_none() is None:
                    session.add(
                        CertificateType(
                            tenant_id=tenant_id, authority_id=authority_ids[authority_code], code=code, name=name,
                            validity_months=validity_months, is_mandatory=is_mandatory,
                        )
                    )

        existing_policy = await session.execute(
            select(ApprovalPolicy).where(
                ApprovalPolicy.tenant_id == tenant_id, ApprovalPolicy.entity_type == "cost_rate_change"
            )
        )
        if existing_policy.scalar_one_or_none() is None:
            policy = ApprovalPolicy(
                tenant_id=tenant_id, entity_type="cost_rate_change", name="Default cost-rate approval policy",
                version=1, mode="sequential_up_to_tier", is_active=True,
            )
            session.add(policy)
            await session.flush()
            for seq, min_amount, max_amount, role in _DEFAULT_APPROVAL_TIERS:
                session.add(
                    ApprovalPolicyTier(
                        tenant_id=tenant_id, policy_id=policy.id, seq=seq, min_amount=min_amount,
                        max_amount=max_amount, required_role=role,
                    )
                )

        await session.flush()
    print(f"Seeded demo data for tenant '{tenant_slug}' ({tenant_id}).")


def main() -> None:
    parser = argparse.ArgumentParser(prog="app.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)
    seed_parser = subparsers.add_parser("seed", help="Seed reference data for a tenant")
    seed_parser.add_argument("--tenant", default="demo")

    args = parser.parse_args()
    if args.command == "seed":
        asyncio.run(seed(args.tenant))


if __name__ == "__main__":
    main()
