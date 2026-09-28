"""Phase 3 gap-fill (docs/ui-qa-brief.md): home dashboard's "certificates
expiring" tile -- app/services/prequal.py::list_expiring_certificates.
Across every vendor, not one at a time, with a human-readable vendor name
(a bare vendor_id isn't useful on a dashboard card)."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import text

from app.services import prequal as prequal_service

pytestmark = pytest.mark.asyncio

TENANT = "8f14e45f-ceea-4e97-8d0c-3d3b3f3c1a00"


@pytest.fixture(autouse=True)
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
    authority_id = str(
        (
            await session.execute(
                text(
                    "INSERT INTO authorities (tenant_id, code, name) VALUES (:t, 'DM', 'Dubai Municipality') "
                    "RETURNING id"
                ),
                {"t": TENANT},
            )
        ).scalar_one()
    )
    result = await session.execute(
        text(
            "INSERT INTO certificate_types (tenant_id, authority_id, code, name, is_mandatory, warn_days_before) "
            "VALUES (:t, :a, 'TRADE-LIC', 'Trade License', true, 30) RETURNING id"
        ),
        {"t": TENANT, "a": authority_id},
    )
    return str(result.scalar_one())


async def _create_certificate(session, vendor_id: str, cert_type_id: str, expiry_date: date) -> str:
    result = await session.execute(
        text(
            "INSERT INTO vendor_certificates (tenant_id, vendor_id, certificate_type_id, expiry_date, status) "
            "VALUES (:t, :v, :c, :e, 'pending_verification') RETURNING id"
        ),
        {"t": TENANT, "v": vendor_id, "c": cert_type_id, "e": expiry_date},
    )
    return str(result.scalar_one())


async def test_returns_certificates_within_the_window_with_the_vendors_name(rls_session):
    vendor_id = await _create_vendor(rls_session, "Expiring Soon LLC")
    cert_type_id = await _create_certificate_type(rls_session)
    expiring_id = await _create_certificate(rls_session, vendor_id, cert_type_id, date.today() + timedelta(days=10))
    already_expired_id = await _create_certificate(rls_session, vendor_id, cert_type_id, date.today() - timedelta(days=5))

    rows = await prequal_service.list_expiring_certificates(rls_session, days=30)

    ids = {str(r["id"]) for r in rows}
    assert expiring_id in ids
    assert already_expired_id in ids  # already-expired counts as needing attention too
    matching = next(r for r in rows if str(r["id"]) == expiring_id)
    assert matching["vendor_name"] == "Expiring Soon LLC"


async def test_excludes_certificates_outside_the_window_and_never_expiring_ones(rls_session):
    vendor_id = await _create_vendor(rls_session, "Fine For Now LLC")
    cert_type_id = await _create_certificate_type(rls_session)
    far_future_id = await _create_certificate(rls_session, vendor_id, cert_type_id, date.today() + timedelta(days=365))

    rows = await prequal_service.list_expiring_certificates(rls_session, days=30)

    assert far_future_id not in {str(r["id"]) for r in rows}


async def test_orders_soonest_expiry_first(rls_session):
    vendor_id = await _create_vendor(rls_session, "Ordering Test LLC")
    cert_type_id = await _create_certificate_type(rls_session)
    later_id = await _create_certificate(rls_session, vendor_id, cert_type_id, date.today() + timedelta(days=20))
    sooner_id = await _create_certificate(rls_session, vendor_id, cert_type_id, date.today() + timedelta(days=5))

    rows = await prequal_service.list_expiring_certificates(rls_session, days=30)
    ordered_ids = [str(r["id"]) for r in rows if str(r["id"]) in {later_id, sooner_id}]

    assert ordered_ids == [sooner_id, later_id]
