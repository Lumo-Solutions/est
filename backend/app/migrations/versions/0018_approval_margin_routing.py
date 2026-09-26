"""Module D1: approval-engine margin-based tier escalation

Adds approval_policy_tiers.max_margin_pct: a tier can now match either its
amount bracket (unchanged) OR (new) a caller-supplied margin_pct below this
floor, regardless of amount. NULL -- the default, and every existing tier's
value -- preserves the old amount-only behaviour exactly; only a policy
that explicitly sets this on a tier (Module D1's `bid_submission` policy,
seeded via `app.cli seed`) uses it. See
app/services/approvals.py::route_tiers and docs/module-d1-plan.md §2a.

Segregation of duties (the submitter can never decide their own request) is
a code-only fix in app/services/approvals.py::decide -- no schema change.

Revision ID: 0018
Revises: 0017
Create Date: 2026-01-02 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("approval_policy_tiers", sa.Column("max_margin_pct", sa.Numeric(5, 2), nullable=True))


def downgrade() -> None:
    op.drop_column("approval_policy_tiers", "max_margin_pct")
