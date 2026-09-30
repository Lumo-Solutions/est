"""External AI provider governance: tenant AI settings, the ai_calls audit
table, the AI response cache, and a per-project "no external AI" override.
See docs/ai-plan.md and docs/ai-provider.md.

TEMPORARY, KNOWING REVERSAL of SRS §1.1 (no external AI APIs), decided by the
owner until a GPU server runs the in-house model. Tenant data leaves the
boundary only when tenant_ai_settings.external_ai_allowed is true (default
false, managing_director only) and the project has not opted out.

ai_calls holds the full prompt and response (internal traceability): reads
are limited to lead_estimator and above. Every app role may INSERT (the
gateway writes on behalf of whoever triggered the call).

Revision ID: 0032
Revises: 0031
Create Date: 2026-09-30 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from app.db.ddl import enable_rls, tenant_policies

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None

ALL_APP_ROLES = ["estimator", "lead_estimator", "procurement_head", "bd_director", "managing_director"]
CALL_READ_ROLES = ["lead_estimator", "procurement_head", "bd_director", "managing_director"]
SETTINGS_ADMIN_ROLES = ["managing_director"]


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
        "tenant_ai_settings",
        *_entity_columns(),
        sa.Column("external_ai_allowed", sa.Boolean, nullable=False, server_default="false"),
        sa.UniqueConstraint("tenant_id", name="uq_tenant_ai_settings_tenant"),
    )
    op.create_index("ix_tenant_ai_settings_tenant_id", "tenant_ai_settings", ["tenant_id"])
    enable_rls(op, "tenant_ai_settings")
    tenant_policies(op, "tenant_ai_settings", write_roles=SETTINGS_ADMIN_ROLES)

    op.create_table(
        "ai_calls",
        *_entity_columns(),
        sa.Column("project_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("task", sa.String(48), nullable=False),
        sa.Column("provider", sa.String(24), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("prompt_version", sa.String(32), nullable=False, server_default="1"),
        sa.Column("entity_type", sa.String(48), nullable=True),
        sa.Column("entity_id", sa.String(64), nullable=True),
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("prompt", sa.Text, nullable=True),
        sa.Column("response", pg.JSONB, nullable=True),
        sa.Column("tokens_in", sa.Integer, nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer, nullable=False, server_default="0"),
        # ok | cached | error | blocked
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("external", sa.Boolean, nullable=False, server_default="false"),
    )
    op.create_index("ix_ai_calls_tenant_id", "ai_calls", ["tenant_id"])
    op.create_index("ix_ai_calls_project_id", "ai_calls", ["project_id"])
    op.create_index("ix_ai_calls_tenant_created", "ai_calls", ["tenant_id", "created_at"])
    enable_rls(op, "ai_calls")
    # No UPDATE/DELETE policies: calls are append-only. INSERT is open to all
    # app roles; SELECT is lead_estimator+ (prompt/response are internal).
    op.execute(
        "CREATE POLICY ai_calls_tenant_read ON ai_calls FOR SELECT "
        "USING (app_is_system() OR (tenant_id = app_tenant_id() "
        f"AND app_has_role({', '.join(repr(r) for r in CALL_READ_ROLES)})));"
    )
    op.execute(
        "CREATE POLICY ai_calls_tenant_write ON ai_calls FOR INSERT "
        "WITH CHECK (app_is_system() OR (tenant_id = app_tenant_id() "
        f"AND app_has_role({', '.join(repr(r) for r in ALL_APP_ROLES)})));"
    )

    op.create_table(
        "ai_cache",
        *_entity_columns(),
        sa.Column("task", sa.String(48), nullable=False),
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("prompt_version", sa.String(32), nullable=False),
        sa.Column("response", pg.JSONB, nullable=False),
        sa.Column("tokens_in", sa.Integer, nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer, nullable=False, server_default="0"),
        sa.UniqueConstraint(
            "tenant_id", "task", "input_sha256", "model", "prompt_version", name="uq_ai_cache_key"
        ),
    )
    op.create_index("ix_ai_cache_tenant_id", "ai_cache", ["tenant_id"])
    enable_rls(op, "ai_cache")
    tenant_policies(op, "ai_cache", write_roles=ALL_APP_ROLES)

    # Per-project override: NULL = inherit the tenant switch, FALSE = this
    # project never goes to an external provider. (TRUE is not meaningful:
    # a project cannot opt IN when the tenant switch is off.)
    op.add_column("projects", sa.Column("external_ai_override", sa.Boolean, nullable=True))


def downgrade() -> None:
    op.drop_column("projects", "external_ai_override")
    for table in ("ai_cache", "ai_calls", "tenant_ai_settings"):
        op.drop_table(table)
