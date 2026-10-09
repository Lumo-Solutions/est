"""BOQ agent: runs, per-section state, steps (the trace), line proposals, chat.

* agent_runs: one background run (kind 'run') or one chat turn (kind 'chat'): scope, limits, plan, cost, status.
  `started_by` + `started_by_roles` are kept so the deterministic applier can act as the person who started the run.
* agent_run_sections: one BOQ section per row (so a run can be paused, resumed or cancelled per section, and a
  worker only ever updates its own row): status, notes, summary, coverage report.
* agent_steps: the trace. One row per step: tool, args, the agent's note, a one-line result summary, the ai_calls row
  that produced it, tokens, cost, and whether the tool result looked like a prompt injection.
* agent_line_proposals: what the agent claims for a BOQ line (a cost candidate reference or an estimate with a method),
  with evidence, quantity check, flags and confidence. The model never supplies a rate for a candidate: the applier
  takes it from the database row.
* agent_conversations / agent_messages: the chat panel.

Every table is RLS-scoped (tenant + project). Lead estimators and above write; the worker acts as the system.

Revision ID: 0041
Revises: 0040
Create Date: 2026-10-10 12:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from app.db.ddl import enable_rls, tenant_policies

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None

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


def _project_fk() -> sa.Column:
    return sa.Column("project_id", pg.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)


def _indexes(table: str, *cols: str) -> None:
    op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])
    op.create_index(f"ix_{table}_project_id", table, ["project_id"])
    for c in cols:
        op.create_index(f"ix_{table}_{c}", table, [c])


def upgrade() -> None:
    op.create_table(
        "agent_conversations",
        *_entity_columns(),
        _project_fk(),
        sa.Column("title", sa.String(255), nullable=True),
    )
    _indexes("agent_conversations")
    enable_rls(op, "agent_conversations")
    tenant_policies(op, "agent_conversations", write_roles=WRITE_ROLES, project_scoped=True)

    op.create_table(
        "agent_runs",
        *_entity_columns(),
        _project_fk(),
        sa.Column("kind", sa.String(8), nullable=False, server_default="run"),  # run | chat
        sa.Column("conversation_id", pg.UUID(as_uuid=True), sa.ForeignKey("agent_conversations.id", ondelete="CASCADE"), nullable=True),
        sa.Column("settlement_id", pg.UUID(as_uuid=True), sa.ForeignKey("bid_settlements.id", ondelete="SET NULL"), nullable=True),
        # awaiting_confirm | queued | planning | running | paused | done | stopped_limit | failed | cancelled | blocked
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("scope", pg.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("limits", pg.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("estimate", pg.JSONB, nullable=True),
        sa.Column("plan", pg.JSONB, nullable=True),
        sa.Column("summary", pg.JSONB, nullable=True),
        sa.Column("provider", sa.String(24), nullable=True),
        sa.Column("steps_total", sa.Integer, nullable=False, server_default="0"),
        sa.Column("page_views", sa.Integer, nullable=False, server_default="0"),
        sa.Column("ai_calls", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("started_by", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("started_by_roles", pg.ARRAY(sa.Text), nullable=False, server_default="{}"),
        sa.Column("confirmed_by", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("confirmed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    _indexes("agent_runs", "status", "conversation_id")
    enable_rls(op, "agent_runs")
    tenant_policies(op, "agent_runs", write_roles=WRITE_ROLES, project_scoped=True)

    op.create_table(
        "agent_run_sections",
        *_entity_columns(),
        _project_fk(),
        sa.Column("run_id", pg.UUID(as_uuid=True), sa.ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("section_item_id", pg.UUID(as_uuid=True), sa.ForeignKey("boq_line_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("seq", sa.Integer, nullable=False, server_default="0"),
        # pending | reading | done | stopped_limit | failed | cancelled | paused
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("line_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("line_ids", pg.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("steps", sa.Integer, nullable=False, server_default="0"),
        sa.Column("plan", pg.JSONB, nullable=True),
        sa.Column("notes", pg.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("coverage", pg.JSONB, nullable=True),
        sa.Column("stop_reason", sa.String(64), nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.UniqueConstraint("run_id", "section_item_id", name="uq_agent_run_sections_run_section"),
    )
    _indexes("agent_run_sections", "run_id")
    enable_rls(op, "agent_run_sections")
    tenant_policies(op, "agent_run_sections", write_roles=WRITE_ROLES, project_scoped=True)

    op.create_table(
        "agent_steps",
        *_entity_columns(),
        _project_fk(),
        sa.Column("run_id", pg.UUID(as_uuid=True), sa.ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("section_id", pg.UUID(as_uuid=True), sa.ForeignKey("agent_run_sections.id", ondelete="CASCADE"), nullable=True),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("tool", sa.String(32), nullable=False),
        sa.Column("args", pg.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("note", sa.String(400), nullable=True),
        sa.Column("ok", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("result_summary", sa.Text, nullable=True),
        # [{document_id, filename, page}] so the trace can open the file at that page
        sa.Column("file_refs", pg.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("ai_call_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("tokens_in", sa.Integer, nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column("injection", sa.Boolean, nullable=False, server_default="false"),
        sa.UniqueConstraint("run_id", "seq", name="uq_agent_steps_run_seq"),
    )
    _indexes("agent_steps", "run_id", "section_id")
    enable_rls(op, "agent_steps")
    tenant_policies(op, "agent_steps", write_roles=WRITE_ROLES, project_scoped=True)

    op.create_table(
        "agent_line_proposals",
        *_entity_columns(),
        _project_fk(),
        sa.Column("run_id", pg.UUID(as_uuid=True), sa.ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("boq_line_item_id", pg.UUID(as_uuid=True), sa.ForeignKey("boq_line_items.id", ondelete="CASCADE"), nullable=False),
        # candidate | estimate
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("candidate_ref", sa.String(64), nullable=True),
        # The values the applier will write, resolved from the database row (candidate) or the validated estimate.
        sa.Column("apply", pg.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("rate", sa.Numeric(14, 4), nullable=True),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column("uom", sa.String(16), nullable=True),
        sa.Column("as_of", sa.Date, nullable=True),
        sa.Column("method", sa.Text, nullable=True),
        sa.Column("evidence", pg.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("qty_check", pg.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("flags", pg.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False, server_default="0"),
        sa.Column("rationale", sa.Text, nullable=True),
        # proposed | applied | superseded | rejected_by_user
        sa.Column("status", sa.String(20), nullable=False, server_default="proposed"),
        sa.Column("applied_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    _indexes("agent_line_proposals", "run_id", "boq_line_item_id")
    enable_rls(op, "agent_line_proposals")
    tenant_policies(op, "agent_line_proposals", write_roles=WRITE_ROLES, project_scoped=True)

    op.create_table(
        "agent_messages",
        *_entity_columns(),
        _project_fk(),
        sa.Column("conversation_id", pg.UUID(as_uuid=True), sa.ForeignKey("agent_conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(10), nullable=False),  # user | assistant | system
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("run_id", pg.UUID(as_uuid=True), sa.ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True),
    )
    _indexes("agent_messages", "conversation_id")
    enable_rls(op, "agent_messages")
    tenant_policies(op, "agent_messages", write_roles=WRITE_ROLES, project_scoped=True)


def downgrade() -> None:
    for table in (
        "agent_messages", "agent_line_proposals", "agent_steps", "agent_run_sections", "agent_runs", "agent_conversations",
    ):
        op.drop_table(table)
