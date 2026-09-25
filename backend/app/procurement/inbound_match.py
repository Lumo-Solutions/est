"""Sender/RFQ matching for one polled inbound email -- SRS requirement #1
and change #5.

Tenant identification and reply-token matching are two independent checks:
a message is only ever auto-processed (deterministic/LLM parsing) when BOTH
resolve to an open RFQ AND the sender identity check and SPF/DKIM/DMARC
checks raise no flag. Any single failure sends it to needs_review; nothing
here ever silently attaches an email to the wrong RFQ or vendor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.enums import InboundEmailMatchStatus, RfqStatus
from app.models.procurement import Rfq
from app.models.tenancy import Tenant
from app.models.vendors import Vendor, VendorContact
from app.procurement.email_auth import AuthResults, has_auth_failure
from app.procurement.inbound_address import parse_reply_address

# Sender-identity check for these domains compares the exact From address
# against the vendor's known contact emails, not just the domain -- anyone
# can register a gmail.com address, so "the domain matches" proves nothing
# for a free-mail sender (SRS change #5).
FREE_MAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com", "msn.com",
    "yahoo.com", "yahoo.co.uk", "icloud.com", "me.com", "aol.com", "protonmail.com",
    "proton.me", "gmx.com", "mail.com", "zoho.com",
}

_OPEN_RFQ_STATUSES = {RfqStatus.SENT.value, RfqStatus.RESPONDED.value}


@dataclass(frozen=True, slots=True)
class MatchOutcome:
    tenant_id: UUID | None
    rfq_id: UUID | None
    match_status: str
    needs_review: bool
    review_reasons: list[str] = field(default_factory=list)


async def _sender_identity_reason(session: AsyncSession, *, from_address: str, rfq: Rfq) -> str | None:
    """Returns a review-reason string if the sender can't be verified as the
    RFQ's own vendor, or None if it checks out."""
    from_domain = from_address.rsplit("@", 1)[-1].lower()
    vendor = (await session.execute(select(Vendor).where(Vendor.id == rfq.vendor_id))).scalar_one_or_none()
    if vendor is None:
        return "vendor_not_found"
    contacts = (await session.execute(select(VendorContact).where(VendorContact.vendor_id == vendor.id))).scalars().all()
    known_emails = {c.email.lower() for c in contacts if c.email} | ({vendor.primary_email.lower()} if vendor.primary_email else set())

    if from_domain in FREE_MAIL_DOMAINS:
        if from_address.lower() not in known_emails:
            return "free_mail_sender_not_an_exact_known_contact"
        return None

    known_domains = {e.rsplit("@", 1)[-1] for e in known_emails}
    if vendor.email_domain:
        known_domains.add(vendor.email_domain.lower())
    if not known_domains:
        return "vendor_has_no_known_email_domain_on_file"
    if from_domain not in known_domains:
        return "sender_domain_does_not_match_vendor"
    return None


async def match_inbound_email(
    session: AsyncSession, *, from_address: str, to_address: str, auth_results: AuthResults, settings: Settings
) -> MatchOutcome:
    reasons: list[str] = []
    if has_auth_failure(auth_results):
        reasons.append("spf_dkim_or_dmarc_failed")

    parsed = parse_reply_address(to_address, settings)
    if parsed is None:
        return MatchOutcome(None, None, InboundEmailMatchStatus.QUARANTINED_UNKNOWN_TENANT.value, True, reasons + ["recipient_address_not_recognized"])

    tenant = (await session.execute(select(Tenant).where(Tenant.slug == parsed.tenant_slug))).scalar_one_or_none()
    if tenant is None:
        return MatchOutcome(None, None, InboundEmailMatchStatus.QUARANTINED_UNKNOWN_TENANT.value, True, reasons + ["tenant_slug_not_recognized"])

    rfq = (
        await session.execute(select(Rfq).where(Rfq.tenant_id == tenant.id, Rfq.reply_token == parsed.reply_token))
    ).scalar_one_or_none()
    if rfq is None:
        return MatchOutcome(tenant.id, None, InboundEmailMatchStatus.QUARANTINED_NO_TOKEN.value, True, reasons + ["reply_token_not_found"])
    if rfq.status not in _OPEN_RFQ_STATUSES:
        return MatchOutcome(tenant.id, rfq.id, InboundEmailMatchStatus.QUARANTINED_TOKEN_CLOSED.value, True, reasons + [f"rfq_status_is_{rfq.status}"])

    identity_reason = await _sender_identity_reason(session, from_address=from_address, rfq=rfq)
    if identity_reason:
        reasons.append(identity_reason)

    return MatchOutcome(tenant.id, rfq.id, InboundEmailMatchStatus.MATCHED.value, bool(reasons), reasons)
