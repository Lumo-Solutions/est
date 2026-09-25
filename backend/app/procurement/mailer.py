"""SMTP dispatch for RFQ emails, with a fail-closed dev/staging safety net.

resolve_recipient() is the load-bearing function here: whenever
APP_ENV != "production" it substitutes EMAIL_REDIRECT_ALL_TO for the
vendor's real address, and raises rather than silently falling through to
the vendor's address if that setting is empty -- see
tests/unit/test_mailer_redirect.py and docs/procurement-rfq.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import make_msgid

import aiosmtplib

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.procurement.inbound_address import build_reply_address

logger = get_logger(__name__)


class EmailMisconfiguredError(RuntimeError):
    """A non-production environment has no EMAIL_REDIRECT_ALL_TO configured.
    Fails closed: better to refuse dispatch than risk emailing a real
    vendor from a dev/staging environment."""


@dataclass(frozen=True, slots=True)
class ResolvedRecipient:
    to_address: str
    original_to: str | None  # set only when this was redirected


def resolve_recipient(vendor_email: str, settings: Settings) -> ResolvedRecipient:
    if settings.app_env == "production":
        return ResolvedRecipient(to_address=vendor_email, original_to=None)
    redirect_to = settings.email_redirect_all_to
    if not redirect_to:
        raise EmailMisconfiguredError(
            "EMAIL_REDIRECT_ALL_TO must be set whenever APP_ENV != 'production' -- "
            "refusing to dispatch an RFQ email that could reach a real vendor "
            "address from a non-production environment."
        )
    return ResolvedRecipient(to_address=redirect_to, original_to=vendor_email)


@dataclass(frozen=True, slots=True)
class SentEmail:
    to_address: str
    original_to: str | None
    message_id: str


async def send_rfq_email(
    *,
    vendor_email: str,
    subject: str,
    html_body: str,
    attachment_bytes: bytes,
    attachment_filename: str,
    reply_token: str,
    tenant_slug: str,
    settings: Settings | None = None,
) -> SentEmail:
    settings = settings or get_settings()
    recipient = resolve_recipient(vendor_email, settings)
    if recipient.original_to:
        logger.info("rfq_email_redirected", original_to=recipient.original_to, redirected_to=recipient.to_address)

    message = EmailMessage()
    message["From"] = settings.smtp_from_address
    message["To"] = recipient.to_address
    message["Subject"] = subject
    # Plus-addressing Reply-To embeds both the tenant slug and the reply
    # token (see app/procurement/inbound_address.py) so Module C2's IMAP
    # poller can identify the tenant straight from the recipient address --
    # independent of whether the reply-token lookup itself succeeds -- and
    # correlate the reply back to this exact Rfq row.
    message["Reply-To"] = build_reply_address(tenant_slug=tenant_slug, reply_token=reply_token, settings=settings)
    message_id = make_msgid(domain=settings.email_reply_to_domain)
    message["Message-ID"] = message_id
    message.set_content("This message requires an HTML-capable email client to view the RFQ.")
    message.add_alternative(html_body, subtype="html")
    message.add_attachment(
        attachment_bytes,
        maintype="application",
        subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=attachment_filename,
    )

    await aiosmtplib.send(
        message,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_user or None,
        password=settings.smtp_password or None,
        use_tls=settings.smtp_use_tls,
    )
    return SentEmail(to_address=recipient.to_address, original_to=recipient.original_to, message_id=message_id)
