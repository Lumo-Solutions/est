"""Module E Phase 1: schema readiness -- contracts, BOQ/contract revisions
with lineage, live exclusion register, outturn cost observations. Schema
and RLS only, no workflows -- see docs/module-e-schema-design.md.

Every new table denormalizes project_id directly (even
contract_revisions/contract_variations, reachable via contract_id) --
same precedent as bid_settlement_line_items/boq_line_item_measurements:
an RLS policy's project_scoped clause is a plain column check
(app_can_see_project(project_id)), not a join, so the column must be on
the row itself.

Confirmed no refactor to D1/D2: no column is added to bid_settlements,
bid_settlement_line_items, boq_line_items, boq_import_batches, or
quotation_exclusion_flags -- every new FK here points AT those tables'
existing primary keys.

Revision ID: 0027
Revises: 0026
Create Date: 2026-01-09 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from app.db.ddl import enable_rls, tenant_policies

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None

# Module E rows are written by the same estimating/commercial team that
# already touches settlements and BOQs (Module D1) -- no new role tier.
# This phase adds no write endpoints, so these policies exist for
# correctness/future-readiness, not because anything calls them yet.
WRITE_ROLES = ["lead_estimator", "procurement_head", "bd_director", "managing_director"]


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
    # ------------------------------------------------------------------
    # contracts (won settlement -> contract; thin anchor, no duplicated data)
    # ------------------------------------------------------------------
    op.create_table(
        "contracts",
        *_entity_columns(),
        sa.Column("project_id", pg.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("settlement_id", pg.UUID(as_uuid=True), sa.ForeignKey("bid_settlements.id", ondelete="RESTRICT"), nullable=False),
        # Deferred (not a DB-trigger-assigned sequence like rfqs.rfq_ref):
        # no workflow yet decides the numbering convention this phase is
        # scoped to avoid inventing -- see docs/build-log.md's Phase 7
        # section for why this is a deliberate deviation from the plan
        # doc's own "trigger-assigned" phrasing.
        sa.Column("contract_ref", sa.String(32), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("awarded_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.UniqueConstraint("settlement_id", name="uq_contracts_settlement_id"),
    )
    op.create_index("ix_contracts_tenant_id", "contracts", ["tenant_id"])
    op.create_index("ix_contracts_project_id", "contracts", ["project_id"])
    op.execute("CREATE UNIQUE INDEX uq_contracts_tenant_contract_ref ON contracts (tenant_id, contract_ref) WHERE contract_ref IS NOT NULL;")
    enable_rls(op, "contracts")
    tenant_policies(op, "contracts", write_roles=WRITE_ROLES, project_scoped=True)

    # ------------------------------------------------------------------
    # boq_revisions
    # ------------------------------------------------------------------
    op.create_table(
        "boq_revisions",
        *_entity_columns(),
        sa.Column("project_id", pg.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("revision_no", sa.Integer, nullable=False),
        sa.Column("parent_revision_id", pg.UUID(as_uuid=True), sa.ForeignKey("boq_revisions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("import_batch_id", pg.UUID(as_uuid=True), sa.ForeignKey("boq_import_batches.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reason", sa.Text, nullable=True),
        sa.UniqueConstraint("project_id", "revision_no", name="uq_boq_revisions_project_revision_no"),
    )
    op.create_index("ix_boq_revisions_tenant_id", "boq_revisions", ["tenant_id"])
    op.create_index("ix_boq_revisions_project_id", "boq_revisions", ["project_id"])
    enable_rls(op, "boq_revisions")
    tenant_policies(op, "boq_revisions", write_roles=WRITE_ROLES, project_scoped=True)

    # ------------------------------------------------------------------
    # contract_revisions
    # ------------------------------------------------------------------
    op.create_table(
        "contract_revisions",
        *_entity_columns(),
        sa.Column("project_id", pg.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("contract_id", pg.UUID(as_uuid=True), sa.ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("revision_no", sa.Integer, nullable=False),
        sa.Column("parent_revision_id", pg.UUID(as_uuid=True), sa.ForeignKey("contract_revisions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reason", sa.Text, nullable=True),
        sa.UniqueConstraint("contract_id", "revision_no", name="uq_contract_revisions_contract_revision_no"),
    )
    op.create_index("ix_contract_revisions_tenant_id", "contract_revisions", ["tenant_id"])
    op.create_index("ix_contract_revisions_project_id", "contract_revisions", ["project_id"])
    op.create_index("ix_contract_revisions_contract_id", "contract_revisions", ["contract_id"])
    enable_rls(op, "contract_revisions")
    tenant_policies(op, "contract_revisions", write_roles=WRITE_ROLES, project_scoped=True)

    # ------------------------------------------------------------------
    # contract_variations
    # ------------------------------------------------------------------
    op.create_table(
        "contract_variations",
        *_entity_columns(),
        sa.Column("project_id", pg.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("contract_id", pg.UUID(as_uuid=True), sa.ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("revision_id", pg.UUID(as_uuid=True), sa.ForeignKey("contract_revisions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("variation_ref", sa.String(32), nullable=True),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("delta_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="proposed"),
    )
    op.create_index("ix_contract_variations_tenant_id", "contract_variations", ["tenant_id"])
    op.create_index("ix_contract_variations_project_id", "contract_variations", ["project_id"])
    op.create_index("ix_contract_variations_contract_id", "contract_variations", ["contract_id"])
    op.execute("CREATE UNIQUE INDEX uq_contract_variations_tenant_ref ON contract_variations (tenant_id, variation_ref) WHERE variation_ref IS NOT NULL;")
    enable_rls(op, "contract_variations")
    tenant_policies(op, "contract_variations", write_roles=WRITE_ROLES, project_scoped=True)

    # ------------------------------------------------------------------
    # exclusion_register
    # ------------------------------------------------------------------
    op.create_table(
        "exclusion_register",
        *_entity_columns(),
        sa.Column("project_id", pg.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("contract_id", pg.UUID(as_uuid=True), sa.ForeignKey("contracts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_exclusion_flag_id", pg.UUID(as_uuid=True), sa.ForeignKey("quotation_exclusion_flags.id", ondelete="SET NULL"), nullable=True),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("resolution_note", sa.Text, nullable=True),
        sa.Column("resolved_by", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("resolved_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_exclusion_register_tenant_id", "exclusion_register", ["tenant_id"])
    op.create_index("ix_exclusion_register_project_id", "exclusion_register", ["project_id"])
    op.create_index("ix_exclusion_register_contract_id", "exclusion_register", ["contract_id"])
    enable_rls(op, "exclusion_register")
    tenant_policies(op, "exclusion_register", write_roles=WRITE_ROLES, project_scoped=True)

    # ------------------------------------------------------------------
    # outturn_cost_observations
    # ------------------------------------------------------------------
    op.create_table(
        "outturn_cost_observations",
        *_entity_columns(),
        sa.Column("project_id", pg.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("contract_id", pg.UUID(as_uuid=True), sa.ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("boq_line_item_id", pg.UUID(as_uuid=True), sa.ForeignKey("boq_line_items.id", ondelete="SET NULL"), nullable=True),
        sa.Column("cost_item_id", pg.UUID(as_uuid=True), sa.ForeignKey("cost_items.id", ondelete="SET NULL"), nullable=True),
        sa.Column("observed_unit_cost", sa.Numeric(14, 4), nullable=False),
        sa.Column("observed_quantity", sa.Numeric(18, 4), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False, server_default="AED"),
        sa.Column("observed_at", sa.Date, nullable=False),
        sa.Column("source_note", sa.Text, nullable=True),
        # Set once a future write-back workflow actually calls
        # costlib_service.record_rate(source=outturn) -- the seam that
        # workflow needs, added now so it requires no schema change later.
        sa.Column("written_back_rate_id", pg.UUID(as_uuid=True), sa.ForeignKey("cost_item_rates.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_outturn_cost_observations_tenant_id", "outturn_cost_observations", ["tenant_id"])
    op.create_index("ix_outturn_cost_observations_project_id", "outturn_cost_observations", ["project_id"])
    op.create_index("ix_outturn_cost_observations_contract_id", "outturn_cost_observations", ["contract_id"])
    enable_rls(op, "outturn_cost_observations")
    tenant_policies(op, "outturn_cost_observations", write_roles=WRITE_ROLES, project_scoped=True)


def downgrade() -> None:
    op.drop_table("outturn_cost_observations")
    op.drop_table("exclusion_register")
    op.drop_table("contract_variations")
    op.drop_table("contract_revisions")
    op.drop_table("boq_revisions")
    op.drop_table("contracts")
