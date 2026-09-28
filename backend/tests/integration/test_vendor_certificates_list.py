"""Phase 3 gap-fill (docs/ui-qa-brief.md): GET /vendors/{id}/certificates
-- app/services/prequal.py::list_certificates_for_vendor. Only single-cert
add/verify existed before; a certificates screen with expiry alerts needs
every certificate for a vendor, ordered so the soonest-expiring one (or a
never-expiring one, sorted last) is easy to find."""

from __future__ import annotations

import uuid
from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.services import prequal as prequal_service

pytestmark = pytest.mark.asyncio

TENANT = "8f14e45f-ceea-4e97-8d0c-3d3b3f3c1a00"


@pytest_asyncio.fixture(autouse=True)
async def _set_guc(rls_session) -> None:
    await rls_session.execute(
        text(
            "SELECT set_config('app.tenant_id', :t, false), set_config('app.user_id', :u, false), "
            "set_config('app.roles', 'procurement_head', false), set_config('app.is_system', 'off', false)"
        ),
        {"t": TENANT, "u": str(uuid.uuid4())},
    )


async def _create_vendor(session, name: str) -> str:
    result = await session.execute(
        text(
            "INSERT INTO vendors (tenant_id, legal_name, normalized_name, status) "
            "VALUES (:t, :n, :n, 'draft') RETURNING id"
        ),
        {"t": TENANT, "n": name},
    )
    return str(result.scalar_one())


async def _create_certificate_type(session) -> str:
    result = await session.execute(
        text(
            "INSERT INTO authorities (tenant_id, code, name) VALUES (:t, 'DM', 'Dubai Municipality') "
            "RETURNING id"
        ),
        {"t": TENANT},
    )
    authority_id = str(result.scalar_one())
    result = await session.execute(
        text(
            "INSERT INTO certificate_types (tenant_id, authority_id, code, name, is_mandatory, warn_days_before) "
            "VALUES (:t, :a, 'TRADE-LIC', 'Trade License', true, 30) RETURNING id"
        ),
        {"t": TENANT, "a": authority_id},
    )
    return str(result.scalar_one())


async def _create_certificate(session, vendor_id: str, cert_type_id: str, expiry_date: str | None) -> str:
    result = await session.execute(
        text(
            "INSERT INTO vendor_certificates (tenant_id, vendor_id, certificate_type_id, expiry_date, status) "
            "VALUES (:t, :v, :c, :e, 'pending_verification') RETURNING id"
        ),
        {"t": TENANT, "v": vendor_id, "c": cert_type_id, "e": date.fromisoformat(expiry_date) if expiry_date else None},
    )
    return str(result.scalar_one())


async def test_lists_every_certificate_for_the_vendor_soonest_expiry_first(rls_session):
    vendor_id = await _create_vendor(rls_session, "CERT VENDOR 1")
    cert_type_id = await _create_certificate_type(rls_session)
    never_expires = await _create_certificate(rls_session, vendor_id, cert_type_id, None)
    expires_soon = await _create_certificate(rls_session, vendor_id, cert_type_id, "2026-01-01")
    expires_later = await _create_certificate(rls_session, vendor_id, cert_type_id, "2027-01-01")

    rows = await prequal_service.list_certificates_for_vendor(rls_session, uuid.UUID(vendor_id))

    assert [str(r.id) for r in rows] == [expires_soon, expires_later, never_expires]


async def test_a_different_vendor_sees_no_certificates(rls_session):
    vendor_id = await _create_vendor(rls_session, "CERT VENDOR 2")
    other_vendor_id = await _create_vendor(rls_session, "CERT VENDOR 3")
    cert_type_id = await _create_certificate_type(rls_session)
    await _create_certificate(rls_session, vendor_id, cert_type_id, "2026-01-01")

    rows = await prequal_service.list_certificates_for_vendor(rls_session, uuid.UUID(other_vendor_id))

    assert rows == []
