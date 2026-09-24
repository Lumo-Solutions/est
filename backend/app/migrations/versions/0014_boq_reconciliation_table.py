"""Phase 3 fix (real bug): move reconciliation state off boq_line_items
onto its own table with an operational (estimator+) write policy.

boq_line_items' own WRITE_ROLES is lead_estimator+ (structural edits --
migration 0011). app/services/boq.py::_apply_reconciliation(), triggered
by linking a measurement (an *operational* action explicitly gated at
estimator+, per _RECONCILE_ROLES), was writing variance/variance_pct/
discrepancy_class/reconciliation_note/reconciled_at directly onto
boq_line_items -- so its UPDATE matched zero rows under RLS for any actor
without a structural role: a plain estimator linking a measurement raised
SQLAlchemy's StaleDataError (it expected to update exactly 1 row; RLS's
USING clause filtered it to 0). Caught by
tests/integration/test_boq_rls.py::test_estimator_can_link_and_reconcile_
but_not_create_structure once `make test-integration` could actually run.

Moving reconciliation state to its own table with its own, looser write
policy fixes this without touching boq_line_items' own structural-edit
policy at all -- deliberately not "compute reconciliation on read instead
of persisting it", which would give up the very reason it was persisted in
the first place (cheap filter/sort on discrepancy_class for the SRS's own
"4,200+ line" AG Grid) in exchange for solving a problem this table split
already solves.

Revision ID: 0014
Revises: 0013
Create Date: 2026-01-01 00:00:13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from app.db.ddl import enable_rls, tenant_policies

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

# Same operational role set as boq_line_item_measurements (migration 0013)
# and app/api/v1/routes/boq.py::_RECONCILE_ROLES -- linking/reconciling is
# normal, frequent estimating work, unlike structural edits to
# boq_line_items itself, which keeps its own lead_estimator+ policy
# untouched by this migration.
WRITE_ROLES = ["estimator", "lead_estimator", "procurement_head", "bd_director", "managing_director"]
# This row is only ever removed via CASCADE when the parent boq_line_item
# is deleted (a structural action) -- delete_roles matches boq_line_items'
# own DELETE_ROLES, so that cascade is guaranteed to succeed under RLS
# FORCE ROW LEVEL SECURITY for whoever is already allowed to delete the
# parent (a different, non-matching delete_roles here would make deleting
# a reconciled BOQ item fail with a foreign-key-via-RLS error).
DELETE_ROLES = ["lead_estimator", "procurement_head", "managing_director"]


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
    op.create_table(
        "boq_line_item_reconciliation",
        *_entity_columns(),
        sa.Column(
            "boq_line_item_id", pg.UUID(as_uuid=True), sa.ForeignKey("boq_line_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Denormalized from boq_line_items.project_id, same reasoning as
        # boq_line_item_measurements (migration 0013): the project_scoped
        # RLS policy below reads this column directly.
        sa.Column("project_id", pg.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("variance", sa.Numeric(18, 4), nullable=True),
        sa.Column("variance_pct", sa.Numeric(8, 3), nullable=True),
        sa.Column("discrepancy_class", sa.String(16), nullable=True),
        sa.Column("reconciliation_note", sa.Text, nullable=True),
        sa.Column("reconciled_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.UniqueConstraint("boq_line_item_id", name="uq_boq_line_item_reconciliation_item"),
    )
    op.create_index("ix_boq_line_item_reconciliation_tenant_id", "boq_line_item_reconciliation", ["tenant_id"])
    op.create_index("ix_boq_line_item_reconciliation_project_id", "boq_line_item_reconciliation", ["project_id"])

    enable_rls(op, "boq_line_item_reconciliation")
    tenant_policies(
        op, "boq_line_item_reconciliation", write_roles=WRITE_ROLES, delete_roles=DELETE_ROLES, project_scoped=True
    )

    # Migrate any reconciliation state already written under 0011-0013's
    # boq_line_items columns before dropping them.
    op.execute(
        "INSERT INTO boq_line_item_reconciliation "
        "(tenant_id, boq_line_item_id, project_id, variance, variance_pct, discrepancy_class, "
        "reconciliation_note, reconciled_at) "
        "SELECT tenant_id, id, project_id, variance, variance_pct, discrepancy_class, "
        "reconciliation_note, reconciled_at "
        "FROM boq_line_items WHERE reconciled_at IS NOT NULL;"
    )

    op.drop_column("boq_line_items", "variance")
    op.drop_column("boq_line_items", "variance_pct")
    op.drop_column("boq_line_items", "discrepancy_class")
    op.drop_column("boq_line_items", "reconciliation_note")
    op.drop_column("boq_line_items", "reconciled_at")


def downgrade() -> None:
    op.add_column("boq_line_items", sa.Column("variance", sa.Numeric(18, 4), nullable=True))
    op.add_column("boq_line_items", sa.Column("variance_pct", sa.Numeric(8, 3), nullable=True))
    op.add_column("boq_line_items", sa.Column("discrepancy_class", sa.String(16), nullable=True))
    op.add_column("boq_line_items", sa.Column("reconciliation_note", sa.Text, nullable=True))
    op.add_column("boq_line_items", sa.Column("reconciled_at", sa.TIMESTAMP(timezone=True), nullable=True))
    op.execute(
        "UPDATE boq_line_items SET "
        "variance = r.variance, variance_pct = r.variance_pct, discrepancy_class = r.discrepancy_class, "
        "reconciliation_note = r.reconciliation_note, reconciled_at = r.reconciled_at "
        "FROM boq_line_item_reconciliation r WHERE r.boq_line_item_id = boq_line_items.id;"
    )
    op.drop_table("boq_line_item_reconciliation")
