"""Module D2: BOQ import retention, settlement outcome vendor links, reason codes

Adds boq_import_batches (one row per committed BOQ import; retains the
original .xlsx in S3 plus its column mapping, so a later settlement export
can write settled rates back into the exact original file -- D3) and two
nullable columns on boq_line_items (import_batch_id, source_row_number).
Existing imports/line items simply get NULL here -- "backfill is not
possible for existing imports" (the build brief) -- and D3 will refuse an
original-workbook export for anything with a NULL batch, falling back to
the generated export.

Also adds bid_settlements.outcome_competitor_vendor_ids (an optional
structured link alongside the free-text outcome_competitor_names already
added in migration 0019) and settlement_reason_codes (a tenant-configurable
win/loss reason list, seeded via `app.cli seed` -- not a hardcoded enum,
per the brief's standing constraint on configurable values).

Revision ID: 0020
Revises: 0019
Create Date: 2026-01-03 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from app.db.ddl import enable_rls, tenant_policies

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

# Matches boq_line_items' own WRITE_ROLES (migrations 0009/0013/0014) --
# boq_import_batches rows are created in the same commit_import() call.
BOQ_WRITE_ROLES = ["estimator", "lead_estimator", "procurement_head", "bd_director", "managing_director"]
# Matches bid_settlements' own header-level WRITE_ROLES (migration 0019).
REASON_CODE_WRITE_ROLES = ["lead_estimator", "procurement_head", "bd_director", "managing_director"]


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
    # boq_import_batches
    # ------------------------------------------------------------------
    op.create_table(
        "boq_import_batches",
        *_entity_columns(),
        sa.Column("project_id", pg.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_filename", sa.String(255), nullable=False),
        sa.Column("source_object_key", sa.String(512), nullable=True),
        sa.Column("source_sha256", sa.String(64), nullable=True),
        sa.Column("sheet_name", sa.String(255), nullable=True),
        sa.Column("header_row", sa.Integer, nullable=False, server_default="1"),
        # item_no_column/description_column/uom_column/quantity_column/
        # parent_column hold header TEXT (app/boq/import_parser.py matches
        # raw rows by header string, not column letter) -- can be long.
        # rate_column/amount_column are genuinely short spreadsheet column
        # letters ("F"), recorded only for D3.
        sa.Column("item_no_column", sa.String(255), nullable=False),
        sa.Column("description_column", sa.String(255), nullable=False),
        sa.Column("uom_column", sa.String(255), nullable=True),
        sa.Column("quantity_column", sa.String(255), nullable=True),
        sa.Column("parent_column", sa.String(255), nullable=True),
        sa.Column("rate_column", sa.String(8), nullable=True),
        sa.Column("amount_column", sa.String(8), nullable=True),
        sa.Column("imported_by", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("imported_at", sa.TIMESTAMP(timezone=True), nullable=False),
    )
    op.create_index("ix_boq_import_batches_tenant_id", "boq_import_batches", ["tenant_id"])
    op.create_index("ix_boq_import_batches_project_id", "boq_import_batches", ["project_id"])
    enable_rls(op, "boq_import_batches")
    tenant_policies(op, "boq_import_batches", write_roles=BOQ_WRITE_ROLES, project_scoped=True)

    # ------------------------------------------------------------------
    # boq_line_items: import provenance
    # ------------------------------------------------------------------
    op.add_column(
        "boq_line_items",
        sa.Column("import_batch_id", pg.UUID(as_uuid=True), sa.ForeignKey("boq_import_batches.id", ondelete="SET NULL"), nullable=True),
    )
    op.add_column("boq_line_items", sa.Column("source_row_number", sa.Integer, nullable=True))
    op.create_index("ix_boq_line_items_import_batch_id", "boq_line_items", ["import_batch_id"])

    # ------------------------------------------------------------------
    # bid_settlements: structured competitor-vendor link
    # ------------------------------------------------------------------
    op.add_column(
        "bid_settlements",
        sa.Column("outcome_competitor_vendor_ids", pg.ARRAY(pg.UUID(as_uuid=True)), nullable=False, server_default="{}"),
    )

    # ------------------------------------------------------------------
    # settlement_reason_codes
    # ------------------------------------------------------------------
    op.create_table(
        "settlement_reason_codes",
        *_entity_columns(),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.UniqueConstraint("tenant_id", "code", name="uq_settlement_reason_codes_tenant_code"),
    )
    op.create_index("ix_settlement_reason_codes_tenant_id", "settlement_reason_codes", ["tenant_id"])
    enable_rls(op, "settlement_reason_codes")
    tenant_policies(op, "settlement_reason_codes", write_roles=REASON_CODE_WRITE_ROLES)


def downgrade() -> None:
    op.drop_table("settlement_reason_codes")
    op.drop_column("bid_settlements", "outcome_competitor_vendor_ids")
    op.drop_index("ix_boq_line_items_import_batch_id", table_name="boq_line_items")
    op.drop_column("boq_line_items", "source_row_number")
    op.drop_column("boq_line_items", "import_batch_id")
    op.drop_table("boq_import_batches")
