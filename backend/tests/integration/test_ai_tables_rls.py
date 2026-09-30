"""Row-level security on every table the AI work added: enabled AND forced, tenant isolation, project scoping (a
non-member sees and writes nothing), append-only ai_calls, and the role split on writes."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from app.core.context import RequestContext
from app.db.rls import set_rls_context

pytestmark = pytest.mark.asyncio

TABLES = (
    "tenant_ai_settings", "ai_calls", "ai_cache", "boq_pdf_extractions", "drawing_annotations",
    "verification_runs", "verification_lines", "verification_mappings", "settlement_ai_runs", "settlement_ai_proposals",
)
PROJECT_SCOPED = (
    "boq_pdf_extractions", "drawing_annotations", "verification_runs", "verification_lines", "verification_mappings",
    "settlement_ai_runs", "settlement_ai_proposals",
)


def _ctx(roles: frozenset[str], tenant_id: uuid.UUID, *, user_id: uuid.UUID | None = None, is_system: bool = False) -> RequestContext:
    user_id = user_id or uuid.uuid4()
    return RequestContext(tenant_id=tenant_id, user_id=user_id, sub=str(user_id), roles=roles, is_system=is_system)


async def _seed(session, member_id: uuid.UUID) -> dict:
    tenant_id = uuid.uuid4()
    await set_rls_context(session, _ctx(frozenset(), tenant_id, is_system=True))
    await session.execute(text("INSERT INTO tenants (id, slug, name) VALUES (:i, :s, 'T')"), {"i": str(tenant_id), "s": f"rls-{uuid.uuid4().hex[:8]}"})
    t = str(tenant_id)
    project_id = (await session.execute(text("INSERT INTO projects (tenant_id, code, name) VALUES (:t, :c, 'P') RETURNING id"), {"t": t, "c": f"R-{uuid.uuid4().hex[:8]}"})).scalar_one()
    await session.execute(text("INSERT INTO project_members (project_id, user_id, tenant_id) VALUES (:p, :u, :t)"), {"p": str(project_id), "u": str(member_id), "t": t})
    await session.execute(text("INSERT INTO tenant_ai_settings (tenant_id, external_ai_allowed) VALUES (:t, true)"), {"t": t})
    await session.execute(
        text("INSERT INTO ai_calls (tenant_id, task, provider, model, input_sha256, status) VALUES (:t, 'x', 'mock', 'mock', :h, 'ok')"), {"t": t, "h": "a" * 64}
    )
    await session.execute(
        text("INSERT INTO ai_cache (tenant_id, task, input_sha256, model, prompt_version, response) VALUES (:t, 'x', :h, 'm', '1', '{}'::jsonb)"), {"t": t, "h": "b" * 64}
    )
    run_id = (await session.execute(text("INSERT INTO verification_runs (tenant_id, project_id) VALUES (:t, :p) RETURNING id"), {"t": t, "p": str(project_id)})).scalar_one()
    await session.execute(text("INSERT INTO verification_lines (tenant_id, project_id, run_id, vclass) VALUES (:t, :p, :r, 'match')"), {"t": t, "p": str(project_id), "r": str(run_id)})
    await session.execute(
        text("INSERT INTO boq_pdf_extractions (tenant_id, project_id, source_filename, bucket, object_key, sha256) VALUES (:t, :p, 'a.pdf', 'b', 'k', :h)"),
        {"t": t, "p": str(project_id), "h": "c" * 64},
    )
    return {"tenant": tenant_id, "project": project_id, "run": run_id}


async def test_rls_enabled_and_forced_on_every_new_table(rls_session):
    rows = await rls_session.execute(text("SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = ANY(:n)"), {"n": list(TABLES)})
    seen = {name: (rls, force) for name, rls, force in rows}
    assert set(seen) == set(TABLES) and all(v == (True, True) for v in seen.values()), seen


async def test_tenant_isolation_and_project_scoping(rls_session):
    member = uuid.uuid4()
    a = await _seed(rls_session, member)
    b = await _seed(rls_session, uuid.uuid4())
    # a member estimator of tenant A's project sees A's rows in the project-scoped tables, none of B's
    await set_rls_context(rls_session, _ctx(frozenset({"estimator"}), a["tenant"], user_id=member))
    for table in ("verification_runs", "verification_lines", "boq_pdf_extractions"):
        assert (await rls_session.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one() == 1, table
    assert (await rls_session.execute(text("SELECT count(*) FROM ai_cache"))).scalar_one() == 1
    assert (await rls_session.execute(text("SELECT count(*) FROM tenant_ai_settings"))).scalar_one() == 1
    # an estimator who is NOT a member of the project sees nothing project-scoped
    await set_rls_context(rls_session, _ctx(frozenset({"estimator"}), a["tenant"], user_id=uuid.uuid4()))
    for table in ("verification_runs", "verification_lines", "boq_pdf_extractions"):
        assert (await rls_session.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one() == 0, table
    # ...and cannot write into it either
    with pytest.raises((ProgrammingError, DBAPIError)):
        async with rls_session.begin_nested():
            await rls_session.execute(text("INSERT INTO verification_runs (tenant_id, project_id) VALUES (:t, :p)"), {"t": str(a["tenant"]), "p": str(a["project"])})
    # the other tenant's director sees only tenant B's rows
    await set_rls_context(rls_session, _ctx(frozenset({"managing_director"}), b["tenant"]))
    assert (await rls_session.execute(text("SELECT count(*) FROM verification_runs"))).scalar_one() == 1
    assert (await rls_session.execute(text("SELECT count(*) FROM verification_runs WHERE id=:i"), {"i": str(a["run"])})).scalar_one() == 0


async def test_ai_calls_role_split_and_append_only(rls_session):
    member = uuid.uuid4()
    a = await _seed(rls_session, member)
    est = _ctx(frozenset({"estimator"}), a["tenant"], user_id=member)
    lead = _ctx(frozenset({"lead_estimator"}), a["tenant"], user_id=member)
    await set_rls_context(rls_session, est)
    assert (await rls_session.execute(text("SELECT count(*) FROM ai_calls"))).scalar_one() == 0     # prompts/responses are internal
    await rls_session.execute(text("INSERT INTO ai_calls (tenant_id, task, provider, model, input_sha256, status) VALUES (:t, 'y', 'mock', 'mock', :h, 'ok')"),
                              {"t": str(a["tenant"]), "h": "d" * 64})     # ...but every role can write its own audit row
    await set_rls_context(rls_session, lead)
    assert (await rls_session.execute(text("SELECT count(*) FROM ai_calls"))).scalar_one() == 2
    assert (await rls_session.execute(text("UPDATE ai_calls SET error='tampered'"))).rowcount == 0     # append-only
    assert (await rls_session.execute(text("DELETE FROM ai_calls"))).rowcount == 0
    # the tenant switch: everyone can read it, only the managing director can write it
    assert (await rls_session.execute(text("SELECT external_ai_allowed FROM tenant_ai_settings"))).scalar_one() is True
    assert (await rls_session.execute(text("UPDATE tenant_ai_settings SET external_ai_allowed=false"))).rowcount == 0
    await set_rls_context(rls_session, _ctx(frozenset({"managing_director"}), a["tenant"]))
    assert (await rls_session.execute(text("UPDATE tenant_ai_settings SET external_ai_allowed=false"))).rowcount == 1
