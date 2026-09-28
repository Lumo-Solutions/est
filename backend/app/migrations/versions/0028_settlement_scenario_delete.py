"""Phase 3 gap-fill (docs/ui-qa-brief.md): add bid_settlement_scenarios'
missing DELETE policy

Migration 0019 enabled RLS on bid_settlement_scenarios and created its
SELECT/INSERT/UPDATE policies via tenant_policies(write_roles=LINE_WRITE_ROLES,
project_scoped=True) but never passed delete_roles, because no delete
endpoint existed yet -- tenant_policies() only emits a DELETE policy when
delete_roles is truthy (app/db/ddl.py). With RLS enabled and force-enabled
on every table by this app's own convention (FORCE ROW LEVEL SECURITY --
see migration 0002) and no matching DELETE policy, Postgres denies every
DELETE by default: no exception, just 0 rows affected.

Found live, not assumed: app.services.settlement::delete_scenario's new
DELETE (added alongside this migration, docs/ui-qa/issues.md UI-P2-*)
returned 0 matched rows for a real estimator-owned scenario, exactly the
same silent-DELETE-does-nothing shape migration 0022 already found and
fixed once for drawing_measurements.

Fix: DELETE_ROLES = the same 5 roles LINE_WRITE_ROLES already covers
(scenarios are "purely a UI convenience" per BidSettlementScenario's own
docstring -- whoever can save one should be able to remove their own
scratch work; no reason for a narrower delete role than create).

Revision ID: 0028
Revises: 0027
Create Date: 2026-09-28 00:00:00
"""

from __future__ import annotations

from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None

_DELETE_ROLES = ["estimator", "lead_estimator", "procurement_head", "bd_director", "managing_director"]


def _role_list_sql(roles: list[str]) -> str:
    quoted = ", ".join(f"'{r}'" for r in roles)
    return f"app_has_role({quoted})"


def upgrade() -> None:
    op.execute(
        "CREATE POLICY bid_settlement_scenarios_tenant_delete ON bid_settlement_scenarios FOR DELETE "
        "USING (app_is_system() OR (tenant_id = app_tenant_id() AND "
        f"{_role_list_sql(_DELETE_ROLES)} AND app_can_see_project(project_id)));"
    )


def downgrade() -> None:
    op.execute("DROP POLICY bid_settlement_scenarios_tenant_delete ON bid_settlement_scenarios;")
