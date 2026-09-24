"""Covers two things about app.services.takeoff.trigger_ingest():

1. It forwards exactly the calling actor's roles to the index_sheets
   Celery task -- no more, no less (see docs/takeoff-pipeline.md's "Two
   real bugs..." section: the original bug was forwarding *no* roles at
   all, which made every real actor's write fail RLS; the risk in fixing
   that is accidentally over-forwarding, e.g. granting every WRITE_ROLES
   role instead of just what the actor actually has).
2. RLS still blocks a user without project membership from triggering
   ingest at all -- get_drawing()'s SELECT is project_scoped with no role
   requirement of its own, so a non-member's query is silently filtered to
   zero rows (a clean 404 via NotFoundError), never reaching
   index_sheets.delay(). This is the same protection upload_drawing()
   *didn't* have (an INSERT has no prior read to be filtered by, so it
   fails hard instead -- see assert_can_see_project() in
   app/services/projects.py, added for exactly that gap) -- confirmed by
   raw SQL against the live dev stack before writing this test.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import text

from app.core.context import RequestContext
from app.core.enums import DrawingStatus
from app.core.errors import NotFoundError
from app.db.rls import set_rls_context
from app.services import takeoff as takeoff_service

pytestmark = pytest.mark.asyncio

TENANT = uuid.UUID("8f14e45f-ceea-4e97-8d0c-3d3b3f3c1a00")


async def _seed_project_and_drawing(session, sha256_suffix: str) -> tuple[str, str]:
    """Seeds as a system actor (bypasses RLS entirely), same pattern as
    test_geometry_measurements_rls.py."""
    system_ctx = RequestContext(tenant_id=TENANT, user_id=None, sub=None, roles=frozenset(), is_system=True)
    await set_rls_context(session, system_ctx)
    project_id = (
        await session.execute(
            text(
                "INSERT INTO projects (tenant_id, code, name) VALUES (:t, :code, 'trigger test') RETURNING id"
            ),
            {"t": str(TENANT), "code": f"TRIGGER-TEST-{sha256_suffix}"},
        )
    ).scalar_one()
    sha256 = ("2" * 68 + sha256_suffix)[-68:]  # unique, fixed-length, valid-looking hex-ish string
    drawing_id = (
        await session.execute(
            text(
                "INSERT INTO drawings (tenant_id, project_id, original_filename, kind, bucket, object_key, "
                "size_bytes, sha256, status) VALUES (:t, :p, 'test.dxf', 'dxf', 'b', 'k', 1, :sha, :status) "
                "RETURNING id"
            ),
            {"t": str(TENANT), "p": project_id, "sha": sha256, "status": DrawingStatus.UPLOADED.value},
        )
    ).scalar_one()
    return str(project_id), str(drawing_id)


async def test_trigger_ingest_forwards_exactly_the_actors_roles(rls_session):
    project_id, drawing_id = await _seed_project_and_drawing(rls_session, "aaa1")

    user_id = uuid.uuid4()
    # Membership is required for the actor's own SELECT of the drawing to
    # be visible at all (see module docstring); a realistic estimator
    # triggering ingest on a project they're actually assigned to.
    system_ctx = RequestContext(tenant_id=TENANT, user_id=None, sub=None, roles=frozenset(), is_system=True)
    await set_rls_context(rls_session, system_ctx)
    await rls_session.execute(
        text("INSERT INTO project_members (project_id, user_id, tenant_id, project_role) VALUES (:p, :u, :t, 'estimator')"),
        {"p": project_id, "u": str(user_id), "t": str(TENANT)},
    )

    actor_ctx = RequestContext(
        tenant_id=TENANT, user_id=user_id, sub=str(user_id), roles=frozenset({"estimator"}), is_system=False
    )
    await set_rls_context(rls_session, actor_ctx)

    with patch("app.workers.tasks.takeoff.index_sheets.delay") as mock_delay:
        await takeoff_service.trigger_ingest(rls_session, actor_ctx, uuid.UUID(drawing_id))

    mock_delay.assert_called_once()
    called_drawing_id, called_tenant_id, called_actor_user_id, called_actor_roles = mock_delay.call_args.args
    assert called_drawing_id == drawing_id
    assert called_tenant_id == str(TENANT)
    assert called_actor_user_id == str(user_id)
    # Exactly what the actor has -- not more (no "lead_estimator" or
    # "managing_director" slipped in) and not less (not silently empty,
    # which was the original bug).
    assert called_actor_roles == ["estimator"]


async def test_non_member_cannot_trigger_ingest_at_all(rls_session):
    # A real (non-system) actor with a legitimate WRITE_ROLES role, but no
    # project_members row for this project: get_drawing()'s project_scoped
    # SELECT policy has no role requirement of its own, only project
    # visibility -- so the query returns nothing (not a permission error),
    # and trigger_ingest raises NotFoundError before ever calling
    # index_sheets.delay(). No Celery dispatch, no partial state change.
    _project_id, drawing_id = await _seed_project_and_drawing(rls_session, "bbb2")

    user_id = uuid.uuid4()
    actor_ctx = RequestContext(
        tenant_id=TENANT, user_id=user_id, sub=str(user_id), roles=frozenset({"estimator"}), is_system=False
    )
    await set_rls_context(rls_session, actor_ctx)

    with patch("app.workers.tasks.takeoff.index_sheets.delay") as mock_delay:
        with pytest.raises(NotFoundError):
            await takeoff_service.trigger_ingest(rls_session, actor_ctx, uuid.UUID(drawing_id))
        mock_delay.assert_not_called()
