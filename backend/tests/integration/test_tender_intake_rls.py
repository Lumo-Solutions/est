"""Tender intake tables: RLS is ENABLED and FORCED, tenant isolation, project scoping
(a non-member estimator sees and writes nothing), and the role split on writes:
estimators write packages/documents/classifications, only lead_estimator+ writes
addenda, only managing_director writes class overrides."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import RequestContext
from app.db.rls import set_rls_context

pytestmark = pytest.mark.asyncio

TABLES = (
    "tender_packages", "project_documents", "document_classifications", "addenda", "addendum_links", "tender_class_config",
)
PROJECT_SCOPED = TABLES[:-1]
SHA = "a" * 64


def _ctx(roles: frozenset[str], *, tenant_id: uuid.UUID, user_id: uuid.UUID | None = None, is_system: bool = False) -> RequestContext:
    user_id = user_id or uuid.uuid4()
    return RequestContext(tenant_id=tenant_id, user_id=user_id, sub=str(user_id), roles=roles, is_system=is_system)


async def _seed_tenant(session: AsyncSession, member_id: uuid.UUID) -> dict:
    """One tenant with a project (member_id is a member), and one row in every table."""
    tenant_id = uuid.uuid4()
    await set_rls_context(session, _ctx(frozenset(), tenant_id=tenant_id, is_system=True))
    await session.execute(
        text("INSERT INTO tenants (id, slug, name) VALUES (:id, :slug, 'T')"),
        {"id": str(tenant_id), "slug": f"t-{uuid.uuid4().hex[:8]}"},
    )
    t = str(tenant_id)
    project_id = (
        await session.execute(text("INSERT INTO projects (tenant_id, code, name) VALUES (:t, :c, 'P') RETURNING id"), {"t": t, "c": f"TI-{uuid.uuid4().hex[:8]}"})
    ).scalar_one()
    await session.execute(
        text("INSERT INTO project_members (project_id, user_id, tenant_id) VALUES (:p, :u, :t)"),
        {"p": str(project_id), "u": str(member_id), "t": t},
    )
    package_id = (
        await session.execute(text("INSERT INTO tender_packages (tenant_id, project_id) VALUES (:t, :p) RETURNING id"), {"t": t, "p": str(project_id)})
    ).scalar_one()
    doc_id = (
        await session.execute(
            text(
                "INSERT INTO project_documents (tenant_id, project_id, package_id, original_filename, sha256, bucket, object_key, size_bytes) "
                "VALUES (:t, :p, :k, 'a.pdf', :sha, 'b', 'tender/x', 1) RETURNING id"
            ),
            {"t": t, "p": str(project_id), "k": str(package_id), "sha": SHA},
        )
    ).scalar_one()
    await session.execute(
        text(
            "INSERT INTO document_classifications (tenant_id, project_id, document_id, source, doc_class, confidence) "
            "VALUES (:t, :p, :d, 'rules', 'boq', 0.9)"
        ),
        {"t": t, "p": str(project_id), "d": str(doc_id)},
    )
    addendum_id = (
        await session.execute(
            text("INSERT INTO addenda (tenant_id, project_id, document_id) VALUES (:t, :p, :d) RETURNING id"),
            {"t": t, "p": str(project_id), "d": str(doc_id)},
        )
    ).scalar_one()
    await session.execute(
        text("INSERT INTO addendum_links (tenant_id, project_id, addendum_id, reference_text) VALUES (:t, :p, :a, 'C-101 Rev A')"),
        {"t": t, "p": str(project_id), "a": str(addendum_id)},
    )
    await session.execute(text("INSERT INTO tender_class_config (tenant_id, code, label) VALUES (:t, 'boq', 'Priced BOQ')"), {"t": t})
    return {"tenant": tenant_id, "project": project_id, "package": package_id, "doc": doc_id, "addendum": addendum_id}


async def _counts(session: AsyncSession) -> dict[str, int]:
    return {t: (await session.execute(text(f"SELECT count(*) FROM {t}"))).scalar_one() for t in TABLES}


async def test_rls_is_enabled_and_forced_on_every_table(rls_session):
    rows = await rls_session.execute(
        text("SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = ANY(:names)"),
        {"names": list(TABLES)},
    )
    seen = {name: (rls, force) for name, rls, force in rows}
    assert set(seen) == set(TABLES)
    assert all(rls and force for rls, force in seen.values()), seen


async def test_tenant_isolation_on_every_table(rls_session):
    member = uuid.uuid4()
    a = await _seed_tenant(rls_session, member)
    b = await _seed_tenant(rls_session, member)

    await set_rls_context(rls_session, _ctx(frozenset({"managing_director"}), tenant_id=a["tenant"]))
    assert await _counts(rls_session) == dict.fromkeys(TABLES, 1)
    await set_rls_context(rls_session, _ctx(frozenset({"managing_director"}), tenant_id=b["tenant"]))
    assert await _counts(rls_session) == dict.fromkeys(TABLES, 1)
    # A's ids are invisible from B.
    got = (await rls_session.execute(text("SELECT count(*) FROM project_documents WHERE id = :i"), {"i": str(a["doc"])})).scalar_one()
    assert got == 0

    # And a foreign tenant_id cannot be written.
    with pytest.raises(Exception, match=r"(?i)row-level security"):
        async with rls_session.begin_nested():
            await rls_session.execute(
                text("INSERT INTO tender_packages (tenant_id, project_id) VALUES (:t, :p)"),
                {"t": str(a["tenant"]), "p": str(b["project"])},
            )


async def test_project_scoped_tables_hide_everything_from_a_non_member_estimator(rls_session):
    member = uuid.uuid4()
    a = await _seed_tenant(rls_session, member)

    outsider = _ctx(frozenset({"estimator"}), tenant_id=a["tenant"])
    await set_rls_context(rls_session, outsider)
    counts = await _counts(rls_session)
    assert all(counts[t] == 0 for t in PROJECT_SCOPED), counts
    assert counts["tender_class_config"] == 1  # tenant level, not project scoped

    with pytest.raises(Exception, match=r"(?i)row-level security"):
        async with rls_session.begin_nested():
            await rls_session.execute(
                text("INSERT INTO tender_packages (tenant_id, project_id) VALUES (:t, :p)"), {"t": str(a["tenant"]), "p": str(a["project"])}
            )

    # The member sees their project's rows; bd_director / procurement_head / md see all projects.
    await set_rls_context(rls_session, _ctx(frozenset({"estimator"}), tenant_id=a["tenant"], user_id=member))
    assert (await _counts(rls_session))["project_documents"] == 1
    for role in ("bd_director", "procurement_head", "managing_director"):
        await set_rls_context(rls_session, _ctx(frozenset({role}), tenant_id=a["tenant"]))
        assert (await _counts(rls_session))["project_documents"] == 1


async def _insert_ok(session: AsyncSession, sql: str, params: dict) -> None:
    async with session.begin_nested():
        await session.execute(text(sql), params)


async def _insert_denied(session: AsyncSession, sql: str, params: dict) -> None:
    with pytest.raises(Exception, match=r"(?i)row-level security"):
        async with session.begin_nested():
            await session.execute(text(sql), params)


async def test_write_roles_estimator_uploads_but_only_lead_writes_addenda_and_only_md_writes_class_config(rls_session):
    member = uuid.uuid4()
    a = await _seed_tenant(rls_session, member)
    t, p, doc = str(a["tenant"]), str(a["project"]), str(a["doc"])

    package_sql = "INSERT INTO tender_packages (tenant_id, project_id) VALUES (:t, :p)"
    classification_sql = (
        "INSERT INTO document_classifications (tenant_id, project_id, document_id, source, doc_class, confidence) "
        "VALUES (:t, :p, :d, 'model', 'boq', 0.5)"
    )
    addendum_sql = "INSERT INTO addenda (tenant_id, project_id, document_id) VALUES (:t, :p, :d)"
    link_sql = "INSERT INTO addendum_links (tenant_id, project_id, addendum_id, reference_text) VALUES (:t, :p, :a, 'X-1')"
    config_sql = "INSERT INTO tender_class_config (tenant_id, code, label) VALUES (:t, 'contract', 'Contracts')"
    base = {"t": t, "p": p, "d": doc, "a": str(a["addendum"])}

    # Lowest role that may upload: estimator (a project member).
    estimator = _ctx(frozenset({"estimator"}), tenant_id=a["tenant"], user_id=member)
    await set_rls_context(rls_session, estimator)
    await _insert_ok(rls_session, package_sql, base)
    await _insert_ok(rls_session, classification_sql, base)
    # ... but not the addenda register or class overrides.
    await _insert_denied(rls_session, addendum_sql, base)
    await _insert_denied(rls_session, link_sql, base)
    await _insert_denied(rls_session, config_sql, base)

    # Lowest role that may confirm (write addenda): lead_estimator (member).
    lead = _ctx(frozenset({"lead_estimator"}), tenant_id=a["tenant"], user_id=member)
    await set_rls_context(rls_session, lead)
    await _insert_ok(rls_session, link_sql, base)
    await _insert_denied(rls_session, config_sql, base)
    # A second addendum for the same document violates the unique constraint (not RLS): one register row per document.
    with pytest.raises(Exception, match=r"(?i)uq_addenda_document|duplicate key"):
        async with rls_session.begin_nested():
            await rls_session.execute(text(addendum_sql), base)

    # Only managing_director edits class configuration.
    md = _ctx(frozenset({"managing_director"}), tenant_id=a["tenant"])
    await set_rls_context(rls_session, md)
    await _insert_ok(rls_session, config_sql, base)


async def test_class_config_read_is_open_but_bd_director_cannot_change_it(rls_session):
    member = uuid.uuid4()
    a = await _seed_tenant(rls_session, member)
    await set_rls_context(rls_session, _ctx(frozenset({"bd_director"}), tenant_id=a["tenant"]))
    assert (await rls_session.execute(text("SELECT count(*) FROM tender_class_config"))).scalar_one() == 1
    await _insert_denied(
        rls_session, "INSERT INTO tender_class_config (tenant_id, code, label) VALUES (:t, 'contract', 'C')", {"t": str(a["tenant"])}
    )
    # An UPDATE by a non-MD role affects zero rows (USING clause hides them).
    async with rls_session.begin_nested():
        res = await rls_session.execute(text("UPDATE tender_class_config SET label = 'hacked' WHERE code = 'boq'"))
        assert res.rowcount == 0
