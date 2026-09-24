from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.asyncio

TENANT = "8f14e45f-ceea-4e97-8d0c-3d3b3f3c1a00"


async def _set_guc(session, *, roles: str, is_system: str = "off") -> None:
    await session.execute(
        text(
            "SELECT set_config('app.tenant_id', :t, false), set_config('app.user_id', :u, false), "
            "set_config('app.roles', :r, false), set_config('app.is_system', :sys, false)"
        ),
        {"t": TENANT, "u": str(uuid.uuid4()), "r": roles, "sys": is_system},
    )


async def _seed_drawing_sheet(session) -> tuple[str, str, str]:
    """Seeds a project/drawing/drawing_sheet as a system actor (same
    privilege level app.workers.tasks.takeoff's Celery tasks run under) and
    returns (project_id, drawing_id, sheet_id) for FK-satisfying inserts
    into drawing_measurements."""
    await _set_guc(session, roles="", is_system="on")
    project_id = (
        await session.execute(
            text("INSERT INTO projects (tenant_id, code, name) VALUES (:t, 'RLS-MEAS-TEST', 'RLS test') RETURNING id"),
            {"t": TENANT},
        )
    ).scalar_one()
    drawing_id = (
        await session.execute(
            text(
                "INSERT INTO drawings (tenant_id, project_id, original_filename, kind, bucket, object_key, "
                "size_bytes, sha256) VALUES (:t, :p, 'test.dxf', 'dxf', 'test-bucket', 'test-key', 1, "
                "'0000000000000000000000000000000000000000000000000000000000000000') RETURNING id"
            ),
            {"t": TENANT, "p": project_id},
        )
    ).scalar_one()
    sheet_id = (
        await session.execute(
            text(
                "INSERT INTO drawing_sheets (tenant_id, drawing_id, project_id, sheet_index) "
                "VALUES (:t, :d, :p, 0) RETURNING id"
            ),
            {"t": TENANT, "d": drawing_id, "p": project_id},
        )
    ).scalar_one()
    return str(project_id), str(drawing_id), str(sheet_id)


def _insert_measurement_sql() -> str:
    return (
        "INSERT INTO drawing_measurements (tenant_id, drawing_id, sheet_id, project_id, capability, kind, "
        "value, unit, confidence, source_entity_ids) VALUES "
        "(:t, :d, :s, :p, 'alignment', 'alignment_length_m', 10.0, 'm', 1.0, '[]'::jsonb)"
    )


async def test_system_actor_can_write_measurements(rls_session):
    # This is the actual privilege level extract_geometry_measurements runs
    # under (build_worker_context() with no actor_user_id -> is_system=True)
    # -- confirms the Celery task's own write path is not blocked by RLS.
    project_id, drawing_id, sheet_id = await _seed_drawing_sheet(rls_session)
    await _set_guc(rls_session, roles="", is_system="on")
    await rls_session.execute(
        text(_insert_measurement_sql()), {"t": TENANT, "d": drawing_id, "s": sheet_id, "p": project_id}
    )
    result = await rls_session.execute(
        text("SELECT count(*) FROM drawing_measurements WHERE drawing_id = :d"), {"d": drawing_id}
    )
    assert result.scalar_one() == 1


async def test_actor_with_no_matching_role_cannot_write_measurements(rls_session):
    # A real (non-system) actor whose roles don't include any of WRITE_ROLES
    # -- e.g. the exact bug this migration's write policy would have caught
    # in app.services.takeoff.trigger_ingest before actor_roles forwarding
    # was fixed (see docs/takeoff-pipeline.md).
    project_id, drawing_id, sheet_id = await _seed_drawing_sheet(rls_session)
    await _set_guc(rls_session, roles="auditor")
    with pytest.raises(Exception, match=r"(?i)row-level security"):
        async with rls_session.begin_nested():
            await rls_session.execute(
                text(_insert_measurement_sql()), {"t": TENANT, "d": drawing_id, "s": sheet_id, "p": project_id}
            )


async def test_estimator_without_project_membership_cannot_write_measurements(rls_session):
    # estimator IS in WRITE_ROLES, but this table is project_scoped
    # (app_can_see_project(project_id)), which for a plain "estimator" role
    # additionally requires a project_members row -- there isn't one here.
    # This is real, correct behavior (an estimator must be added to a
    # project before writing into it), not a gap; confirmed directly
    # against the live dev stack's RLS before writing this test, since it's
    # easy to assume WRITE_ROLES membership alone is sufficient and it
    # isn't for a project_scoped table.
    project_id, drawing_id, sheet_id = await _seed_drawing_sheet(rls_session)
    await _set_guc(rls_session, roles="estimator")
    with pytest.raises(Exception, match=r"(?i)row-level security"):
        async with rls_session.begin_nested():
            await rls_session.execute(
                text(_insert_measurement_sql()), {"t": TENANT, "d": drawing_id, "s": sheet_id, "p": project_id}
            )


async def test_bd_director_can_write_without_project_membership(rls_session):
    # bd_director (and managing_director/procurement_head) bypass the
    # project_members check entirely in app_can_see_project() -- a real
    # (non-system) actor with this role can write with no membership row,
    # unlike plain "estimator" above.
    project_id, drawing_id, sheet_id = await _seed_drawing_sheet(rls_session)
    await _set_guc(rls_session, roles="bd_director")
    await rls_session.execute(
        text(_insert_measurement_sql()), {"t": TENANT, "d": drawing_id, "s": sheet_id, "p": project_id}
    )
    result = await rls_session.execute(
        text("SELECT count(*) FROM drawing_measurements WHERE drawing_id = :d"), {"d": drawing_id}
    )
    assert result.scalar_one() == 1
