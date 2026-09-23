"""multi-tier approval workflows

Revision ID: 0008
Revises: 0007
Create Date: 2026-01-01 00:00:07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from app.db.ddl import enable_rls, tenant_policies

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


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
        "approval_policies",
        *_entity_columns(),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("mode", sa.String(32), nullable=False, server_default="sequential_up_to_tier"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.UniqueConstraint("tenant_id", "entity_type", "version", name="uq_approval_policies_tenant_type_version"),
    )
    op.create_index("ix_approval_policies_tenant_id", "approval_policies", ["tenant_id"])

    op.create_table(
        "approval_policy_tiers",
        *_entity_columns(),
        sa.Column("policy_id", pg.UUID(as_uuid=True), sa.ForeignKey("approval_policies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("seq", sa.SmallInteger, nullable=False),
        sa.Column("min_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("max_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("required_role", sa.String(32), nullable=False),
        sa.Column("quorum", sa.SmallInteger, nullable=False, server_default="1"),
        sa.Column("sla_hours", sa.Integer, nullable=True),
        sa.Column("requires_mfa", sa.Boolean, nullable=False, server_default="true"),
    )
    op.create_index("ix_approval_policy_tiers_tenant_id", "approval_policy_tiers", ["tenant_id"])
    op.create_index("ix_approval_policy_tiers_policy_id", "approval_policy_tiers", ["policy_id"])

    op.create_table(
        "approval_requests",
        *_entity_columns(),
        sa.Column("project_id", pg.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="SET NULL"), nullable=True),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("entity_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="AED"),
        sa.Column("policy_id", pg.UUID(as_uuid=True), sa.ForeignKey("approval_policies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("policy_version", sa.Integer, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("current_seq", sa.SmallInteger, nullable=False, server_default="1"),
        sa.Column("payload_snapshot", pg.JSONB, nullable=True),
        sa.Column("requested_by", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("requested_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_approval_requests_tenant_id", "approval_requests", ["tenant_id"])
    op.execute(
        "CREATE UNIQUE INDEX uq_approval_requests_one_pending ON approval_requests "
        "(tenant_id, entity_type, entity_id) WHERE status = 'pending';"
    )

    op.create_table(
        "approval_steps",
        *_entity_columns(),
        sa.Column("request_id", pg.UUID(as_uuid=True), sa.ForeignKey("approval_requests.id", ondelete="CASCADE"), nullable=False),
        # Denormalized from approval_requests.project_id so the
        # project-scoped RLS policy (app_can_see_project(project_id)) can
        # read it directly without a subquery/join in the policy predicate.
        sa.Column("project_id", pg.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="SET NULL"), nullable=True),
        sa.Column("seq", sa.SmallInteger, nullable=False),
        sa.Column("required_role", sa.String(32), nullable=False),
        sa.Column("assignee_user_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("decision_note", sa.Text, nullable=True),
        sa.Column("decided_by", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("decided_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("decided_ip", pg.INET, nullable=True),
        sa.Column("decided_acr", sa.String(16), nullable=True),
        sa.UniqueConstraint("request_id", "seq", name="uq_approval_steps_request_seq"),
    )
    op.create_index("ix_approval_steps_tenant_id", "approval_steps", ["tenant_id"])
    op.create_index("ix_approval_steps_request_id", "approval_steps", ["request_id"])

    for table in ("approval_policies", "approval_policy_tiers", "approval_requests", "approval_steps"):
        enable_rls(op, table)

    tenant_policies(op, "approval_policies", write_roles=["managing_director"], delete_roles=["managing_director"])
    tenant_policies(op, "approval_policy_tiers", write_roles=["managing_director"], delete_roles=["managing_director"])
    # Any authenticated role may create a request (app enforces requested_by
    # == caller); decisions are gated in the service layer against
    # approval_steps.required_role, not by an RLS write policy here.
    tenant_policies(
        op, "approval_requests",
        write_roles=["estimator", "lead_estimator", "procurement_head", "bd_director", "managing_director"],
        delete_roles=None, project_scoped=True,
    )
    tenant_policies(
        op, "approval_steps",
        write_roles=["estimator", "lead_estimator", "procurement_head", "bd_director", "managing_director"],
        delete_roles=None, project_scoped=True,
    )


def downgrade() -> None:
    op.drop_table("approval_steps")
    op.drop_table("approval_requests")
    op.drop_table("approval_policy_tiers")
    op.drop_table("approval_policies")
