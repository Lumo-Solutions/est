"""Parses the tenant-slug + RFQ reply-token out of a plus-addressed
recipient, e.g. `rfq+acme-co.AbCdEf...@installtec.local`.

This is deliberately independent of which literal IMAP mailbox a message was
polled from: a real mail provider (Gmail, Office 365, Postfix with
recipient_delimiter=+) folds `local+ext@domain` into `local@domain` for
routing purposes but leaves the message's own To: header exactly as the
sender addressed it, so parsing that header text works the same whether the
poller is reading one shared production mailbox or a dev/test mailbox that
has no such folding (see app/workers/tasks/quotation_ingestion.py and
docs/procurement-quotation-ingestion.md for why GreenMail, not Mailpit, is
the dev IMAP server).

Format: `{EMAIL_REPLY_TO_LOCAL_PART}+{tenant_slug}.{reply_token}@{EMAIL_REPLY_TO_DOMAIN}`.
`reply_token` is `secrets.token_urlsafe(32)` (alphabet: A-Za-z0-9-_), which
never contains '.', so splitting the extension on the *first* '.' safely
separates the two even though tenant slugs may contain '-'.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings


@dataclass(frozen=True, slots=True)
class ParsedReplyAddress:
    tenant_slug: str
    reply_token: str


def build_reply_address(*, tenant_slug: str, reply_token: str, settings: Settings) -> str:
    return f"{settings.email_reply_to_local_part}+{tenant_slug}.{reply_token}@{settings.email_reply_to_domain}"


def parse_reply_address(address: str, settings: Settings) -> ParsedReplyAddress | None:
    """Returns None for anything that isn't structurally one of our own
    reply addresses (wrong local part/domain, no '+' extension, no '.'
    separator inside it) -- the caller treats that the same as an unknown
    tenant, never as a parse error worth crashing the poller over."""
    address = address.strip()
    if "@" not in address:
        return None
    local, _, domain = address.rpartition("@")
    if domain.lower() != settings.email_reply_to_domain.lower():
        return None
    base, sep, extension = local.partition("+")
    if not sep or base.lower() != settings.email_reply_to_local_part.lower():
        return None
    tenant_slug, dot, reply_token = extension.partition(".")
    if not dot or not tenant_slug or not reply_token:
        return None
    return ParsedReplyAddress(tenant_slug=tenant_slug, reply_token=reply_token)
