"""immutable hash-chained audit trail

Revision ID: 0003
Revises: 0002
Create Date: 2026-01-01 00:00:02

See docs/audit-chain.md for the exact hashing scheme this trigger implements.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from app.db.ddl import audit_insert_only_policies, enable_rls

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

_CHAIN_TRIGGER_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION audit_events_chain_trg() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_last_seq bigint;
    v_last_hash char(64);
BEGIN
    NEW.chain_date := COALESCE(NEW.chain_date, (NEW.occurred_at AT TIME ZONE 'UTC')::date);
    NEW.payload := COALESCE(NEW.payload, '{}'::jsonb);
    NEW.payload_sha256 := encode(digest(NEW.payload::text, 'sha256'), 'hex');

    INSERT INTO audit_chain_heads (tenant_id, chain_date, last_seq, last_hash, updated_at)
    VALUES (NEW.tenant_id, NEW.chain_date, 0, repeat('0', 64), now())
    ON CONFLICT (tenant_id, chain_date) DO NOTHING;

    SELECT last_seq, last_hash INTO v_last_seq, v_last_hash
    FROM audit_chain_heads
    WHERE tenant_id = NEW.tenant_id AND chain_date = NEW.chain_date
    FOR UPDATE;

    NEW.seq := v_last_seq + 1;
    NEW.prev_hash := v_last_hash;

    NEW.canonical_json := jsonb_build_object(
        'v', 1,
        'tenant_id', NEW.tenant_id,
        'chain_date', NEW.chain_date,
        'seq', NEW.seq,
        'occurred_at', to_char(NEW.occurred_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
        'actor_sub', NEW.actor_sub,
        'actor_user_id', NEW.actor_user_id,
        'actor_roles', to_jsonb((SELECT coalesce(array_agg(r ORDER BY r), ARRAY[]::text[]) FROM unnest(NEW.actor_roles) r)),
        'actor_acr', NEW.actor_acr,
        'action', NEW.action,
        'entity_type', NEW.entity_type,
        'entity_id', NEW.entity_id,
        'project_id', NEW.project_id,
        'ip', host(NEW.ip_address),
        'user_agent', NEW.user_agent,
        'request_id', NEW.request_id,
        'payload_sha256', NEW.payload_sha256
    )::text;

    NEW.event_hash := encode(digest(NEW.prev_hash || '|' || NEW.canonical_json, 'sha256'), 'hex');

    UPDATE audit_chain_heads
    SET last_seq = NEW.seq, last_hash = NEW.event_hash, updated_at = now()
    WHERE tenant_id = NEW.tenant_id AND chain_date = NEW.chain_date;

    RETURN NEW;
END;
$$;
"""


def upgrade() -> None:
    op.create_table(
        "audit_chain_heads",
        sa.Column("tenant_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("chain_date", sa.Date, primary_key=True),
        sa.Column("last_seq", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("last_hash", sa.String(64), nullable=False, server_default="0" * 64),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "audit_events",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("chain_date", sa.Date, nullable=False),
        sa.Column("seq", sa.BigInteger, nullable=False),
        sa.Column("occurred_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("clock_timestamp()")),
        sa.Column("actor_user_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_sub", sa.String(255), nullable=True),
        sa.Column("actor_roles", pg.ARRAY(sa.Text), nullable=False, server_default="{}"),
        sa.Column("actor_acr", sa.String(16), nullable=True),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.String(64), nullable=True),
        sa.Column("project_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("ip_address", pg.INET, nullable=True),
        sa.Column("user_agent", sa.Text, nullable=True),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("payload", pg.JSONB, nullable=False, server_default="{}"),
        sa.Column("payload_sha256", sa.String(64), nullable=False, server_default=""),
        sa.Column("prev_hash", sa.String(64), nullable=False, server_default=""),
        sa.Column("event_hash", sa.String(64), nullable=False, server_default=""),
        sa.Column("canonical_json", sa.Text, nullable=False, server_default=""),
        sa.UniqueConstraint("tenant_id", "chain_date", "seq", name="uq_audit_events_tenant_date_seq"),
        sa.UniqueConstraint("event_hash", name="uq_audit_events_event_hash"),
    )
    op.create_index("ix_audit_events_tenant_id", "audit_events", ["tenant_id"])
    op.create_index("ix_audit_events_entity", "audit_events", ["tenant_id", "entity_type", "entity_id"])
    op.create_index("ix_audit_events_tenant_time", "audit_events", ["tenant_id", "occurred_at"])
    op.create_index("ix_audit_events_actor_time", "audit_events", ["tenant_id", "actor_user_id", "occurred_at"])

    op.create_table(
        "audit_checkpoints",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("chain_date", sa.Date, nullable=False),
        sa.Column("head_seq", sa.BigInteger, nullable=False),
        sa.Column("head_hash", sa.String(64), nullable=False),
        sa.Column("hmac", sa.String(64), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_audit_checkpoints_tenant_id", "audit_checkpoints", ["tenant_id"])

    op.execute(_CHAIN_TRIGGER_FUNCTION_SQL)
    op.execute(
        "CREATE TRIGGER audit_events_chain_trg BEFORE INSERT ON audit_events "
        "FOR EACH ROW EXECUTE FUNCTION audit_events_chain_trg();"
    )
    op.execute(
        "CREATE TRIGGER audit_events_no_mutate BEFORE UPDATE OR DELETE OR TRUNCATE ON audit_events "
        "FOR EACH STATEMENT EXECUTE FUNCTION raise_immutable();"
    )
    # Row-level trigger too: FOR EACH STATEMENT above catches bulk UPDATE/DELETE
    # with zero matched rows differently than per-row use cases; belt-and-braces.
    op.execute(
        "CREATE TRIGGER audit_events_no_mutate_row BEFORE UPDATE OR DELETE ON audit_events "
        "FOR EACH ROW EXECUTE FUNCTION raise_immutable();"
    )

    enable_rls(op, "audit_events")
    audit_insert_only_policies(op, "audit_events")
    enable_rls(op, "audit_chain_heads")
    op.execute(
        "CREATE POLICY audit_chain_heads_system ON audit_chain_heads FOR ALL "
        "USING (app_is_system() OR tenant_id = app_tenant_id()) "
        "WITH CHECK (tenant_id = app_tenant_id() OR app_is_system());"
    )
    enable_rls(op, "audit_checkpoints")
    op.execute(
        "CREATE POLICY audit_checkpoints_read ON audit_checkpoints FOR SELECT "
        "USING (app_is_system() OR tenant_id = app_tenant_id());"
    )
    op.execute(
        "CREATE POLICY audit_checkpoints_insert ON audit_checkpoints FOR INSERT "
        "WITH CHECK (app_is_system() OR tenant_id = app_tenant_id());"
    )

    # Revoke UPDATE/DELETE/TRUNCATE from the app role at the grant layer too
    # (belt-and-braces alongside the triggers and the missing RLS policies).
    op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON audit_events FROM installtec_app;")


def downgrade() -> None:
    op.execute("GRANT UPDATE, DELETE, TRUNCATE ON audit_events TO installtec_app;")
    op.execute("DROP TRIGGER IF EXISTS audit_events_no_mutate_row ON audit_events;")
    op.execute("DROP TRIGGER IF EXISTS audit_events_no_mutate ON audit_events;")
    op.execute("DROP TRIGGER IF EXISTS audit_events_chain_trg ON audit_events;")
    op.execute("DROP FUNCTION IF EXISTS audit_events_chain_trg() CASCADE;")
    op.drop_table("audit_checkpoints")
    op.drop_table("audit_events")
    op.drop_table("audit_chain_heads")
