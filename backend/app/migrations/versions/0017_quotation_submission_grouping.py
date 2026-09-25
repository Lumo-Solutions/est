"""Module C2 fix: one quotation per inbound email, not per attachment

Adds quotation_attachments.quotation_id (every attachment on one inbound
email links to the single Quotation that email produced -- supporting
documents included, not just the one actually extracted from) and
is_primary (which attachment that extraction came from). See
app/workers/tasks/quotation_ingestion.py::_process_inbound_email_body.

No RLS policy change needed: quotation_attachments' existing bespoke
policies (migration 0016) already cover UPDATE of any column on rows this
tenant/platform_admin can already see.

Revision ID: 0017
Revises: 0016
Create Date: 2026-01-01 00:00:16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "quotation_attachments",
        sa.Column("quotation_id", pg.UUID(as_uuid=True), sa.ForeignKey("quotations.id", ondelete="SET NULL"), nullable=True),
    )
    op.add_column(
        "quotation_attachments",
        sa.Column("is_primary", sa.Boolean, nullable=False, server_default="false"),
    )
    op.create_index("ix_quotation_attachments_quotation_id", "quotation_attachments", ["quotation_id"])


def downgrade() -> None:
    op.drop_index("ix_quotation_attachments_quotation_id", table_name="quotation_attachments")
    op.drop_column("quotation_attachments", "is_primary")
    op.drop_column("quotation_attachments", "quotation_id")
