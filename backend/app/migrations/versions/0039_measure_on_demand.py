"""Measure on demand, AI cost estimate before spending.

* drawings.measure_priority: the priority a drawing was last queued at (0 = a person is looking at it, 3 = the
  verification report needs it, 6 = a bulk "Measure all", 9 = automatic on intake), so a drawing waiting at a low
  priority can be bumped when someone opens it. The new drawing status `indexed` is a plain varchar value.
* tenant_ai_settings.intake_auto_measure: disciplines whose drawings are measured automatically when intake routes
  them (default: none, i.e. empty list).
* tender_packages.cost_confirmed_at / cost_confirmed_usd / cost_confirmed_by: a pack read by an external AI provider
  starts only after a lead estimator confirmed the estimated cost.
* ai_calls.tokens_cached: prompt tokens the provider served from its cache (billed at the cached rate).

Revision ID: 0039
Revises: 0038
Create Date: 2026-10-02 09:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("drawings", sa.Column("measure_priority", sa.SmallInteger, nullable=True))
    op.add_column(
        "tenant_ai_settings",
        sa.Column("intake_auto_measure", pg.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.add_column("tender_packages", sa.Column("cost_confirmed_at", pg.TIMESTAMP(timezone=True), nullable=True))
    op.add_column("tender_packages", sa.Column("cost_confirmed_usd", sa.Numeric(12, 4), nullable=True))
    op.add_column("tender_packages", sa.Column("cost_confirmed_by", pg.UUID(as_uuid=True), nullable=True))
    op.add_column("ai_calls", sa.Column("tokens_cached", sa.Integer, nullable=False, server_default="0"))
    # Existing packs are deliberately left unconfirmed: a pack that is still unread when an external provider is
    # configured waits for a lead estimator to see the estimate and confirm it.


def downgrade() -> None:
    op.drop_column("ai_calls", "tokens_cached")
    op.drop_column("tender_packages", "cost_confirmed_by")
    op.drop_column("tender_packages", "cost_confirmed_usd")
    op.drop_column("tender_packages", "cost_confirmed_at")
    op.drop_column("tenant_ai_settings", "intake_auto_measure")
    op.drop_column("drawings", "measure_priority")
