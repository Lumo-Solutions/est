"""Settlement lines filled by the BOQ agent: which proposal set the line and who confirmed it.

* bid_settlement_line_items.agent_proposal_id: the agent_line_proposals row behind an `agent_candidate` /
  `agent_estimate` line (SET NULL if the proposal row is ever removed; the cost stays, the submit gate still sees the
  agent cost source with no confirmation).
* agent_confirmed_by / agent_confirmed_at: the person who confirmed the agent line. `submit_settlement` refuses a
  settlement with an agent line that has no confirmation.
`cost_source` is a varchar(24) since 0036; the new values ('agent_candidate', 'agent_estimate') fit.

Revision ID: 0042
Revises: 0041
Create Date: 2026-10-10 12:30:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "bid_settlement_line_items",
        sa.Column("agent_proposal_id", pg.UUID(as_uuid=True), sa.ForeignKey("agent_line_proposals.id", ondelete="SET NULL"), nullable=True),
    )
    op.add_column("bid_settlement_line_items", sa.Column("agent_confirmed_by", pg.UUID(as_uuid=True), nullable=True))
    op.add_column("bid_settlement_line_items", sa.Column("agent_confirmed_at", pg.TIMESTAMP(timezone=True), nullable=True))
    op.create_index("ix_bid_settlement_line_items_agent_proposal_id", "bid_settlement_line_items", ["agent_proposal_id"])


def downgrade() -> None:
    op.drop_index("ix_bid_settlement_line_items_agent_proposal_id", table_name="bid_settlement_line_items")
    op.drop_column("bid_settlement_line_items", "agent_confirmed_at")
    op.drop_column("bid_settlement_line_items", "agent_confirmed_by")
    op.drop_column("bid_settlement_line_items", "agent_proposal_id")
