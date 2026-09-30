"""Drawing <-> BOQ quantity verification: runs, lines, and a person's mapping decisions.

- verification_runs: one report over a project's BOQ (status, progress, summary, AI usage).
- verification_lines: one row per BOQ line (plus 'missing_in_boq' rows for drawing quantities
  no BOQ line accounts for) with class, quantity, delta, confidence, method, evidence links.
- verification_mappings: a person's accept/reject/include of one piece of drawing evidence for
  one BOQ line. Keyed per project (not per run) so decisions survive re-runs, and non-destructive:
  clearing a mapping deletes only the decision, never the drawing or BOQ data.

Estimators work these rows (accept/override is normal estimating work, like linking a
measurement), so write access is every app role; creating a run (which spends AI budget) is
restricted at the API to lead_estimator and above.

Revision ID: 0034
Revises: 0033
Create Date: 2026-09-30 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from app.db.ddl import enable_rls, tenant_policies

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None

ALL_ROLES = ["estimator", "lead_estimator", "procurement_head", "bd_director", "managing_director"]
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


def _project_fk() -> sa.Column:
    return sa.Column("project_id", pg.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)


def upgrade() -> None:
    op.create_table(
        "verification_runs",
        *_entity_columns(),
        _project_fk(),
        # queued | running | ready | failed
        sa.Column("status", sa.String(12), nullable=False, server_default="queued"),
        sa.Column("use_ai", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("phase", sa.String(16), nullable=True),
        sa.Column("progress_done", sa.Integer, nullable=False, server_default="0"),
        sa.Column("progress_total", sa.Integer, nullable=False, server_default="0"),
        sa.Column("counts", pg.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("summary", pg.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("warnings", pg.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("ai_calls", sa.Integer, nullable=False, server_default="0"),
        sa.Column("ai_cost_usd", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_verification_runs_tenant_id", "verification_runs", ["tenant_id"])
    op.create_index("ix_verification_runs_project_id", "verification_runs", ["project_id"])
    enable_rls(op, "verification_runs")
    tenant_policies(op, "verification_runs", write_roles=ALL_ROLES, delete_roles=DELETE_ROLES, project_scoped=True)

    op.create_table(
        "verification_lines",
        *_entity_columns(),
        _project_fk(),
        sa.Column("run_id", pg.UUID(as_uuid=True), sa.ForeignKey("verification_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("boq_line_item_id", pg.UUID(as_uuid=True), sa.ForeignKey("boq_line_items.id", ondelete="SET NULL"), nullable=True),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("item_no", sa.String(32), nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("trade_name", sa.String(255), nullable=True),
        # match | variance | missing_in_drawings | not_verifiable | missing_in_boq
        sa.Column("vclass", sa.String(24), nullable=False),
        # measured | annotated | none
        sa.Column("method", sa.String(12), nullable=False, server_default="none"),
        # ai | rules | user | none
        sa.Column("mapped_by", sa.String(8), nullable=False, server_default="none"),
        sa.Column("boq_quantity", sa.Numeric(18, 4), nullable=True),
        sa.Column("boq_uom", sa.String(16), nullable=True),
        sa.Column("drawing_quantity", sa.Numeric(18, 4), nullable=True),
        sa.Column("delta", sa.Numeric(18, 4), nullable=True),
        sa.Column("delta_pct", sa.Numeric(9, 3), nullable=True),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False, server_default="0"),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("flags", pg.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("interpretation", pg.JSONB, nullable=True),
        # attached evidence used for the quantity: [{ref, kind, value, unit, label, drawing_id, sheet_id, page, bbox}]
        sa.Column("evidence", pg.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        # ranked proposals: [{ref, score, reason, source, selected}]
        sa.Column("candidates", pg.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.create_index("ix_verification_lines_tenant_id", "verification_lines", ["tenant_id"])
    op.create_index("ix_verification_lines_project_id", "verification_lines", ["project_id"])
    op.create_index("ix_verification_lines_run_class", "verification_lines", ["run_id", "vclass"])
    op.create_index("ix_verification_lines_run_sort", "verification_lines", ["run_id", "sort_order"])
    enable_rls(op, "verification_lines")
    tenant_policies(op, "verification_lines", write_roles=ALL_ROLES, delete_roles=ALL_ROLES, project_scoped=True)

    op.create_table(
        "verification_mappings",
        *_entity_columns(),
        _project_fk(),
        sa.Column("boq_line_item_id", pg.UUID(as_uuid=True), sa.ForeignKey("boq_line_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("evidence_ref", sa.String(64), nullable=False),
        # include | exclude
        sa.Column("decision", sa.String(8), nullable=False),
        sa.Column("note", sa.Text, nullable=True),
        sa.UniqueConstraint("boq_line_item_id", "evidence_ref", name="uq_verification_mappings_line_evidence"),
    )
    op.create_index("ix_verification_mappings_tenant_id", "verification_mappings", ["tenant_id"])
    op.create_index("ix_verification_mappings_project_id", "verification_mappings", ["project_id"])
    enable_rls(op, "verification_mappings")
    tenant_policies(op, "verification_mappings", write_roles=ALL_ROLES, delete_roles=ALL_ROLES, project_scoped=True)


def downgrade() -> None:
    for table in ("verification_mappings", "verification_lines", "verification_runs"):
        op.drop_table(table)
