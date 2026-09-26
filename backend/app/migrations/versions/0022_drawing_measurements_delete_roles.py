"""Module B Phase 4a: widen drawing_measurements' DELETE policy

Migration 0010 scoped drawing_measurements' DELETE policy to
["lead_estimator", "procurement_head", "managing_director"] on the
assumption that app.services.takeoff::recompute_sheet_measurements is
"written only by the extract_geometry_measurements Celery task (system
actor, bypasses RLS via app_is_system())" -- true when it was written, but
Phase 4a made that same function reachable from request-path code with a
real (non-system) actor: set_manual_scale and revert_scale_calibration
(behind the same require_roles(*_UPLOAD_ROLES) as every other drawing
mutation -- estimator/lead_estimator/procurement_head/bd_director/
managing_director) both call it directly so a calibration change is
reflected immediately.

Found by running app.cli simulate-takeoff-pdf (as "estimator", the lowest
of those five roles) against a real dev stack: recompute's DELETE FOR
{sheet_id} silently matched zero rows under FORCE ROW LEVEL SECURITY
(default-deny with no matching policy), so recompute only ever ADDED
measurement rows, never removed the old ones -- list_measurements() then
non-deterministically returned whichever same-kind row a plain ORDER BY
sheet_id, capability, kind happened to place first, not necessarily the
latest. Confirmed via drawing_measurements directly: three
alignment_length_m rows survived one calibrate + one revert, where there
should only ever be one.

Fix: DELETE_ROLES for this table becomes the same five roles WRITE_ROLES
already covers (every role that can call set_manual_scale/
revert_scale_calibration), not a narrower subset -- read/insert/update
policies are untouched.

Revision ID: 0022
Revises: 0021
Create Date: 2026-01-05 00:00:00
"""

from __future__ import annotations

from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None

_OLD_DELETE_ROLES = ["lead_estimator", "procurement_head", "managing_director"]
_NEW_DELETE_ROLES = ["estimator", "lead_estimator", "procurement_head", "bd_director", "managing_director"]


def _role_list_sql(roles: list[str]) -> str:
    quoted = ", ".join(f"'{r}'" for r in roles)
    return f"app_has_role({quoted})"


def upgrade() -> None:
    op.execute("DROP POLICY drawing_measurements_tenant_delete ON drawing_measurements;")
    op.execute(
        "CREATE POLICY drawing_measurements_tenant_delete ON drawing_measurements FOR DELETE "
        "USING (app_is_system() OR (tenant_id = app_tenant_id() AND "
        f"{_role_list_sql(_NEW_DELETE_ROLES)} AND app_can_see_project(project_id)));"
    )


def downgrade() -> None:
    op.execute("DROP POLICY drawing_measurements_tenant_delete ON drawing_measurements;")
    op.execute(
        "CREATE POLICY drawing_measurements_tenant_delete ON drawing_measurements FOR DELETE "
        "USING (app_is_system() OR (tenant_id = app_tenant_id() AND "
        f"{_role_list_sql(_OLD_DELETE_ROLES)} AND app_can_see_project(project_id)));"
    )
