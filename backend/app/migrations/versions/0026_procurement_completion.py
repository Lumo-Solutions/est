"""Module C Phase 6: project location, vendor service regions, subtotal
verification, vendor-quote unit conversion, bid-leveling-stage FX rate,
exclusion citation location. See docs/module-c-phase6-plan.md.

Adds:
- projects.emirate/area/latitude/longitude (nullable -- no backfill for
  existing projects).
- vendor_service_regions (tenant-scoped, RLS-forced) -- which emirates a
  vendor is willing to serve; a vendor with zero rows is "region unknown",
  never filtered as if available everywhere nor as ineligible on its own.
- quotations.stated_total/total_mismatch (subtotal-level arithmetic
  verification -- LLM path only; the deterministic pricing-sheet template
  has no independent grand-total cell of its own to check against, so
  these stay NULL/false for every deterministic-path quotation) and
  fx_rate_to_base/fx_rate_date (bid-leveling-stage FX, deliberately
  separate from BidSettlementLineItem.fx_rate's own acceptance-stage rate
  -- migration 0019).
- quotation_line_items.vendor_uom/uom_mismatch -- unit-aware quantity
  comparison against the matched BOQ item, using the existing
  app.boq.units conversion table.
- quotation_exclusion_flags.source_location/citation_verified -- "page or
  cell" citation plus a deterministic substring-verification flag (a
  citation that doesn't verify is kept, not dropped -- it might still be
  real, just needs a reviewer's own look).

Revision ID: 0026
Revises: 0025
Create Date: 2026-01-08 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from app.db.ddl import enable_rls, tenant_policies

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None

# Same tier as every other Vendor-owned config table (migration 0005's own
# WRITE_ROLES for `vendors`) -- editing which regions a vendor serves is
# vendor-admin work, not a narrower or wider tier.
VENDOR_REGION_WRITE_ROLES = ["lead_estimator", "procurement_head", "bd_director", "managing_director"]


def _entity_columns() -> list[sa.Column]:
    return [
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", pg.UUID(as_uuid=True), nullable=True),
    ]


def upgrade() -> None:
    op.add_column("projects", sa.Column("emirate", sa.String(32), nullable=True))
    op.add_column("projects", sa.Column("area", sa.String(128), nullable=True))
    op.add_column("projects", sa.Column("latitude", sa.Numeric(9, 6), nullable=True))
    op.add_column("projects", sa.Column("longitude", sa.Numeric(9, 6), nullable=True))

    op.create_table(
        "vendor_service_regions",
        *_entity_columns(),
        sa.Column("vendor_id", pg.UUID(as_uuid=True), sa.ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("emirate", sa.String(32), nullable=False),
        sa.UniqueConstraint("vendor_id", "emirate", name="uq_vendor_service_regions_vendor_emirate"),
    )
    op.create_index("ix_vendor_service_regions_tenant_id", "vendor_service_regions", ["tenant_id"])
    op.create_index("ix_vendor_service_regions_vendor_id", "vendor_service_regions", ["vendor_id"])
    enable_rls(op, "vendor_service_regions")
    tenant_policies(op, "vendor_service_regions", write_roles=VENDOR_REGION_WRITE_ROLES, delete_roles=VENDOR_REGION_WRITE_ROLES)

    op.add_column("quotations", sa.Column("stated_total", sa.Numeric(16, 2), nullable=True))
    op.add_column("quotations", sa.Column("total_mismatch", sa.Boolean, nullable=False, server_default="false"))
    op.add_column("quotations", sa.Column("fx_rate_to_base", sa.Numeric(14, 6), nullable=True))
    op.add_column("quotations", sa.Column("fx_rate_date", sa.Date, nullable=True))

    op.add_column("quotation_line_items", sa.Column("vendor_uom", sa.String(16), nullable=True))
    op.add_column("quotation_line_items", sa.Column("uom_mismatch", sa.Boolean, nullable=False, server_default="false"))

    op.add_column("quotation_exclusion_flags", sa.Column("source_location", sa.String(64), nullable=True))
    op.add_column("quotation_exclusion_flags", sa.Column("citation_verified", sa.Boolean, nullable=False, server_default="false"))


def downgrade() -> None:
    op.drop_column("quotation_exclusion_flags", "citation_verified")
    op.drop_column("quotation_exclusion_flags", "source_location")
    op.drop_column("quotation_line_items", "uom_mismatch")
    op.drop_column("quotation_line_items", "vendor_uom")
    op.drop_column("quotations", "fx_rate_date")
    op.drop_column("quotations", "fx_rate_to_base")
    op.drop_column("quotations", "total_mismatch")
    op.drop_column("quotations", "stated_total")
    op.drop_table("vendor_service_regions")
    op.drop_column("projects", "longitude")
    op.drop_column("projects", "latitude")
    op.drop_column("projects", "area")
    op.drop_column("projects", "emirate")
