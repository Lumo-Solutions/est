"""AI pricing assistant: settlement AI runs and per-line cost proposals.

- settlement_ai_runs: one run that proposes costs for a settlement draft ('costs') or produces
  advisory markup suggestions ('markup', result stored in `result`). Progress, AI usage, warnings.
- settlement_ai_proposals: one proposal per settlement line: the chosen real source (accepted vendor
  quote line / cost-library rate / historical median), the ranked candidates, flags computed in code,
  confidence, rationale, and the person's decision. The AI never supplies a rate; accepting a proposal
  applies it through the existing settlement.set_line_cost, so rates stay authoritative and approval
  routing / segregation of duties are untouched.

Estimators work proposals (like line costing today), so write is every app role; starting a run spends
AI budget and is restricted to lead_estimator and above at the API.

Revision ID: 0035
Revises: 0034
Create Date: 2026-09-30 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from app.db.ddl import enable_rls, tenant_policies

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None

ALL_ROLES = ["estimator", "lead_estimator", "procurement_head", "bd_director", "managing_director"]


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
        "settlement_ai_runs",
        *_entity_columns(),
        _project_fk(),
        sa.Column("settlement_id", pg.UUID(as_uuid=True), sa.ForeignKey("bid_settlements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),  # costs | markup
        sa.Column("status", sa.String(12), nullable=False, server_default="queued"),  # queued|running|ready|failed
        sa.Column("use_ai", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("progress_done", sa.Integer, nullable=False, server_default="0"),
        sa.Column("progress_total", sa.Integer, nullable=False, server_default="0"),
        sa.Column("params", pg.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("counts", pg.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("result", pg.JSONB, nullable=True),
        sa.Column("warnings", pg.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("ai_calls", sa.Integer, nullable=False, server_default="0"),
        sa.Column("ai_cost_usd", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_settlement_ai_runs_tenant_id", "settlement_ai_runs", ["tenant_id"])
    op.create_index("ix_settlement_ai_runs_project_id", "settlement_ai_runs", ["project_id"])
    op.create_index("ix_settlement_ai_runs_settlement_id", "settlement_ai_runs", ["settlement_id"])
    enable_rls(op, "settlement_ai_runs")
    tenant_policies(op, "settlement_ai_runs", write_roles=ALL_ROLES, project_scoped=True)

    op.create_table(
        "settlement_ai_proposals",
        *_entity_columns(),
        _project_fk(),
        sa.Column("run_id", pg.UUID(as_uuid=True), sa.ForeignKey("settlement_ai_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("settlement_id", pg.UUID(as_uuid=True), sa.ForeignKey("bid_settlements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("settlement_line_id", pg.UUID(as_uuid=True), sa.ForeignKey("bid_settlement_line_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("boq_line_item_id", pg.UUID(as_uuid=True), sa.ForeignKey("boq_line_items.id", ondelete="CASCADE"), nullable=False),
        # proposed | accepted | overridden | rejected | superseded
        sa.Column("status", sa.String(12), nullable=False, server_default="proposed"),
        # ai | rules | none
        sa.Column("source", sa.String(6), nullable=False, server_default="none"),
        sa.Column("chosen", pg.JSONB, nullable=True),
        sa.Column("candidates", pg.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("rationale", sa.Text, nullable=True),
        sa.Column("flags", pg.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False, server_default="0"),
        sa.Column("decided_by", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("decided_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("decision_note", sa.Text, nullable=True),
        sa.Column("applied", pg.JSONB, nullable=True),
    )
    op.create_index("ix_settlement_ai_proposals_tenant_id", "settlement_ai_proposals", ["tenant_id"])
    op.create_index("ix_settlement_ai_proposals_project_id", "settlement_ai_proposals", ["project_id"])
    op.create_index("ix_settlement_ai_proposals_run_id", "settlement_ai_proposals", ["run_id"])
    op.create_index("ix_settlement_ai_proposals_line", "settlement_ai_proposals", ["settlement_line_id", "status"])
    enable_rls(op, "settlement_ai_proposals")
    tenant_policies(op, "settlement_ai_proposals", write_roles=ALL_ROLES, project_scoped=True)


def downgrade() -> None:
    op.drop_table("settlement_ai_proposals")
    op.drop_table("settlement_ai_runs")
