"""Fix: bid_settlement_line_items.cost_source was varchar(16), but SettlementCostSource.COST_LIBRARY_RATE
is 'cost_library_rate' (17 characters). Applying a cost-library rate to a settlement line (the
`cost_library_rate` path of settlement.set_line_cost) therefore always failed with
StringDataRightTruncationError; no test exercised that path. Found while building the AI pricing
assistant, which applies library rates through it.

Widening a varchar is a metadata-only change in Postgres; no data is rewritten.

Revision ID: 0036
Revises: 0035
Create Date: 2026-09-30 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "bid_settlement_line_items", "cost_source", existing_type=sa.String(16), type_=sa.String(24),
        existing_nullable=False, existing_server_default="manual",
    )


def downgrade() -> None:
    op.alter_column(
        "bid_settlement_line_items", "cost_source", existing_type=sa.String(24), type_=sa.String(16),
        existing_nullable=False, existing_server_default="manual",
    )
