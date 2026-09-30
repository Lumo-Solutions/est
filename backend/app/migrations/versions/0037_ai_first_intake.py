"""AI-first tender intake: the auto-accept threshold, who classified a document, and archived drawings.

* tenant_ai_settings.intake_auto_accept_min: AI classifications at or above this confidence are accepted and
  routed without a person (default 0.850; managing_director changes it, audited).
* project_documents.classified_by ('ai' | 'rules' | 'user') and auto_accepted: which decider the current
  classification comes from, and whether it was routed without a person.
* addenda.withdrawn_at / withdrawn_reason: an addendum reclassified as something else is withdrawn from the
  register (rows are never deleted; there is no DELETE policy on addenda), and revived if it is routed again.
* drawings.archived_at / archived_reason: a drawing reclassified as something else leaves the takeoff but keeps
  its sheets and measurements (archived, never deleted). Existing RLS policies already cover these columns.

Revision ID: 0037
Revises: 0036
Create Date: 2026-10-01 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenant_ai_settings",
        sa.Column("intake_auto_accept_min", sa.Numeric(4, 3), nullable=False, server_default="0.850"),
    )
    op.add_column("project_documents", sa.Column("classified_by", sa.String(16), nullable=True))
    op.add_column("project_documents", sa.Column("auto_accepted", sa.Boolean, nullable=False, server_default="false"))
    op.execute(
        "UPDATE project_documents SET classified_by = CASE "
        "WHEN confirmed_by IS NOT NULL THEN 'user' ELSE 'rules' END WHERE doc_class IS NOT NULL"
    )
    op.add_column("addenda", sa.Column("withdrawn_at", pg.TIMESTAMP(timezone=True), nullable=True))
    op.add_column("addenda", sa.Column("withdrawn_reason", sa.String(255), nullable=True))
    op.add_column("drawings", sa.Column("archived_at", pg.TIMESTAMP(timezone=True), nullable=True))
    op.add_column("drawings", sa.Column("archived_reason", sa.String(255), nullable=True))
    op.create_index("ix_drawings_archived_at", "drawings", ["archived_at"])


def downgrade() -> None:
    op.drop_index("ix_drawings_archived_at", table_name="drawings")
    op.drop_column("addenda", "withdrawn_reason")
    op.drop_column("addenda", "withdrawn_at")
    op.drop_column("drawings", "archived_reason")
    op.drop_column("drawings", "archived_at")
    op.drop_column("project_documents", "auto_accepted")
    op.drop_column("project_documents", "classified_by")
    op.drop_column("tenant_ai_settings", "intake_auto_accept_min")
