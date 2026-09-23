"""Exercises the real BEFORE INSERT trigger (audit_events_chain_trg) and
immutability guards against a live Postgres, then cross-checks the stored
hashes with services/audit.py's Python-side verifier -- the same two
properties (chain correctness, tamper detection) validated manually
against a live container during development.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy import text

from app.services.audit import ChainVerificationError, verify_chain

pytestmark = pytest.mark.asyncio

TENANT = uuid.UUID("8f14e45f-ceea-4e97-8d0c-3d3b3f3c1a00")


async def _set_guc(session, *, roles: str = "lead_estimator") -> None:
    await session.execute(
        text(
            "SELECT set_config('app.tenant_id', :t, false), set_config('app.user_id', :u, false), "
            "set_config('app.roles', :r, false), set_config('app.is_system', 'off', false)"
        ),
        {"t": str(TENANT), "u": str(uuid.uuid4()), "r": roles},
    )


async def _insert_event(session, entity_id: str) -> None:
    await session.execute(
        text(
            "INSERT INTO audit_events (tenant_id, chain_date, seq, occurred_at, actor_sub, actor_roles, "
            "action, entity_type, entity_id, payload, payload_sha256, prev_hash, event_hash, canonical_json) "
            "VALUES (:t, CURRENT_DATE, 0, now(), 'testuser', ARRAY['lead_estimator'], 'create', "
            "'vendor', :eid, :payload, '', '', '', '')"
        ),
        {"t": str(TENANT), "eid": entity_id, "payload": '{"k": "v"}'},
    )


async def test_chain_assigns_contiguous_sequence_and_links_hashes(rls_session):
    await _set_guc(rls_session)
    for i in range(3):
        await _insert_event(rls_session, f"entity-{i}")

    result = await rls_session.execute(
        text("SELECT seq, prev_hash, event_hash FROM audit_events WHERE tenant_id = :t ORDER BY seq"),
        {"t": str(TENANT)},
    )
    rows = result.all()
    assert [r[0] for r in rows] == [1, 2, 3]
    assert rows[0][1] == "0" * 64  # genesis prev_hash
    assert rows[1][1] == rows[0][2]  # seq 2's prev_hash == seq 1's event_hash
    assert rows[2][1] == rows[1][2]
    assert len({r[2] for r in rows}) == 3  # all event hashes distinct


async def test_stored_hashes_rehash_correctly(rls_session):
    await _set_guc(rls_session)
    await _insert_event(rls_session, "rehash-test")
    result = await rls_session.execute(
        text(
            "SELECT encode(digest(prev_hash || '|' || canonical_json, 'sha256'), 'hex') = event_hash "
            "FROM audit_events WHERE entity_id = 'rehash-test'"
        )
    )
    assert result.scalar_one() is True


async def test_update_is_rejected(rls_session):
    await _set_guc(rls_session)
    await _insert_event(rls_session, "no-update")
    # pytest.raises MUST be the outer context manager: begin_nested() only
    # rolls back the savepoint when IT sees the exception propagate through
    # its own __aexit__. If pytest.raises is nested inside instead, it
    # swallows the exception first, so begin_nested() exits "normally" and
    # tries to RELEASE (commit) a savepoint that's actually in Postgres's
    # aborted-transaction state -- which itself raises.
    with pytest.raises(Exception, match=r"(?i)permission denied|immutable"):
        async with rls_session.begin_nested():
            await rls_session.execute(
                text("UPDATE audit_events SET action = 'delete' WHERE entity_id = 'no-update'")
            )


async def test_delete_is_rejected(rls_session):
    await _set_guc(rls_session)
    await _insert_event(rls_session, "no-delete")
    with pytest.raises(Exception, match=r"(?i)permission denied|immutable"):
        async with rls_session.begin_nested():
            await rls_session.execute(text("DELETE FROM audit_events WHERE entity_id = 'no-delete'"))


async def test_verify_chain_passes_on_untampered_data(rls_session):
    await _set_guc(rls_session)
    await _insert_event(rls_session, "verify-ok")
    today = date.today()
    await verify_chain(rls_session, TENANT, today, today)  # raises on failure; no exception == pass


async def test_verify_chain_detects_tampering(postgres_container):
    """installtec_app cannot tamper audit_events at all (REVOKE + RLS +
    trigger all block it, which is the point) -- to prove verify_chain()
    actually catches a corrupted row, this connects as the migrator/owner
    role, disables the trigger just long enough to hand-craft a row with a
    wrong event_hash (simulating e.g. direct storage-level corruption), then
    re-enables it and asserts detection."""
    from sqlalchemy import text as sql
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    engine = create_async_engine(postgres_container)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session, session.begin():
            # FORCE ROW LEVEL SECURITY applies even to the owning role, so
            # this still needs app_is_system() to satisfy the INSERT policy.
            await session.execute(sql("SELECT set_config('app.is_system', 'on', false)"))
            await session.execute(sql("ALTER TABLE audit_events DISABLE TRIGGER audit_events_chain_trg"))
            await session.execute(
                sql(
                    "INSERT INTO audit_events (tenant_id, chain_date, seq, occurred_at, actor_sub, "
                    "actor_roles, action, entity_type, entity_id, payload, payload_sha256, prev_hash, "
                    "event_hash, canonical_json) VALUES "
                    "(:t, CURRENT_DATE, 999999, now(), 'tamperer', ARRAY['managing_director'], 'create', "
                    "'vendor', 'tampered', '{}'::jsonb, "
                    "encode(digest('{}', 'sha256'), 'hex'), "
                    "repeat('0', 64), repeat('a', 64), 'not-the-real-canonical-json')"
                ),
                {"t": str(TENANT)},
            )
            await session.execute(sql("ALTER TABLE audit_events ENABLE TRIGGER audit_events_chain_trg"))

            with pytest.raises(ChainVerificationError):
                await verify_chain(session, TENANT, date.today(), date.today())
    finally:
        # No cleanup: audit_events has no DELETE policy at all (by design --
        # see audit_insert_only_policies), so even the owning role can't
        # remove this row without BYPASSRLS. Harmless in the ephemeral,
        # session-scoped test container; its seq=999999 never collides with
        # trigger-assigned seq values from other tests in this file.
        await engine.dispose()
